from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from redditctl.errors import AuthenticationError, ValidationError
from redditctl.links import LinkRelayClient
from redditctl.relay import RelayStore, create_relay_app


@pytest.mark.asyncio
async def test_relay_mapping_redirect_and_aggregate_stats(tmp_path: Path) -> None:
    app = create_relay_app(RelayStore(tmp_path / "relay.db"), "secret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://relay.test") as http:
        client = LinkRelayClient("https://relay.test", "secret", http)
        await client.create_mapping("launch", "https://example.com/product")
        response = await http.get(
            "/r/launch",
            headers={"referer": "https://www.reddit.com/r/python", "user-agent": "browser"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "https://example.com/product"
        stats = await client.stats("launch")
    assert len(stats.buckets) == 1
    assert stats.buckets[0].referrer_class == "reddit"
    assert not stats.buckets[0].bot


@pytest.mark.asyncio
async def test_relay_rejects_bad_admin_token_and_destination(tmp_path: Path) -> None:
    app = create_relay_app(RelayStore(tmp_path / "relay.db"), "secret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://relay.test") as http:
        unauthorized = await http.get("/admin/stats/nope")
        bad_url = await http.post(
            "/admin/mappings",
            headers={"authorization": "Bearer secret"},
            json={"slug": "valid-slug", "destination": "http://example.com"},
        )
        missing = await http.get("/r/missing")
    assert unauthorized.status_code == 401
    assert bad_url.status_code == 400
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_relay_client_maps_auth_and_schema_errors() -> None:
    responses = iter([httpx.Response(401), httpx.Response(200, json={"not": "stats"})])
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: next(responses))
    ) as http:
        client = LinkRelayClient("https://relay.test", "wrong", http)
        with pytest.raises(AuthenticationError):
            await client.stats("launch")
        with pytest.raises(ValidationError, match="invalid statistics"):
            await client.stats("launch")
