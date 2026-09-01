from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import TracebackType

from redditctl.clock import Clock
from redditctl.config import SchedulingConfig
from redditctl.domain import ActionState, ActionType, DraftContent, ScheduledAction
from redditctl.errors import (
    AuthenticationError,
    NetworkError,
    PermissionDeniedError,
    RateLimitedError,
    UncertainOutcomeError,
    ValidationError,
)
from redditctl.persistence import Database
from redditctl.reddit import RedditGateway


class WorkerLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: object | None = None

    def __enter__(self) -> WorkerLock:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise RuntimeError("Another redditctl worker owns this profile") from None
        self.handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.handle is not None:
            handle = self.handle
            assert hasattr(handle, "fileno") and hasattr(handle, "close")
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


@dataclass(frozen=True)
class WorkerResult:
    action_id: str | None
    state: ActionState | None
    message: str


class SchedulerWorker:
    def __init__(
        self,
        database: Database,
        reddit: RedditGateway,
        clock: Clock,
        config: SchedulingConfig,
        *,
        worker_id: str | None = None,
    ) -> None:
        self.database = database
        self.reddit = reddit
        self.clock = clock
        self.config = config
        self.worker_id = worker_id or f"worker-{os.getpid()}"

    async def run_once(self) -> WorkerResult:
        now = self.clock.now()
        recovered = self.database.recover_expired_claim(now)
        if recovered is not None:
            return WorkerResult(
                recovered,
                ActionState.NEEDS_REVIEW,
                "Worker lease expired; verify the remote outcome before retrying",
            )
        action = self.database.claim_due(now, self.worker_id, self.config.lease_seconds)
        if action is None:
            return WorkerResult(None, None, "No due actions")
        preflight = self._preflight(action)
        if preflight:
            self.database.transition_action(
                action.action_id,
                {ActionState.RUNNING},
                ActionState.NEEDS_REVIEW,
                now,
                last_error=preflight,
                lease_until=None,
                worker_id=None,
            )
            return WorkerResult(action.action_id, ActionState.NEEDS_REVIEW, preflight)
        try:
            remote = await self._execute(action)
        except RateLimitedError as exc:
            return self._retry(action, now, exc.message)
        except (NetworkError, UncertainOutcomeError):
            message = "Remote outcome is uncertain; inspect Reddit before retrying"
            self.database.transition_action(
                action.action_id,
                {ActionState.RUNNING},
                ActionState.NEEDS_REVIEW,
                now,
                last_error=message,
                lease_until=None,
                worker_id=None,
            )
            return WorkerResult(action.action_id, ActionState.NEEDS_REVIEW, message)
        except (AuthenticationError, PermissionDeniedError, ValidationError) as exc:
            self.database.transition_action(
                action.action_id,
                {ActionState.RUNNING},
                ActionState.NEEDS_REVIEW,
                now,
                last_error=exc.message,
                lease_until=None,
                worker_id=None,
            )
            return WorkerResult(action.action_id, ActionState.NEEDS_REVIEW, exc.message)
        self.database.transition_action(
            action.action_id,
            {ActionState.RUNNING},
            ActionState.SUCCEEDED,
            now,
            remote_fullname=remote,
            lease_until=None,
            worker_id=None,
            last_error=None,
        )
        return WorkerResult(action.action_id, ActionState.SUCCEEDED, f"Completed as {remote}")

    def _preflight(self, action: ScheduledAction) -> str | None:
        snapshot = self.database.latest_rule_snapshot(action.subreddit)
        if action.rule_hash and (snapshot is None or snapshot.content_hash != action.rule_hash):
            return "Subreddit rules changed after approval"
        if action.action_type in {ActionType.EDIT_SELF_BODY, ActionType.POST_FOLLOWUP_COMMENT}:
            fullname = str(action.payload.get("fullname", ""))
            thing = self.database.get_thing(fullname)
            if thing is None:
                return "The target thread is no longer available locally"
            if action.action_type is ActionType.EDIT_SELF_BODY and not thing.is_self:
                return "The target is not an editable self-post"
        return None

    async def _execute(self, action: ScheduledAction) -> str:
        if action.action_type in {ActionType.SUBMIT_SELF, ActionType.SUBMIT_LINK}:
            draft = DraftContent(
                subreddit=action.subreddit,
                title=str(action.payload.get("title", "")),
                body=str(action.payload.get("body", "")),
                kind="link" if action.action_type is ActionType.SUBMIT_LINK else "self",
                url=action.payload.get("url"),
                flair_id=action.payload.get("flair_id"),
            )
            return await self.reddit.submit(draft)
        if action.action_type is ActionType.EDIT_SELF_BODY:
            return await self.reddit.edit(
                str(action.payload["fullname"]), str(action.payload.get("body", ""))
            )
        return await self.reddit.comment(
            str(action.payload["fullname"]), str(action.payload.get("body", ""))
        )

    def _retry(self, action: ScheduledAction, now: datetime, message: str) -> WorkerResult:
        if action.attempt >= self.config.maximum_attempts:
            state = ActionState.FAILED
            due_at: str | None = None
        else:
            state = ActionState.RETRY_WAIT
            due = now + timedelta(seconds=min(3600, 2**action.attempt * 30))
            due_at = due.isoformat(timespec="microseconds")
        updates: dict[str, object] = {
            "last_error": message,
            "lease_until": None,
            "worker_id": None,
        }
        if due_at:
            updates["due_at"] = due_at
        self.database.transition_action(
            action.action_id, {ActionState.RUNNING}, state, now, **updates
        )
        return WorkerResult(action.action_id, state, message)
