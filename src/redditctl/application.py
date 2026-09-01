from __future__ import annotations

from dataclasses import replace

from redditctl.clock import Clock
from redditctl.discovery import DiscoveryPreferences, DiscoveryService
from redditctl.domain import DraftContent, Recommendation, RecommendationCandidate, RuleSnapshot
from redditctl.drafting.models import DraftRequest, LlmGateway
from redditctl.persistence import Database
from redditctl.reddit import RedditGateway


class AccountService:
    def __init__(self, database: Database, reddit: RedditGateway, clock: Clock) -> None:
        self.database = database
        self.reddit = reddit
        self.clock = clock

    async def synchronize(self, *, limit: int = 100) -> tuple[int, int]:
        account = await self.reddit.me()
        self.database.upsert_account(account)
        things = await self.reddit.owned_content(account.username, limit=limit)
        changed = sum(self.database.upsert_thing(thing, self.clock.now()) for thing in things)
        return len(things), changed

    async def synchronize_rules(self, subreddit: str) -> RuleSnapshot:
        snapshot = await self.reddit.subreddit_rules(subreddit)
        self.database.store_rule_snapshot(snapshot)
        return snapshot


class DiscoveryApplication:
    def __init__(self, database: Database, reddit: RedditGateway) -> None:
        self.database = database
        self.reddit = reddit
        self.ranker = DiscoveryService()

    async def discover(
        self,
        query: str,
        *,
        limit: int = 20,
        preferences: DiscoveryPreferences | None = None,
    ) -> list[Recommendation]:
        candidates = await self.reddit.search_communities(query, limit=limit)
        enriched: list[RecommendationCandidate] = []
        for candidate in candidates:
            snapshot = self.database.latest_rule_snapshot(candidate.name)
            if snapshot is None:
                snapshot = await self.reddit.subreddit_rules(candidate.name)
                self.database.store_rule_snapshot(snapshot)
            rules_text = "\n".join(f"{rule.short_name} {rule.body}" for rule in snapshot.rules)
            samples = await self.reddit.community_samples(candidate.name, limit=10)
            enriched.append(
                replace(candidate, rules_text=rules_text, sample_text="\n\n".join(samples))
            )
        return self.ranker.rank(query, enriched, preferences)


class DraftingService:
    def __init__(self, database: Database, llm: LlmGateway, clock: Clock, model: str) -> None:
        self.database = database
        self.llm = llm
        self.clock = clock
        self.model = model

    async def create(self, request: DraftRequest) -> tuple[str, DraftContent]:
        proposal = await self.llm.draft(request)
        content = DraftContent(
            subreddit=request.subreddit,
            title=proposal.titles[0],
            body=proposal.body,
            kind=request.kind,
        )
        draft_id = self.database.create_draft(
            content,
            self.clock.now(),
            author_kind="model",
            provider="gemini",
            model=self.model,
            rule_hash=request.rules.content_hash,
        )
        return draft_id, content
