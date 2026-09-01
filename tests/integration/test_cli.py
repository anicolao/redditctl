from __future__ import annotations

import json

from typer.testing import CliRunner

from redditctl.cli import app
from redditctl.config import AppConfig
from redditctl.domain import DraftContent, Rule, RuleSnapshot, Thing, ThingKind
from redditctl.persistence import Database


def test_cli_init_and_empty_lists(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("REDDITCTL_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("REDDITCTL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REDDITCTL_CACHE_DIR", str(tmp_path / "cache"))
    runner = CliRunner()
    initialized = runner.invoke(app, ["init"])
    assert initialized.exit_code == 0
    assert (tmp_path / "config" / "config.toml").exists()
    listed = runner.invoke(app, ["schedule", "list"])
    assert listed.exit_code == 0
    assert json.loads(listed.stdout) == []


def test_cli_lists_and_shows_local_posts(tmp_path, monkeypatch, now) -> None:
    monkeypatch.setenv("REDDITCTL_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("REDDITCTL_DATA_DIR", str(tmp_path / "data"))
    config = AppConfig.defaults()
    database = Database(config.database)
    database.migrate()
    database.upsert_thing(
        Thing(
            "t3_one",
            ThingKind.SUBMISSION,
            "python",
            now,
            title="Hello",
            score=7,
            reply_count=2,
        ),
        now,
    )
    runner = CliRunner()
    listed = runner.invoke(app, ["posts", "list", "--format", "json"])
    assert listed.exit_code == 0
    assert json.loads(listed.stdout)[0]["fullname"] == "t3_one"
    shown = runner.invoke(app, ["posts", "show", "t3_one"])
    assert shown.exit_code == 0
    assert json.loads(shown.stdout)["thing"]["score"] == 7


def test_cli_checks_rules_and_manages_schedule(tmp_path, monkeypatch, now) -> None:
    monkeypatch.setenv("REDDITCTL_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("REDDITCTL_DATA_DIR", str(tmp_path / "data"))
    config = AppConfig.defaults()
    database = Database(config.database)
    database.migrate()
    snapshot = RuleSnapshot.create(
        "python", "url", now, [Rule("1", "Self promotion", "Disclose self-promotion")]
    )
    database.store_rule_snapshot(snapshot)
    database.upsert_thing(
        Thing("t3_owned", ThingKind.SUBMISSION, "python", now, title="Owned", is_self=True),
        now,
    )
    draft_id = database.create_draft(
        DraftContent("python", "Title", "Body"), now, rule_hash=snapshot.content_hash
    )
    body = tmp_path / "body.md"
    body.write_text("Body")
    runner = CliRunner()
    checked = runner.invoke(
        app, ["rules", "check", "python", "--title", "Title", "--body", str(body)]
    )
    assert checked.exit_code == 0
    assert json.loads(checked.stdout)[0]["code"] == "promotion_review"
    added = runner.invoke(app, ["schedule", "add", draft_id, "--at", "+2h"])
    assert added.exit_code == 0
    action_id = added.stdout.strip()
    approved = runner.invoke(app, ["schedule", "approve", action_id])
    assert approved.exit_code == 0
    cancelled = runner.invoke(app, ["schedule", "cancel", action_id])
    assert cancelled.exit_code == 0
    audit = runner.invoke(app, ["audit", "list", "--action-id", action_id])
    assert audit.exit_code == 0
    assert len(json.loads(audit.stdout)) == 3
    update_body = tmp_path / "update.md"
    update_body.write_text("An update")
    update = runner.invoke(
        app,
        [
            "update",
            "plan",
            "t3_owned",
            "--at",
            "+1d",
            "--edit-body",
            str(update_body),
        ],
    )
    assert update.exit_code == 0
    assert database.get_action(update.stdout.strip()).action_type.value == "edit_self_body"
