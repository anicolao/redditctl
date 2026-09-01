from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from redditctl.clock import FrozenClock
from redditctl.persistence import Database


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 9, 1, 12, tzinfo=UTC)


@pytest.fixture
def clock(now: datetime) -> FrozenClock:
    return FrozenClock(now)


@pytest.fixture
def database(tmp_path: Path) -> Database:
    result = Database(tmp_path / "redditctl.db")
    result.migrate()
    return result
