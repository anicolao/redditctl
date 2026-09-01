from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any
from uuid import uuid4

from redditctl.domain import (
    Account,
    ActionState,
    ActionType,
    DraftContent,
    MetricSnapshot,
    Rule,
    RuleSnapshot,
    ScheduledAction,
    Thing,
    ThingKind,
    canonical_hash,
)
from redditctl.errors import StorageError


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise StorageError(str(exc)) from exc
        finally:
            connection.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def migrate(self) -> None:
        with self.transaction(immediate=True) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            migration_dir = files("redditctl.persistence.migrations")
            for resource in sorted(migration_dir.iterdir(), key=lambda item: item.name):
                if not resource.name.endswith(".sql"):
                    continue
                sql = resource.read_text(encoding="utf-8")
                checksum = canonical_hash(sql)
                row = connection.execute(
                    "SELECT checksum FROM schema_migrations WHERE version = ?", (resource.name,)
                ).fetchone()
                if row:
                    if row["checksum"] != checksum:
                        raise StorageError(f"Migration checksum changed: {resource.name}")
                    continue
                statement = ""
                for line in sql.splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        connection.execute(statement)
                        statement = ""
                if statement.strip():
                    raise StorageError(f"Incomplete SQL in migration: {resource.name}")
                connection.execute(
                    "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (?, ?, ?)",
                    (resource.name, checksum, _utc(datetime.now(UTC))),
                )

    def upsert_account(self, account: Account) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO accounts(reddit_id, username, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(reddit_id) DO UPDATE SET username = excluded.username",
                (account.reddit_id, account.username, _utc(account.created_at)),
            )

    def upsert_thing(self, thing: Thing, observed_at: datetime) -> bool:
        with self.transaction() as connection:
            previous = connection.execute(
                "SELECT score, reply_count FROM things WHERE fullname = ?", (thing.fullname,)
            ).fetchone()
            connection.execute(
                """
                INSERT INTO things(
                    fullname, kind, subreddit, created_at, title, body, url, permalink,
                    score, reply_count, is_self, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fullname) DO UPDATE SET
                    subreddit = excluded.subreddit, title = excluded.title, body = excluded.body,
                    url = excluded.url, permalink = excluded.permalink, score = excluded.score,
                    reply_count = excluded.reply_count, is_self = excluded.is_self,
                    updated_at = excluded.updated_at
                """,
                (
                    thing.fullname,
                    thing.kind.value,
                    thing.subreddit,
                    _utc(thing.created_at),
                    thing.title,
                    thing.body,
                    thing.url,
                    thing.permalink,
                    thing.score,
                    thing.reply_count,
                    int(thing.is_self),
                    _utc(observed_at),
                ),
            )
            changed = (
                previous is None
                or previous["score"] != thing.score
                or previous["reply_count"] != thing.reply_count
            )
            if changed:
                connection.execute(
                    "INSERT OR IGNORE INTO metric_snapshots"
                    "(thing_fullname, observed_at, score, reply_count) VALUES (?, ?, ?, ?)",
                    (thing.fullname, _utc(observed_at), thing.score, thing.reply_count),
                )
            return changed

    def list_things(
        self, *, limit: int = 100, subreddit: str | None = None, sort: str = "created_at"
    ) -> list[Thing]:
        sort_columns = {
            "created_at": "created_at",
            "score": "COALESCE(score, -1)",
            "replies": "COALESCE(reply_count, -1)",
        }
        if sort not in sort_columns:
            raise ValueError(f"Unsupported sort: {sort}")
        where = "WHERE subreddit = ?" if subreddit else ""
        params: tuple[object, ...] = (subreddit, limit) if subreddit else (limit,)
        with self.read() as connection:
            rows = connection.execute(
                f"SELECT * FROM things {where} ORDER BY {sort_columns[sort]} DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._thing_from_row(row) for row in rows]

    def get_thing(self, fullname: str) -> Thing | None:
        with self.read() as connection:
            row = connection.execute(
                "SELECT * FROM things WHERE fullname = ?", (fullname,)
            ).fetchone()
        return self._thing_from_row(row) if row else None

    @staticmethod
    def _thing_from_row(row: sqlite3.Row) -> Thing:
        return Thing(
            fullname=row["fullname"],
            kind=ThingKind(row["kind"]),
            subreddit=row["subreddit"],
            created_at=datetime.fromisoformat(row["created_at"]),
            title=row["title"],
            body=row["body"],
            url=row["url"],
            permalink=row["permalink"],
            score=row["score"],
            reply_count=row["reply_count"],
            is_self=bool(row["is_self"]),
        )

    def metric_history(self, fullname: str) -> list[MetricSnapshot]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM metric_snapshots WHERE thing_fullname = ? ORDER BY observed_at",
                (fullname,),
            ).fetchall()
        return [
            MetricSnapshot(
                thing_fullname=row["thing_fullname"],
                observed_at=datetime.fromisoformat(row["observed_at"]),
                score=row["score"],
                reply_count=row["reply_count"],
            )
            for row in rows
        ]

    def store_rule_snapshot(self, snapshot: RuleSnapshot) -> bool:
        rules_json = json.dumps([asdict(rule) for rule in snapshot.rules], sort_keys=True)
        with self.transaction() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO rule_snapshots"
                "(subreddit, source_url, retrieved_at, content_hash, rules_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    snapshot.subreddit,
                    snapshot.source_url,
                    _utc(snapshot.retrieved_at),
                    snapshot.content_hash,
                    rules_json,
                ),
            )
            return cursor.rowcount == 1

    def latest_rule_snapshot(self, subreddit: str) -> RuleSnapshot | None:
        with self.read() as connection:
            row = connection.execute(
                "SELECT * FROM rule_snapshots WHERE subreddit = ? "
                "ORDER BY retrieved_at DESC LIMIT 1",
                (subreddit,),
            ).fetchone()
        if not row:
            return None
        rules = tuple(Rule(**item) for item in json.loads(row["rules_json"]))
        return RuleSnapshot(
            subreddit=row["subreddit"],
            source_url=row["source_url"],
            retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
            content_hash=row["content_hash"],
            rules=rules,
        )

    def create_draft(
        self,
        content: DraftContent,
        created_at: datetime,
        *,
        author_kind: str = "user",
        provider: str | None = None,
        model: str | None = None,
        rule_hash: str | None = None,
    ) -> str:
        draft_id = f"draft-{uuid4().hex[:8]}"
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO drafts(id, subreddit, created_at, current_revision) "
                "VALUES (?, ?, ?, 1)",
                (draft_id, content.subreddit, _utc(created_at)),
            )
            self._insert_revision(
                connection,
                draft_id,
                1,
                content,
                created_at,
                author_kind,
                provider,
                model,
                rule_hash,
            )
        return draft_id

    def add_draft_revision(
        self,
        draft_id: str,
        content: DraftContent,
        created_at: datetime,
        *,
        author_kind: str,
        provider: str | None = None,
        model: str | None = None,
        rule_hash: str | None = None,
    ) -> int:
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(revision_number), 0) AS revision FROM draft_revisions "
                "WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
            revision = int(row["revision"]) + 1
            self._insert_revision(
                connection,
                draft_id,
                revision,
                content,
                created_at,
                author_kind,
                provider,
                model,
                rule_hash,
            )
            connection.execute(
                "UPDATE drafts SET current_revision = ? WHERE id = ?", (revision, draft_id)
            )
            return revision

    @staticmethod
    def _insert_revision(
        connection: sqlite3.Connection,
        draft_id: str,
        revision: int,
        content: DraftContent,
        created_at: datetime,
        author_kind: str,
        provider: str | None = None,
        model: str | None = None,
        rule_hash: str | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO draft_revisions(
                draft_id, revision_number, created_at, content_json, content_hash,
                author_kind, provider, model, rule_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft_id,
                revision,
                _utc(created_at),
                json.dumps(asdict(content), sort_keys=True),
                content.content_hash,
                author_kind,
                provider,
                model,
                rule_hash,
            ),
        )

    def current_draft(self, draft_id: str) -> tuple[DraftContent, str | None] | None:
        with self.read() as connection:
            row = connection.execute(
                """
                SELECT r.content_json, r.rule_hash FROM drafts d
                JOIN draft_revisions r
                  ON r.draft_id = d.id AND r.revision_number = d.current_revision
                WHERE d.id = ?
                """,
                (draft_id,),
            ).fetchone()
        if not row:
            return None
        return DraftContent(**json.loads(row["content_json"])), row["rule_hash"]

    def schedule_action(
        self,
        action_type: ActionType,
        due_at: datetime,
        subreddit: str,
        payload: dict[str, Any],
        now: datetime,
        *,
        rule_hash: str | None = None,
        approved: bool = False,
    ) -> str:
        action_id = f"action-{uuid4().hex[:10]}"
        state = ActionState.APPROVED if approved else ActionState.PENDING_APPROVAL
        payload_hash = canonical_hash(payload)
        approved_at = _utc(now) if approved else None
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO scheduled_actions(
                    id, action_type, state, due_at, subreddit, payload_json, payload_hash,
                    rule_hash, approved_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    action_type.value,
                    state.value,
                    _utc(due_at),
                    subreddit,
                    json.dumps(payload, sort_keys=True),
                    payload_hash,
                    rule_hash,
                    approved_at,
                    _utc(now),
                    _utc(now),
                ),
            )
            self._audit(connection, now, action_id, "scheduled", {"state": state.value})
        return action_id

    def approve_action(self, action_id: str, now: datetime) -> bool:
        return self.transition_action(
            action_id,
            {ActionState.PENDING_APPROVAL, ActionState.NEEDS_REVIEW},
            ActionState.APPROVED,
            now,
            approved_at=_utc(now),
            last_error=None,
        )

    def transition_action(
        self,
        action_id: str,
        expected: set[ActionState],
        target: ActionState,
        now: datetime,
        **updates: object,
    ) -> bool:
        allowed_columns = {
            "approved_at",
            "lease_until",
            "worker_id",
            "last_error",
            "remote_fullname",
            "due_at",
        }
        if set(updates) - allowed_columns:
            raise ValueError("Unsupported action update")
        assignments = ["state = ?", "updated_at = ?"]
        values: list[object] = [target.value, _utc(now)]
        for column, value in updates.items():
            assignments.append(f"{column} = ?")
            values.append(value)
        placeholders = ",".join("?" for _ in expected)
        values.extend([action_id, *(state.value for state in expected)])
        with self.transaction(immediate=True) as connection:
            cursor = connection.execute(
                f"UPDATE scheduled_actions SET {', '.join(assignments)} "
                f"WHERE id = ? AND state IN ({placeholders})",
                values,
            )
            if cursor.rowcount:
                self._audit(connection, now, action_id, "transition", {"state": target.value})
            return cursor.rowcount == 1

    def claim_due(
        self, now: datetime, worker_id: str, lease_seconds: int
    ) -> ScheduledAction | None:
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                """
                SELECT * FROM scheduled_actions
                WHERE state IN ('approved', 'retry_wait')
                  AND due_at <= ?
                  AND (lease_until IS NULL OR lease_until < ?)
                ORDER BY due_at, created_at LIMIT 1
                """,
                (_utc(now), _utc(now)),
            ).fetchone()
            if not row:
                return None
            lease_until = now + timedelta(seconds=lease_seconds)
            cursor = connection.execute(
                """
                UPDATE scheduled_actions
                SET state = 'running', worker_id = ?, lease_until = ?,
                    attempt = attempt + 1, updated_at = ?
                WHERE id = ? AND state IN ('approved', 'retry_wait')
                """,
                (worker_id, _utc(lease_until), _utc(now), row["id"]),
            )
            if cursor.rowcount != 1:
                return None
            self._audit(connection, now, row["id"], "claimed", {"worker_id": worker_id})
            claimed = connection.execute(
                "SELECT * FROM scheduled_actions WHERE id = ?", (row["id"],)
            ).fetchone()
        return self._action_from_row(claimed)

    def recover_expired_claim(self, now: datetime) -> str | None:
        """Quarantine one abandoned mutation rather than risk executing it twice."""
        message = "Worker lease expired; verify the remote outcome before retrying"
        with self.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT id FROM scheduled_actions WHERE state = 'running' "
                "AND lease_until < ? ORDER BY lease_until LIMIT 1",
                (_utc(now),),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE scheduled_actions SET state = 'needs_review', last_error = ?, "
                "lease_until = NULL, worker_id = NULL, updated_at = ? WHERE id = ?",
                (message, _utc(now), row["id"]),
            )
            self._audit(
                connection,
                now,
                row["id"],
                "lease_expired",
                {"state": ActionState.NEEDS_REVIEW.value},
            )
            return str(row["id"])

    def get_action(self, action_id: str) -> ScheduledAction | None:
        with self.read() as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_actions WHERE id = ?", (action_id,)
            ).fetchone()
        return self._action_from_row(row) if row else None

    def list_actions(self, *, limit: int = 100) -> list[ScheduledAction]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM scheduled_actions ORDER BY due_at LIMIT ?", (limit,)
            ).fetchall()
        return [self._action_from_row(row) for row in rows]

    @staticmethod
    def _action_from_row(row: sqlite3.Row) -> ScheduledAction:
        return ScheduledAction(
            action_id=row["id"],
            action_type=ActionType(row["action_type"]),
            state=ActionState(row["state"]),
            due_at=datetime.fromisoformat(row["due_at"]),
            subreddit=row["subreddit"],
            payload=json.loads(row["payload_json"]),
            payload_hash=row["payload_hash"],
            rule_hash=row["rule_hash"],
            approved_at=_dt(row["approved_at"]),
            attempt=row["attempt"],
            lease_until=_dt(row["lease_until"]),
            worker_id=row["worker_id"],
            last_error=row["last_error"],
            remote_fullname=row["remote_fullname"],
        )

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        now: datetime,
        action_id: str | None,
        event_type: str,
        detail: dict[str, object],
    ) -> None:
        connection.execute(
            "INSERT INTO audit_events(occurred_at, action_id, event_type, detail_json) "
            "VALUES (?, ?, ?, ?)",
            (_utc(now), action_id, event_type, json.dumps(detail, sort_keys=True)),
        )

    def audit_events(self, action_id: str | None = None) -> list[dict[str, object]]:
        with self.read() as connection:
            if action_id:
                rows = connection.execute(
                    "SELECT * FROM audit_events WHERE action_id = ? ORDER BY id", (action_id,)
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM audit_events ORDER BY id").fetchall()
        return [
            {
                "occurred_at": row["occurred_at"],
                "action_id": row["action_id"],
                "event_type": row["event_type"],
                "detail": json.loads(row["detail_json"]),
            }
            for row in rows
        ]

    def upsert_link_mapping(
        self, slug: str, destination: str, created_at: datetime, *, active: bool = True
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO link_mappings(slug, destination, active, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    destination = excluded.destination, active = excluded.active
                """,
                (slug, destination, int(active), _utc(created_at)),
            )

    def upsert_link_snapshot(
        self,
        slug: str,
        bucket_at: datetime,
        referrer_class: str,
        bot: bool,
        count: int,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO link_snapshots(slug, bucket_at, referrer_class, bot, count)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(slug, bucket_at, referrer_class, bot)
                DO UPDATE SET count = excluded.count
                """,
                (slug, _utc(bucket_at), referrer_class, int(bot), count),
            )

    def link_totals(self, slug: str) -> dict[str, int]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT referrer_class, bot, SUM(count) AS total FROM link_snapshots "
                "WHERE slug = ? GROUP BY referrer_class, bot",
                (slug,),
            ).fetchall()
        return {
            f"{row['referrer_class']}:{'bot' if row['bot'] else 'human'}": int(row["total"])
            for row in rows
        }
