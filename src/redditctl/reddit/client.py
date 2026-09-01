from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from redditctl.domain import (
    Account,
    DraftContent,
    RecommendationCandidate,
    Rule,
    RuleSnapshot,
    Thing,
    ThingKind,
)
from redditctl.errors import (
    AuthenticationError,
    NetworkError,
    PermissionDeniedError,
    RateLimitedError,
    ValidationError,
)


class TokenProvider(Protocol):
    async def get_access_token(self) -> str: ...


class RedditGateway(Protocol):
    async def me(self) -> Account: ...

    async def owned_content(self, username: str, *, limit: int = 100) -> list[Thing]: ...

    async def subreddit_rules(self, subreddit: str) -> RuleSnapshot: ...

    async def search_communities(
        self, query: str, *, limit: int = 20
    ) -> list[RecommendationCandidate]: ...

    async def community_samples(self, subreddit: str, *, limit: int = 10) -> list[str]: ...

    async def submit(self, draft: DraftContent) -> str: ...

    async def edit(self, fullname: str, body: str) -> str: ...

    async def comment(self, parent_fullname: str, body: str) -> str: ...


class MeDto(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    created_utc: float


class ChildDataDto(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    subreddit: str = ""
    created_utc: float
    title: str = ""
    selftext: str = ""
    body: str = ""
    url: str | None = None
    permalink: str | None = None
    score: int | None = None
    num_comments: int | None = None
    is_self: bool = False


class ChildDto(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str
    data: ChildDataDto


class ListingDataDto(BaseModel):
    model_config = ConfigDict(extra="ignore")
    children: list[ChildDto] = Field(default_factory=list)
    after: str | None = None


class ListingDto(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: ListingDataDto


class RedditClient:
    def __init__(
        self,
        token_provider: TokenProvider,
        http: httpx.AsyncClient,
        *,
        base_url: str = "https://oauth.reddit.com",
        user_agent: str = "redditctl/0.1 by its authenticated user",
    ) -> None:
        self.token_provider = token_provider
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.last_rate_remaining: float | None = None
        self.last_rate_reset: float | None = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int | float | bool | None] | None = None,
        data: dict[str, object] | None = None,
    ) -> Any:
        token = await self.token_provider.get_access_token()
        headers = {"Authorization": f"Bearer {token}", "User-Agent": self.user_agent}
        params = {**(params or {}), "raw_json": 1}
        try:
            response = await self.http.request(
                method, f"{self.base_url}{path}", params=params, data=data, headers=headers
            )
        except httpx.HTTPError as exc:
            raise NetworkError(f"Reddit request failed: {method} {path}") from exc
        if remaining := response.headers.get("x-ratelimit-remaining"):
            self.last_rate_remaining = float(remaining)
        if reset := response.headers.get("x-ratelimit-reset"):
            self.last_rate_reset = float(reset)
        if response.status_code == 401:
            raise AuthenticationError("Reddit rejected the access token")
        if response.status_code == 403:
            raise PermissionDeniedError("Reddit denied this operation")
        if response.status_code == 429:
            raise RateLimitedError("Reddit rate limit reached")
        if response.status_code >= 500:
            raise NetworkError(f"Reddit returned HTTP {response.status_code}")
        if response.status_code >= 400:
            raise ValidationError(
                f"Reddit returned HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ValidationError("Reddit returned invalid JSON") from exc

    async def me(self) -> Account:
        try:
            dto = MeDto.model_validate(await self._request("GET", "/api/v1/me"))
        except PydanticValidationError as exc:
            raise ValidationError("Reddit identity response changed shape") from exc
        return Account(dto.id, dto.name, datetime.fromtimestamp(dto.created_utc, UTC))

    async def owned_content(self, username: str, *, limit: int = 100) -> list[Thing]:
        result: list[Thing] = []
        after: str | None = None
        while len(result) < limit:
            params: dict[str, str | int | float | bool | None] = {
                "limit": min(100, limit - len(result)),
                "sort": "new",
            }
            if after:
                params["after"] = after
            payload = await self._request("GET", f"/user/{username}/overview", params=params)
            try:
                listing = ListingDto.model_validate(payload)
            except PydanticValidationError as exc:
                raise ValidationError("Reddit listing response changed shape") from exc
            for child in listing.data.children:
                data = child.data
                kind = ThingKind.COMMENT if child.kind == "t1" else ThingKind.SUBMISSION
                result.append(
                    Thing(
                        fullname=data.name,
                        kind=kind,
                        subreddit=data.subreddit,
                        created_at=datetime.fromtimestamp(data.created_utc, UTC),
                        title=data.title,
                        body=data.body if kind is ThingKind.COMMENT else data.selftext,
                        url=data.url,
                        permalink=data.permalink,
                        score=data.score,
                        reply_count=data.num_comments if kind is ThingKind.SUBMISSION else None,
                        is_self=data.is_self,
                    )
                )
            after = listing.data.after
            if not after:
                break
        return result[:limit]

    async def subreddit_rules(self, subreddit: str) -> RuleSnapshot:
        payload = await self._request("GET", f"/r/{subreddit}/about/rules")
        rules: list[Rule] = []
        for index, item in enumerate(payload.get("rules", []), start=1):
            rules.append(
                Rule(
                    rule_id=str(item.get("violation_reason") or index),
                    short_name=str(item.get("short_name", "")),
                    body=str(item.get("description", "")),
                    applies_to=item.get("kind"),
                )
            )
        return RuleSnapshot.create(
            subreddit,
            f"https://www.reddit.com/r/{subreddit}/about/rules",
            datetime.now(UTC),
            rules,
        )

    async def search_communities(
        self, query: str, *, limit: int = 20
    ) -> list[RecommendationCandidate]:
        payload = await self._request(
            "GET", "/subreddits/search", params={"q": query, "limit": limit, "sort": "relevance"}
        )
        candidates: list[RecommendationCandidate] = []
        for child in payload.get("data", {}).get("children", []):
            data = child.get("data", {})
            name = str(data.get("display_name", ""))
            if not name:
                continue
            candidates.append(
                RecommendationCandidate(
                    name=name,
                    title=str(data.get("title", "")),
                    description=str(data.get("public_description", "")),
                    rules_text="",
                    sample_text="",
                    subscribers=data.get("subscribers"),
                    active=data.get("subreddit_type") not in {"private", "restricted"},
                    nsfw=bool(data.get("over18", False)),
                )
            )
        return candidates

    async def community_samples(self, subreddit: str, *, limit: int = 10) -> list[str]:
        payload = await self._request("GET", f"/r/{subreddit}/new", params={"limit": limit})
        try:
            listing = ListingDto.model_validate(payload)
        except PydanticValidationError as exc:
            raise ValidationError("Reddit community listing response changed shape") from exc
        return [
            f"{child.data.title}\n{child.data.selftext}".strip()
            for child in listing.data.children
            if child.kind == "t3"
        ]

    async def submit(self, draft: DraftContent) -> str:
        data: dict[str, object] = {
            "api_type": "json",
            "sr": draft.subreddit,
            "title": draft.title,
            "kind": "link" if draft.kind == "link" else "self",
            "resubmit": True,
        }
        if draft.kind == "link":
            data["url"] = draft.url or ""
        else:
            data["text"] = draft.body
        if draft.flair_id:
            data["flair_id"] = draft.flair_id
        payload = await self._request("POST", "/api/submit", data=data)
        return self._mutation_name(payload)

    async def edit(self, fullname: str, body: str) -> str:
        payload = await self._request(
            "POST",
            "/api/editusertext",
            data={"api_type": "json", "thing_id": fullname, "text": body},
        )
        return self._mutation_name(payload, fallback=fullname)

    async def comment(self, parent_fullname: str, body: str) -> str:
        payload = await self._request(
            "POST",
            "/api/comment",
            data={"api_type": "json", "thing_id": parent_fullname, "text": body},
        )
        return self._mutation_name(payload)

    @staticmethod
    def _mutation_name(payload: dict[str, Any], fallback: str | None = None) -> str:
        errors = payload.get("json", {}).get("errors", [])
        if errors:
            raise ValidationError(f"Reddit rejected the operation: {errors[0][1]}")
        data = payload.get("json", {}).get("data", {})
        name = data.get("name") or data.get("things", [{}])[0].get("data", {}).get("name")
        if name:
            return str(name)
        if fallback:
            return fallback
        raise ValidationError("Reddit accepted the request without returning a content identifier")
