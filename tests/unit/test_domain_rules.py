from __future__ import annotations

from datetime import UTC, datetime

from redditctl.domain import (
    ActionState,
    DraftContent,
    FindingSeverity,
    Rule,
    RuleSnapshot,
    canonical_hash,
)
from redditctl.rules import RuleEngine, RulePolicy


def test_rule_snapshot_hash_is_stable() -> None:
    rules = [Rule("1", "Stay relevant", "Posts must be on topic")]
    first = RuleSnapshot.create("python", "https://example/rules", datetime.now(UTC), rules)
    second = RuleSnapshot.create("python", "different", datetime.now(UTC), rules)
    assert first.content_hash == second.content_hash
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})


def test_action_terminal_states() -> None:
    assert ActionState.SUCCEEDED.terminal
    assert ActionState.FAILED.terminal
    assert ActionState.CANCELLED.terminal
    assert not ActionState.APPROVED.terminal


def test_rule_engine_finds_deterministic_errors() -> None:
    draft = DraftContent("python", "x" * 11, "I built my project with spam", kind="link")
    policy = RulePolicy(
        required_terms=("source",),
        banned_terms=("spam",),
        require_flair=True,
        maximum_title_length=10,
        require_affiliation_disclosure=True,
    )
    findings = RuleEngine().check(draft, None, policy)
    codes = {finding.code for finding in findings}
    assert {
        "title_too_long",
        "missing_url",
        "missing_flair",
        "missing_required_term",
        "banned_term",
        "rules_unavailable",
    } <= codes
    assert RuleEngine.has_errors(findings)


def test_rule_engine_checks_domains_and_ambiguous_rules(now: datetime) -> None:
    snapshot = RuleSnapshot.create(
        "python",
        "https://reddit.com/r/python/about/rules",
        now,
        [Rule("promo", "Self-promotion and flair", "Self promotion requires flair")],
    )
    draft = DraftContent(
        "python", "A title", "No relationship stated", kind="link", url="https://x.bad.test/a"
    )
    findings = RuleEngine().check(draft, snapshot, RulePolicy(banned_domains=("bad.test",)))
    assert {finding.code for finding in findings} == {
        "banned_domain",
        "promotion_review",
        "flair_review",
    }
    assert any(finding.severity is FindingSeverity.WARNING for finding in findings)
