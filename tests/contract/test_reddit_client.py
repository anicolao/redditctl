from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from redditctl.domain import DraftContent, ThingKind
from redditctl.errors import AuthenticationError, RateLimitedError, ValidationError
from redditctl.reddit import RedditClient
from redditctl.reddit.oauth import StaticTokenProvider


@pytest.fixture
def transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer token"
        if request.url.path == "/api/v1/me":
            return httpx.Response(200, json={"id": "u1", "name": "alice", "created_utc": 0})
        if request.url.path == "/user/alice/overview":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "after": None,
                        "children": [
                            {
                                "kind": "t3",
                                "data": {
                                    "name": "t3_one",
                                    "subreddit": "python",
                                    "created_utc": 1,
                                    "title": "Hello",
                                    "selftext": "Body",
                                    "score": 4,
                                    "num_comments": 2,
                                    "is_self": True,
                                },
                            }
                        ],
                    }
                },
            )
        if request.url.path == "/r/python/about/rules":
            return httpx.Response(
                200,
                json={"rules": [{"short_name": "Relevant", "description": "On topic"}]},
            )
        if request.url.path == "/subreddits/search":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "children": [
                            {
                                "data": {
                                    "display_name": "python",
                                    "title": "Python",
                                    "public_description": "Language",
                                    "subscribers": 10,
                                    "subreddit_type": "public",
                                }
                            }
                        ]
                    }
                },
            )
        if request.url.path == "/r/python/new":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "after": None,
                        "children": [
                            {
                                "kind": "t3",
                                "data": {
                                    "name": "t3_sample",
                                    "created_utc": 1,
                                    "title": "Recent topic",
                                    "selftext": "Discussion",
                                },
                            }
                        ],
                    }
                },
            )
        if request.url.path == "/api/submit":
            return httpx.Response(200, json={"json": {"errors": [], "data": {"name": "t3_new"}}})
        if request.url.path == "/api/editusertext":
            return httpx.Response(200, json={"json": {"errors": [], "data": {}}})
        if request.url.path == "/api/comment":
            return httpx.Response(
                200,
                json={
                    "json": {
                        "errors": [],
                        "data": {"things": [{"data": {"name": "t1_new"}}]},
                    }
                },
            )
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_reddit_reads_and_writes_contract(transport: httpx.MockTransport) -> None:
    async with httpx.AsyncClient(transport=transport) as http:
        client = RedditClient(StaticTokenProvider("token"), http, base_url="https://reddit.test")
        account = await client.me()
        things = await client.owned_content(account.username)
        rules = await client.subreddit_rules("python")
        communities = await client.search_communities("python")
        samples = await client.community_samples("python")
        remote = await client.submit(DraftContent("python", "Title", "Body"))
        edited = await client.edit("t3_old", "Updated")
        comment = await client.comment("t3_old", "Follow-up")
    assert account.created_at == datetime(1970, 1, 1, tzinfo=UTC)
    assert things[0].kind is ThingKind.SUBMISSION
    assert rules.rules[0].short_name == "Relevant"
    assert communities[0].name == "python"
    assert samples == ["Recent topic\nDiscussion"]
    assert remote == "t3_new"
    assert edited == "t3_old"
    assert comment == "t1_new"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error"),
    [(401, AuthenticationError), (429, RateLimitedError), (400, ValidationError)],
)
async def test_reddit_maps_http_errors(status: int, error: type[Exception]) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, text="no"))
    async with httpx.AsyncClient(transport=transport) as http:
        client = RedditClient(StaticTokenProvider("token"), http, base_url="https://reddit.test")
        with pytest.raises(error):
            await client.me()


@pytest.mark.asyncio
async def test_reddit_rejects_invalid_json_and_mutation_errors() -> None:
    responses = iter(
        [
            httpx.Response(200, text="not-json"),
            httpx.Response(200, json={"json": {"errors": [["BAD", "Rejected"]]}}),
        ]
    )
    transport = httpx.MockTransport(lambda request: next(responses))
    async with httpx.AsyncClient(transport=transport) as http:
        client = RedditClient(StaticTokenProvider("token"), http, base_url="https://reddit.test")
        with pytest.raises(ValidationError, match="invalid JSON"):
            await client.me()
        with pytest.raises(ValidationError, match="Rejected"):
            await client.submit(DraftContent("python", "Title", "Body"))
