from __future__ import annotations

from datetime import timedelta

from redditctl.domain import (
    Account,
    ActionState,
    ActionType,
    DraftContent,
    Rule,
    RuleSnapshot,
    Thing,
    ThingKind,
)
from redditctl.persistence import Database


def test_migrations_are_idempotent(database: Database) -> None:
    database.migrate()
    with database.connect() as connection:
        versions = connection.execute("SELECT version FROM schema_migrations").fetchall()
    assert [row["version"] for row in versions] == ["0001_initial.sql"]


def test_account_things_and_metrics(database: Database, now) -> None:
    database.upsert_account(Account("u1", "alice", now))
    thing = Thing(
        "t3_one",
        ThingKind.SUBMISSION,
        "python",
        now,
        title="One",
        score=10,
        reply_count=2,
        is_self=True,
    )
    assert database.upsert_thing(thing, now)
    assert not database.upsert_thing(thing, now + timedelta(minutes=1))
    changed = Thing(**{**thing.__dict__, "score": 12})
    assert database.upsert_thing(changed, now + timedelta(minutes=2))
    assert database.get_thing("t3_one").score == 12
    assert len(database.metric_history("t3_one")) == 2
    assert database.list_things(sort="score")[0].fullname == "t3_one"


def test_rules_drafts_schedule_and_audit(database: Database, now) -> None:
    snapshot = RuleSnapshot.create(
        "python", "https://reddit.test/rules", now, [Rule("1", "Relevant", "Stay relevant")]
    )
    assert database.store_rule_snapshot(snapshot)
    assert not database.store_rule_snapshot(snapshot)
    assert database.latest_rule_snapshot("python") == snapshot

    content = DraftContent("python", "A title", "A body")
    draft_id = database.create_draft(content, now, rule_hash=snapshot.content_hash)
    assert database.current_draft(draft_id) == (content, snapshot.content_hash)
    revised = DraftContent("python", "A better title", "A body")
    assert database.add_draft_revision(draft_id, revised, now, author_kind="user") == 2
    assert database.current_draft(draft_id)[0] == revised

    action_id = database.schedule_action(
        ActionType.SUBMIT_SELF,
        now + timedelta(hours=1),
        "python",
        {"title": revised.title, "body": revised.body},
        now,
        rule_hash=snapshot.content_hash,
    )
    assert database.approve_action(action_id, now)
    claimed = database.claim_due(now + timedelta(hours=2), "worker", 30)
    assert claimed.action_id == action_id
    assert claimed.state is ActionState.RUNNING
    assert claimed.attempt == 1
    assert len(database.audit_events(action_id)) == 3


def test_link_snapshots_replace_same_bucket(database: Database, now) -> None:
    database.upsert_link_mapping("launch", "https://example.com", now)
    database.upsert_link_snapshot("launch", now, "reddit", False, 2)
    database.upsert_link_snapshot("launch", now, "reddit", False, 7)
    database.upsert_link_snapshot("launch", now, "direct", True, 3)
    assert database.link_totals("launch") == {"reddit:human": 7, "direct:bot": 3}
