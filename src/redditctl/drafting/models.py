from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from redditctl.domain import DraftContent, DraftProposal, Finding, RuleSnapshot


@dataclass(frozen=True)
class DraftRequest:
    notes: str
    subreddit: str
    rules: RuleSnapshot
    tone: str = "clear and conversational"
    kind: str = "self"


@dataclass(frozen=True)
class ReviewRequest:
    draft: DraftContent
    rules: RuleSnapshot


@dataclass(frozen=True)
class RuleReview:
    findings: tuple[Finding, ...]


class LlmGateway(Protocol):
    async def draft(self, request: DraftRequest) -> DraftProposal: ...

    async def review(self, request: ReviewRequest) -> RuleReview: ...
