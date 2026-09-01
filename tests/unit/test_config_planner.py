from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from redditctl.config import AppConfig, SchedulingConfig
from redditctl.domain import ActionState, ActionType, Thing, ThingKind
from redditctl.errors import ConfigurationError, PolicyError, UsageError
from redditctl.persistence import Database
from redditctl.scheduling import SchedulePlanner, parse_when


def test_parse_relative_and_local_absolute_times(now: datetime) -> None:
    assert parse_when("+2h", now, ZoneInfo("UTC")) == now + timedelta(hours=2)
    parsed = parse_when("2026-09-02T08:00:00", now, ZoneInfo("America/Toronto"))
    assert parsed == datetime(2026, 9, 2, 12, tzinfo=UTC)
    with pytest.raises(UsageError):
        parse_when("tomorrow", now, ZoneInfo("UTC"))


def test_config_loads_and_rejects_unknown_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REDDITCTL_DATA_DIR", str(tmp_path / "data"))
    valid = tmp_path / "valid.toml"
    valid.write_text('timezone = "America/Toronto"\n[reddit]\nclient_id = "client"\n')
    config = AppConfig.load(valid)
    assert config.reddit_client_id == "client"
    assert config.zone.key == "America/Toronto"
    invalid = tmp_path / "invalid.toml"
    invalid.write_text("typo = true\n")
    with pytest.raises(ConfigurationError):
        AppConfig.load(invalid)
    invalid.write_text("[gemini]\ntypo = true\n")
    with pytest.raises(ConfigurationError, match="gemini"):
        AppConfig.load(invalid)


def test_planner_validates_target_and_spacing(database: Database, now: datetime) -> None:
    planner = SchedulePlanner(
        database,
        SchedulingConfig(minimum_global_gap_seconds=3600, minimum_subreddit_gap_seconds=7200),
    )
    first = planner.plan(
        ActionType.SUBMIT_SELF,
        now + timedelta(hours=3),
        "python",
        {"title": "One", "body": "Body"},
        now,
    )
    assert database.get_action(first).state is ActionState.PENDING_APPROVAL
    with pytest.raises(PolicyError, match="global"):
        planner.plan(
            ActionType.SUBMIT_SELF,
            now + timedelta(hours=3, minutes=30),
            "other",
            {"title": "Two"},
            now,
        )
    with pytest.raises(PolicyError, match="not been synchronized"):
        planner.plan(
            ActionType.EDIT_SELF_BODY,
            now + timedelta(days=1),
            "python",
            {"fullname": "t3_missing", "body": "update"},
            now,
        )


def test_planner_allows_owned_self_post_edit(database: Database, now: datetime) -> None:
    database.upsert_thing(Thing("t3_self", ThingKind.SUBMISSION, "python", now, is_self=True), now)
    action_id = SchedulePlanner(database, SchedulingConfig()).plan(
        ActionType.EDIT_SELF_BODY,
        now + timedelta(days=1),
        "python",
        {"fullname": "t3_self", "body": "Update"},
        now,
    )
    assert database.get_action(action_id) is not None
