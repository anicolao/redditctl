from __future__ import annotations

import pytest
from textual.widgets import DataTable

from redditctl.domain import Thing, ThingKind
from redditctl.tui import RedditctlApp


@pytest.mark.asyncio
async def test_tui_loads_posts_and_schedule_tabs(database, now) -> None:
    database.upsert_thing(
        Thing("t3_one", ThingKind.SUBMISSION, "python", now, title="Hello", score=3), now
    )
    app = RedditctlApp(database)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        table = app.query_one("#posts-table", DataTable)
        assert table.row_count == 1
        await pilot.press("r")
        assert table.row_count == 1
