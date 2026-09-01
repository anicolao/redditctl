from __future__ import annotations

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import DataTable, Footer, Header, Label, TabbedContent, TabPane

from redditctl.persistence import Database


class RedditctlApp(App[None]):
    """A deliberately small, read-only MVP dashboard over shared services."""

    TITLE = "redditctl"
    SUB_TITLE = "local-first Reddit workspace"
    CSS = """
    Screen { background: $surface; }
    #empty-posts, #empty-schedule { padding: 1 2; color: $text-muted; }
    DataTable { height: 1fr; }
    """
    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_data", "Refresh"),
    ]

    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="posts"):
            with TabPane("Posts", id="posts"), Container():
                yield Label(
                    "No synchronized posts yet. Run `redditctl posts sync`.", id="empty-posts"
                )
                yield DataTable(id="posts-table", zebra_stripes=True)
            with TabPane("Schedule", id="schedule"), Container():
                yield Label("No scheduled actions yet.", id="empty-schedule")
                yield DataTable(id="schedule-table", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        posts = self.query_one("#posts-table", DataTable)
        posts.add_columns("Name", "Subreddit", "Score", "Replies", "Title")
        schedule = self.query_one("#schedule-table", DataTable)
        schedule.add_columns("Action", "Due", "Subreddit", "State")
        self.action_refresh_data()

    def action_refresh_data(self) -> None:
        posts = self.query_one("#posts-table", DataTable)
        posts.clear()
        things = self.database.list_things(limit=200)
        for thing in things:
            posts.add_row(
                thing.fullname,
                f"r/{thing.subreddit}",
                str(thing.score or 0),
                str(thing.reply_count or 0),
                thing.title or thing.body[:80],
            )
        self.query_one("#empty-posts", Label).display = not things

        schedule = self.query_one("#schedule-table", DataTable)
        schedule.clear()
        actions = self.database.list_actions(limit=200)
        for action in actions:
            schedule.add_row(
                action.action_id,
                action.due_at.isoformat(timespec="minutes"),
                f"r/{action.subreddit}",
                action.state.value,
            )
        self.query_one("#empty-schedule", Label).display = not actions
