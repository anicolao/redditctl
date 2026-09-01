from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from redditctl.application import AccountService, DiscoveryApplication, DraftingService
from redditctl.config import SchedulingConfig
from redditctl.domain import (
    Account,
    ActionState,
    ActionType,
    DraftContent,
    DraftProposal,
    RecommendationCandidate,
    Rule,
    RuleSnapshot,
    Thing,
    ThingKind,
)
from redditctl.drafting.models import DraftRequest, ReviewRequest, RuleReview
from redditctl.errors import NetworkError, RateLimitedError
from redditctl.persistence import Database
from redditctl.scheduling import SchedulerWorker, WorkerLock


class FakeReddit:
    def __init__(self, now) -> None:
        self.now = now
        self.submitted: list[DraftContent] = []
        self.failure: Exception | None = None

    async def me(self) -> Account:
        return Account("u1", "alice", self.now)

    async def owned_content(self, username: str, *, limit: int = 100) -> list[Thing]:
        assert username == "alice"
        return [Thing("t3_one", ThingKind.SUBMISSION, "python", self.now, score=3)]

    async def subreddit_rules(self, subreddit: str) -> RuleSnapshot:
        return RuleSnapshot.create(
            subreddit,
            f"https://reddit.test/r/{subreddit}/rules",
            self.now,
            [Rule("1", "Relevant", f"Discuss {subreddit}")],
        )

    async def search_communities(self, query: str, *, limit: int = 20):
        return [RecommendationCandidate("python", "Python", query, "", "", 1_000)]

    async def community_samples(self, subreddit: str, *, limit: int = 10) -> list[str]:
        return [f"A recent discussion about {subreddit}"]

    async def submit(self, draft: DraftContent) -> str:
        if self.failure:
            raise self.failure
        self.submitted.append(draft)
        return "t3_new"

    async def edit(self, fullname: str, body: str) -> str:
        return fullname

    async def comment(self, parent_fullname: str, body: str) -> str:
        return "t1_new"


class FakeLlm:
    async def draft(self, request: DraftRequest) -> DraftProposal:
        return DraftProposal(("Generated title",), f"Generated from {request.notes}")

    async def review(self, request: ReviewRequest) -> RuleReview:
        return RuleReview(())


@pytest.mark.asyncio
async def test_application_services_vertical_slice(database: Database, clock, now) -> None:
    reddit = FakeReddit(now)
    total, changed = await AccountService(database, reddit, clock).synchronize()
    snapshot = await AccountService(database, reddit, clock).synchronize_rules("python")
    recommendations = await DiscoveryApplication(database, reddit).discover("python")
    draft_id, draft = await DraftingService(database, FakeLlm(), clock, "fake-model").create(
        DraftRequest("notes", "python", snapshot)
    )
    assert (total, changed) == (1, 1)
    assert recommendations[0].subreddit == "python"
    assert draft.title == "Generated title"
    assert database.current_draft(draft_id) == (draft, snapshot.content_hash)


@pytest.mark.asyncio
async def test_worker_success_and_rule_change_preflight(database: Database, clock, now) -> None:
    reddit = FakeReddit(now)
    original = await reddit.subreddit_rules("python")
    database.store_rule_snapshot(original)
    action_id = database.schedule_action(
        ActionType.SUBMIT_SELF,
        now,
        "python",
        {"title": "Title", "body": "Body"},
        now,
        rule_hash=original.content_hash,
        approved=True,
    )
    result = await SchedulerWorker(database, reddit, clock, SchedulingConfig()).run_once()
    assert result.state is ActionState.SUCCEEDED
    assert database.get_action(action_id).remote_fullname == "t3_new"

    changed = RuleSnapshot.create(
        "python", "url", now + timedelta(minutes=1), [Rule("2", "New", "Changed")]
    )
    database.store_rule_snapshot(changed)
    second = database.schedule_action(
        ActionType.SUBMIT_SELF,
        now,
        "python",
        {"title": "Title", "body": "Body"},
        now,
        rule_hash=original.content_hash,
        approved=True,
    )
    review = await SchedulerWorker(database, reddit, clock, SchedulingConfig()).run_once()
    assert review.state is ActionState.NEEDS_REVIEW
    assert database.get_action(second).last_error == "Subreddit rules changed after approval"


@pytest.mark.asyncio
async def test_worker_rate_limit_retry_and_uncertain_outcome(
    database: Database, clock, now
) -> None:
    reddit = FakeReddit(now)
    action_id = database.schedule_action(
        ActionType.SUBMIT_SELF,
        now,
        "python",
        {"title": "Title", "body": "Body"},
        now,
        approved=True,
    )
    reddit.failure = RateLimitedError("slow down")
    result = await SchedulerWorker(database, reddit, clock, SchedulingConfig()).run_once()
    assert result.state is ActionState.RETRY_WAIT
    assert database.get_action(action_id).due_at > now

    second = database.schedule_action(
        ActionType.SUBMIT_SELF,
        now,
        "python",
        {"title": "Another", "body": "Body"},
        now,
        approved=True,
    )
    reddit.failure = NetworkError("timeout")
    result = await SchedulerWorker(database, reddit, clock, SchedulingConfig()).run_once()
    assert result.state is ActionState.NEEDS_REVIEW
    assert database.get_action(second).state is ActionState.NEEDS_REVIEW


@pytest.mark.asyncio
async def test_worker_reports_idle_and_exhausted_retry(database: Database, clock, now) -> None:
    reddit = FakeReddit(now)
    idle = await SchedulerWorker(database, reddit, clock, SchedulingConfig()).run_once()
    assert idle.action_id is None
    action_id = database.schedule_action(
        ActionType.SUBMIT_SELF,
        now,
        "python",
        {"title": "Title", "body": "Body"},
        now,
        approved=True,
    )
    reddit.failure = RateLimitedError("still limited")
    failed = await SchedulerWorker(
        database, reddit, clock, SchedulingConfig(maximum_attempts=1)
    ).run_once()
    assert failed.state is ActionState.FAILED
    assert database.get_action(action_id).state is ActionState.FAILED


def test_worker_lock_is_exclusive(tmp_path: Path) -> None:
    lock_path = tmp_path / "worker.lock"
    with (
        WorkerLock(lock_path),
        pytest.raises(RuntimeError, match="Another"),
        WorkerLock(lock_path),
    ):
        pass


@pytest.mark.asyncio
async def test_worker_quarantines_expired_claim(database: Database, clock, now) -> None:
    reddit = FakeReddit(now)
    action_id = database.schedule_action(
        ActionType.SUBMIT_SELF,
        now,
        "python",
        {"title": "Title", "body": "Body"},
        now,
        approved=True,
    )
    database.claim_due(now, "crashed-worker", -1)
    result = await SchedulerWorker(database, reddit, clock, SchedulingConfig()).run_once()
    assert result.action_id == action_id
    assert result.state is ActionState.NEEDS_REVIEW
    assert reddit.submitted == []
