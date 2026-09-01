from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass

from redditctl.domain import Recommendation, RecommendationCandidate


@dataclass(frozen=True)
class DiscoveryPreferences:
    exclude_nsfw: bool = True
    excluded_subreddits: frozenset[str] = frozenset()
    minimum_subscribers: int | None = None


class DiscoveryService:
    """Explainable lexical ranking backed by SQLite FTS5/BM25."""

    def rank(
        self,
        query: str,
        candidates: list[RecommendationCandidate],
        preferences: DiscoveryPreferences | None = None,
    ) -> list[Recommendation]:
        preferences = preferences or DiscoveryPreferences()
        query_tokens = self._tokens(query)
        if not query_tokens:
            return []
        included: list[RecommendationCandidate] = []
        results: list[Recommendation] = []
        excluded = {name.casefold() for name in preferences.excluded_subreddits}
        for candidate in candidates:
            reason: str | None = None
            if candidate.name.casefold() in excluded:
                reason = "excluded by user preference"
            elif preferences.exclude_nsfw and candidate.nsfw:
                reason = "NSFW communities are excluded"
            elif not candidate.active:
                reason = "community is not currently active"
            elif (
                preferences.minimum_subscribers is not None
                and candidate.subscribers is not None
                and candidate.subscribers < preferences.minimum_subscribers
            ):
                reason = "community is below the configured size"
            if reason:
                results.append(Recommendation(candidate.name, float("-inf"), reason, {}, reason))
            else:
                included.append(candidate)

        if included:
            connection = sqlite3.connect(":memory:")
            try:
                connection.execute(
                    "CREATE VIRTUAL TABLE candidates USING "
                    "fts5(name, title, description, rules, samples)"
                )
                connection.executemany(
                    "INSERT INTO candidates(rowid, name, title, description, rules, samples) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (
                            index,
                            candidate.name,
                            candidate.title,
                            candidate.description,
                            candidate.rules_text,
                            candidate.sample_text,
                        )
                        for index, candidate in enumerate(included, start=1)
                    ],
                )
                fts_query = " OR ".join(f'"{token}"' for token in sorted(query_tokens))
                rows = connection.execute(
                    "SELECT rowid, bm25(candidates, 3.0, 2.0, 1.5, 0.5, 1.0) AS rank "
                    "FROM candidates WHERE candidates MATCH ? ORDER BY rank",
                    (fts_query,),
                ).fetchall()
                lexical = {rowid: -float(rank) for rowid, rank in rows}
            finally:
                connection.close()
            for index, candidate in enumerate(included, start=1):
                lexical_score = lexical.get(index, 0.0)
                name_title_tokens = self._tokens(f"{candidate.name} {candidate.title}")
                all_tokens = self._tokens(
                    " ".join(
                        (
                            candidate.name,
                            candidate.title,
                            candidate.description,
                            candidate.rules_text,
                            candidate.sample_text,
                        )
                    )
                )
                exact = float(bool(query_tokens & name_title_tokens))
                topic_overlap = len(query_tokens & all_tokens) / len(query_tokens)
                activity = 1.0 if candidate.active else 0.0
                size_signal = math.log10(max(candidate.subscribers or 1, 1)) / 10
                promotion_warning = float(
                    "self-promotion" in candidate.rules_text.casefold()
                    or "self promotion" in candidate.rules_text.casefold()
                )
                score = (
                    lexical_score
                    + topic_overlap * 2
                    + exact * 0.75
                    + activity * 0.2
                    + size_signal * 0.2
                )
                features = {
                    "lexical_fit": round(lexical_score, 6),
                    "topic_overlap": round(topic_overlap, 6),
                    "title_or_name_match": exact,
                    "recently_active": activity,
                    "size_signal": round(size_signal, 6),
                    "promotion_rule_present": promotion_warning,
                }
                rationale = (
                    f"Lexical topic fit {features['lexical_fit']:.2f}; "
                    f"name/title match {'yes' if exact else 'no'}; "
                    f"self-promotion rule {'present' if promotion_warning else 'not observed'}."
                )
                results.append(Recommendation(candidate.name, score, rationale, features))
        return sorted(
            results,
            key=lambda result: (
                result.excluded_reason is not None,
                -result.score,
                result.subreddit,
            ),
        )

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {token for token in re.findall(r"[\w-]{2,}", text.casefold())}
