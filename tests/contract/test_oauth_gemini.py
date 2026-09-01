from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from redditctl.credentials import MemoryCredentialStore
from redditctl.domain import DraftContent, Rule, RuleSnapshot
from redditctl.drafting.gemini import GeminiGateway
from redditctl.drafting.models import DraftRequest, ReviewRequest
from redditctl.errors import AuthenticationError
from redditctl.reddit.oauth import RedditOAuth, RedditTokenProvider


@pytest.mark.asyncio
async def test_reddit_oauth_exchange_refresh_and_cache() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        grant = request.content.decode()
        if "authorization_code" in grant:
            return httpx.Response(
                200, json={"access_token": "first", "expires_in": 3600, "refresh_token": "refresh"}
            )
        return httpx.Response(200, json={"access_token": "second", "expires_in": 3600})

    store = MemoryCredentialStore()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        oauth = RedditOAuth("client", "http://127.0.0.1:8765/callback", http)
        assert "duration=permanent" in oauth.authorization_url("state", ("identity", "read"))
        tokens = await oauth.exchange_code("code")
        provider = RedditTokenProvider(oauth, store)
        provider.store(tokens)
        provider._access_token = None
        assert await provider.get_access_token() == "second"
        assert await provider.get_access_token() == "second"
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_reddit_token_provider_requires_authorization() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as http:
        provider = RedditTokenProvider(
            RedditOAuth("client", "http://127.0.0.1:8765/callback", http),
            MemoryCredentialStore(),
        )
        with pytest.raises(AuthenticationError):
            await provider.get_access_token()


class FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        schema = kwargs["config"].response_schema
        if schema.__name__ == "DraftProposalDto":
            payload = {"titles": ["One"], "body": "Body", "assumptions": ["Verify"]}
        else:
            payload = {
                "findings": [{"severity": "warning", "code": "check", "message": "Review it"}]
            }
        return type("Response", (), {"parsed": None, "text": json.dumps(payload)})()


class FakeGenaiClient:
    def __init__(self) -> None:
        self.models = FakeModels()


@pytest.mark.asyncio
async def test_gemini_uses_structured_schema_for_draft_and_review() -> None:
    rules = RuleSnapshot.create(
        "python", "url", datetime.now(UTC), [Rule("1", "Relevant", "On topic")]
    )
    client = FakeGenaiClient()
    gateway = GeminiGateway(client, "model")
    proposal = await gateway.draft(DraftRequest("my notes", "python", rules))
    review = await gateway.review(ReviewRequest(DraftContent("python", "One", "Body"), rules))
    assert proposal.titles == ("One",)
    assert proposal.assumptions == ("Verify",)
    assert review.findings[0].code == "check"
    assert len(client.models.calls) == 2
