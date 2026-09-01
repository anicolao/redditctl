from __future__ import annotations

from redditctl.discovery import DiscoveryPreferences, DiscoveryService
from redditctl.domain import RecommendationCandidate


def candidate(name: str, description: str, **kwargs: object) -> RecommendationCandidate:
    return RecommendationCandidate(
        name=name,
        title=name,
        description=description,
        rules_text=str(kwargs.pop("rules_text", "")),
        sample_text="",
        **kwargs,
    )


def test_discovery_ranks_topic_match_and_explains_features() -> None:
    results = DiscoveryService().rank(
        "self hosted photos",
        [
            candidate("selfhosted", "Self hosted services and photos", subscribers=100_000),
            candidate("gardening", "Plants and gardens", subscribers=5_000_000),
        ],
    )
    assert results[0].subreddit == "selfhosted"
    assert "lexical_fit" in results[0].features
    assert "name/title match" in results[0].rationale


def test_discovery_reports_exclusions_after_included_results() -> None:
    results = DiscoveryService().rank(
        "python",
        [
            candidate("python", "language"),
            candidate("nsfwpython", "language", nsfw=True),
            candidate("blocked", "language"),
            candidate("tiny", "language", subscribers=2),
        ],
        DiscoveryPreferences(excluded_subreddits=frozenset({"blocked"}), minimum_subscribers=10),
    )
    assert results[0].subreddit == "python"
    excluded = {item.subreddit: item.excluded_reason for item in results[1:]}
    assert excluded["nsfwpython"] == "NSFW communities are excluded"
    assert excluded["blocked"] == "excluded by user preference"
    assert excluded["tiny"] == "community is below the configured size"


def test_discovery_rejects_empty_query() -> None:
    assert DiscoveryService().rank("!", [candidate("python", "language")]) == []
