from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class ThingKind(StrEnum):
    SUBMISSION = "submission"
    COMMENT = "comment"


class ActionType(StrEnum):
    SUBMIT_SELF = "submit_self"
    SUBMIT_LINK = "submit_link"
    EDIT_SELF_BODY = "edit_self_body"
    POST_FOLLOWUP_COMMENT = "post_followup_comment"


class ActionState(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    NEEDS_REVIEW = "needs_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.FAILED, self.CANCELLED}


class FindingSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Account:
    reddit_id: str
    username: str
    created_at: datetime


@dataclass(frozen=True)
class Thing:
    fullname: str
    kind: ThingKind
    subreddit: str
    created_at: datetime
    title: str = ""
    body: str = ""
    url: str | None = None
    permalink: str | None = None
    score: int | None = None
    reply_count: int | None = None
    is_self: bool = False


@dataclass(frozen=True)
class MetricSnapshot:
    thing_fullname: str
    observed_at: datetime
    score: int | None
    reply_count: int | None


@dataclass(frozen=True)
class Rule:
    rule_id: str
    short_name: str
    body: str
    applies_to: str | None = None


@dataclass(frozen=True)
class RuleSnapshot:
    subreddit: str
    source_url: str
    retrieved_at: datetime
    content_hash: str
    rules: tuple[Rule, ...]

    @classmethod
    def create(
        cls,
        subreddit: str,
        source_url: str,
        retrieved_at: datetime,
        rules: list[Rule],
    ) -> RuleSnapshot:
        canonical = json.dumps([asdict(rule) for rule in rules], sort_keys=True)
        return cls(
            subreddit=subreddit,
            source_url=source_url,
            retrieved_at=retrieved_at,
            content_hash=hashlib.sha256(canonical.encode()).hexdigest(),
            rules=tuple(rules),
        )


@dataclass(frozen=True)
class DraftContent:
    subreddit: str
    title: str
    body: str
    kind: str = "self"
    url: str | None = None
    flair_id: str | None = None

    @property
    def content_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class DraftProposal:
    titles: tuple[str, ...]
    body: str
    suggested_flair: str | None = None
    disclosures: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    rule_references: tuple[str, ...] = ()


@dataclass(frozen=True)
class Finding:
    severity: FindingSeverity
    code: str
    message: str
    rule_id: str | None = None


@dataclass(frozen=True)
class RecommendationCandidate:
    name: str
    title: str
    description: str
    rules_text: str
    sample_text: str
    subscribers: int | None = None
    active: bool = True
    nsfw: bool = False


@dataclass(frozen=True)
class Recommendation:
    subreddit: str
    score: float
    rationale: str
    features: dict[str, float]
    excluded_reason: str | None = None


@dataclass(frozen=True)
class ScheduledAction:
    action_id: str
    action_type: ActionType
    state: ActionState
    due_at: datetime
    subreddit: str
    payload: dict[str, Any]
    payload_hash: str
    rule_hash: str | None = None
    approved_at: datetime | None = None
    attempt: int = 0
    lease_until: datetime | None = None
    worker_id: str | None = None
    last_error: str | None = None
    remote_fullname: str | None = None


def canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()
