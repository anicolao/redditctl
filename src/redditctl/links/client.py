from __future__ import annotations

from datetime import datetime
from typing import cast

import httpx
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from redditctl.errors import AuthenticationError, NetworkError, ValidationError


class LinkBucket(BaseModel):
    bucket_at: datetime
    referrer_class: str
    bot: bool
    count: int = Field(ge=0)


class StatsResponse(BaseModel):
    slug: str
    buckets: list[LinkBucket]


class LinkRelayClient:
    def __init__(self, base_url: str, admin_token: str, http: httpx.AsyncClient) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self.http = http

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.admin_token}"}

    async def create_mapping(self, slug: str, destination: str) -> None:
        response = await self._request(
            "POST", "/admin/mappings", json={"slug": slug, "destination": destination}
        )
        if response.get("slug") != slug:
            raise ValidationError("Relay returned an invalid mapping response")

    async def stats(self, slug: str) -> StatsResponse:
        payload = await self._request("GET", f"/admin/stats/{slug}")
        try:
            return StatsResponse.model_validate(payload)
        except PydanticValidationError as exc:
            raise ValidationError("Relay returned invalid statistics") from exc

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
    ) -> dict[str, object]:
        try:
            response = await self.http.request(
                method, f"{self.base_url}{path}", headers=self.headers, json=json
            )
        except httpx.HTTPError as exc:
            raise NetworkError("Link relay is unavailable") from exc
        if response.status_code == 401:
            raise AuthenticationError("Link relay rejected the admin token")
        if response.status_code >= 400:
            raise ValidationError(f"Link relay returned HTTP {response.status_code}")
        try:
            return cast(dict[str, object], response.json())
        except ValueError as exc:
            raise ValidationError("Link relay returned invalid JSON") from exc
