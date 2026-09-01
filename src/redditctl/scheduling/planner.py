from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from redditctl.config import SchedulingConfig
from redditctl.domain import ActionState, ActionType
from redditctl.errors import PolicyError, UsageError
from redditctl.persistence import Database


def parse_when(value: str, now: datetime, timezone: ZoneInfo) -> datetime:
    relative = re.fullmatch(r"\+(\d+)([hdw])", value.strip().casefold())
    if relative:
        amount = int(relative.group(1))
        units = {"h": "hours", "d": "days", "w": "weeks"}
        return (now + timedelta(**{units[relative.group(2)]: amount})).astimezone(UTC)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise UsageError("Use ISO 8601 with an offset or an unambiguous value such as +2h") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(UTC)


class SchedulePlanner:
    def __init__(self, database: Database, config: SchedulingConfig) -> None:
        self.database = database
        self.config = config

    def plan(
        self,
        action_type: ActionType,
        due_at: datetime,
        subreddit: str,
        payload: dict[str, object],
        now: datetime,
        *,
        rule_hash: str | None = None,
        approved: bool = False,
    ) -> str:
        if due_at <= now:
            raise PolicyError("Scheduled time must be in the future")
        if action_type in {ActionType.EDIT_SELF_BODY, ActionType.POST_FOLLOWUP_COMMENT}:
            if not payload.get("fullname"):
                raise PolicyError("Thread updates require a Reddit fullname")
            thing = self.database.get_thing(str(payload["fullname"]))
            if thing is None:
                raise PolicyError("The target thread has not been synchronized")
            if action_type is ActionType.EDIT_SELF_BODY and not thing.is_self:
                raise PolicyError("Only synchronized self-post bodies can be edited")
        if action_type in {ActionType.SUBMIT_SELF, ActionType.SUBMIT_LINK}:
            self._check_spacing(due_at, subreddit)
        return self.database.schedule_action(
            action_type,
            due_at,
            subreddit,
            payload,
            now,
            rule_hash=rule_hash,
            approved=approved and not self.config.require_approval,
        )

    def _check_spacing(self, due_at: datetime, subreddit: str) -> None:
        for existing in self.database.list_actions(limit=1000):
            if existing.state.terminal or existing.state is ActionState.CANCELLED:
                continue
            gap = abs((existing.due_at - due_at).total_seconds())
            if gap < self.config.minimum_global_gap_seconds:
                raise PolicyError("The action violates the configured global posting gap")
            if (
                existing.subreddit.casefold() == subreddit.casefold()
                and gap < self.config.minimum_subreddit_gap_seconds
            ):
                raise PolicyError("The action violates the configured subreddit posting gap")
