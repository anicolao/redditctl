from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from redditctl.domain import DraftContent, Finding, FindingSeverity, RuleSnapshot


@dataclass(frozen=True)
class RulePolicy:
    required_terms: tuple[str, ...] = ()
    banned_terms: tuple[str, ...] = ()
    banned_domains: tuple[str, ...] = ()
    require_flair: bool = False
    require_affiliation_disclosure: bool = False
    maximum_title_length: int = 300


class RuleEngine:
    def check(
        self,
        draft: DraftContent,
        snapshot: RuleSnapshot | None,
        policy: RulePolicy | None = None,
    ) -> list[Finding]:
        policy = policy or RulePolicy()
        findings: list[Finding] = []
        combined = f"{draft.title}\n{draft.body}".casefold()
        if not draft.title.strip():
            findings.append(
                Finding(FindingSeverity.ERROR, "empty_title", "A post title is required.")
            )
        if len(draft.title) > policy.maximum_title_length:
            findings.append(
                Finding(
                    FindingSeverity.ERROR,
                    "title_too_long",
                    f"Title exceeds {policy.maximum_title_length} characters.",
                )
            )
        if draft.kind == "link" and not draft.url:
            findings.append(
                Finding(FindingSeverity.ERROR, "missing_url", "A link post requires a URL.")
            )
        if policy.require_flair and not draft.flair_id:
            findings.append(
                Finding(FindingSeverity.ERROR, "missing_flair", "This community requires flair.")
            )
        for term in policy.required_terms:
            if term.casefold() not in combined:
                findings.append(
                    Finding(
                        FindingSeverity.ERROR,
                        "missing_required_term",
                        f"Required text is missing: {term}",
                    )
                )
        for term in policy.banned_terms:
            if term.casefold() in combined:
                findings.append(
                    Finding(
                        FindingSeverity.ERROR,
                        "banned_term",
                        f"Disallowed text appears in the draft: {term}",
                    )
                )
        if draft.url:
            hostname = (urlparse(draft.url).hostname or "").casefold()
            for domain in policy.banned_domains:
                normalized = domain.casefold()
                if hostname == normalized or hostname.endswith(f".{normalized}"):
                    findings.append(
                        Finding(
                            FindingSeverity.ERROR,
                            "banned_domain",
                            f"Links to {domain} are not permitted by the configured policy.",
                        )
                    )
        if policy.require_affiliation_disclosure and not re.search(
            r"\b(i (?:am|work|made|built)|my (?:project|company)|affiliat)", combined
        ):
            findings.append(
                Finding(
                    FindingSeverity.WARNING,
                    "missing_disclosure",
                    "Add a clear affiliation disclosure.",
                )
            )
        if snapshot is None:
            findings.append(
                Finding(
                    FindingSeverity.UNKNOWN,
                    "rules_unavailable",
                    "No synchronized rule snapshot is available.",
                )
            )
        else:
            for rule in snapshot.rules:
                text = f"{rule.short_name} {rule.body}".casefold()
                if "self-promotion" in text or "self promotion" in text:
                    findings.append(
                        Finding(
                            FindingSeverity.WARNING,
                            "promotion_review",
                            "Review the community's self-promotion rule before publishing.",
                            rule.rule_id,
                        )
                    )
                if "flair" in text and not draft.flair_id:
                    findings.append(
                        Finding(
                            FindingSeverity.UNKNOWN,
                            "flair_review",
                            "A rule mentions flair; confirm whether one is required.",
                            rule.rule_id,
                        )
                    )
        return findings

    @staticmethod
    def has_errors(findings: list[Finding]) -> bool:
        return any(finding.severity is FindingSeverity.ERROR for finding in findings)
