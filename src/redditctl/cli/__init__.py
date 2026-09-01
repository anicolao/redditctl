from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

from redditctl.application import AccountService, DiscoveryApplication, DraftingService
from redditctl.bootstrap import build_database, build_reddit
from redditctl.clock import SystemClock
from redditctl.config import AppConfig
from redditctl.credentials import KeyringCredentialStore
from redditctl.domain import ActionState, ActionType, DraftContent
from redditctl.drafting import DraftRequest, GeminiGateway, GeminiOAuthManager
from redditctl.errors import RedditctlError
from redditctl.links import LinkRelayClient
from redditctl.reddit.oauth import RedditOAuth, RedditTokenProvider
from redditctl.rules import RuleEngine
from redditctl.scheduling import SchedulePlanner, SchedulerWorker, WorkerLock, parse_when

app = typer.Typer(no_args_is_help=True, help="Manage a Reddit presence from the terminal.")
auth_app = typer.Typer(help="Authorize external services.")
posts_app = typer.Typer(help="Synchronize and inspect owned Reddit content.")
rules_app = typer.Typer(help="Synchronize and check subreddit rules.")
draft_app = typer.Typer(help="Create rule-aware drafts.")
schedule_app = typer.Typer(help="Plan and execute Reddit actions.")
update_app = typer.Typer(help="Plan edits and follow-up comments on owned threads.")
links_app = typer.Typer(help="Manage aggregate click measurement.")
relay_app = typer.Typer(help="Run the optional redirect relay.")
audit_app = typer.Typer(help="Inspect the local mutation log.")
for name, group in (
    ("auth", auth_app),
    ("posts", posts_app),
    ("rules", rules_app),
    ("draft", draft_app),
    ("schedule", schedule_app),
    ("update", update_app),
    ("links", links_app),
    ("relay", relay_app),
    ("audit", audit_app),
):
    app.add_typer(group, name=name)


def _config() -> AppConfig:
    return AppConfig.load()


def _json(value: object) -> None:
    typer.echo(json.dumps(value, default=str, indent=2, sort_keys=True))


@app.command("init")
def initialize() -> None:
    """Create a private config and initialize the local database."""
    config = AppConfig.defaults()
    path = config.initialize()
    build_database(config)
    typer.echo(f"Initialized {path}")


@auth_app.command("reddit")
def authorize_reddit() -> None:
    """Authorize Reddit using the browser and loopback OAuth flow."""
    config = _config()
    client_id = config.reddit_client_id
    if not client_id:
        raise typer.BadParameter("Set reddit.client_id in config.toml first")

    async def authorize() -> None:
        async with httpx.AsyncClient(timeout=30) as http:
            store = KeyringCredentialStore()
            oauth = RedditOAuth(
                client_id,
                config.reddit_redirect_uri,
                http,
            )
            tokens = await oauth.authorize_interactive(
                ("identity", "history", "read", "submit", "edit")
            )
            RedditTokenProvider(oauth, store).store(tokens)

    asyncio.run(authorize())
    typer.echo("Reddit authorization stored in the OS credential store")


@auth_app.command("gemini")
def authorize_gemini() -> None:
    """Authorize Gemini using a Google desktop OAuth client file."""
    config = _config()
    if config.gemini.oauth_client is None:
        raise typer.BadParameter("Set gemini.oauth_client in config.toml first")
    GeminiOAuthManager(KeyringCredentialStore()).authorize(config.gemini.oauth_client)
    typer.echo("Gemini authorization stored in the OS credential store")


@auth_app.command("relay")
def authorize_relay(
    token: Annotated[
        str,
        typer.Option(prompt="Relay admin token", hide_input=True, confirmation_prompt=True),
    ],
) -> None:
    """Store the separately deployed relay's admin token securely."""
    KeyringCredentialStore().set("relay:admin", token)
    typer.echo("Relay admin token stored in the OS credential store")


@posts_app.command("sync")
def sync_posts(limit: Annotated[int, typer.Option(min=1, max=1000)] = 100) -> None:
    """Synchronize recent submissions, comments, and metric snapshots."""
    config = _config()
    database = build_database(config)

    async def sync() -> tuple[int, int]:
        async with httpx.AsyncClient(timeout=30) as http:
            return await AccountService(
                database, build_reddit(config, http), SystemClock()
            ).synchronize(limit=limit)

    found, changed = asyncio.run(sync())
    typer.echo(f"Synchronized {found} items; {changed} metric snapshots changed")


@posts_app.command("list")
def list_posts(
    sort: Annotated[str, typer.Option(help="created_at, score, or replies")] = "created_at",
    subreddit: Annotated[str | None, typer.Option()] = None,
    output: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """List locally synchronized content by metrics."""
    things = build_database(_config()).list_things(sort=sort, subreddit=subreddit)
    rows = [asdict(thing) for thing in things]
    if output == "json":
        _json(rows)
        return
    typer.echo("NAME\tSUBREDDIT\tSCORE\tREPLIES\tTITLE")
    for thing in things:
        typer.echo(
            f"{thing.fullname}\tr/{thing.subreddit}\t{thing.score or 0}\t"
            f"{thing.reply_count or 0}\t{thing.title or thing.body[:60]}"
        )


@posts_app.command("show")
def show_post(fullname: str) -> None:
    """Show an item and its locally recorded metric history."""
    database = build_database(_config())
    thing = database.get_thing(fullname)
    if thing is None:
        raise typer.BadParameter(f"Unknown Reddit fullname: {fullname}")
    _json({"thing": asdict(thing), "metrics": database.metric_history(fullname)})


@rules_app.command("sync")
def sync_rules(subreddit: str) -> None:
    """Fetch and version the current rules for one subreddit."""
    config = _config()
    database = build_database(config)

    async def sync() -> Any:
        async with httpx.AsyncClient(timeout=30) as http:
            service = AccountService(database, build_reddit(config, http), SystemClock())
            return await service.synchronize_rules(subreddit.removeprefix("r/"))

    snapshot = asyncio.run(sync())
    typer.echo(f"Stored {len(snapshot.rules)} rules ({snapshot.content_hash[:12]})")


@rules_app.command("check")
def check_rules(
    subreddit: str,
    title: Annotated[str, typer.Option()],
    body_file: Annotated[Path, typer.Option("--body")],
) -> None:
    """Run deterministic checks against a cached rule snapshot."""
    database = build_database(_config())
    snapshot = database.latest_rule_snapshot(subreddit.removeprefix("r/"))
    findings = RuleEngine().check(
        DraftContent(subreddit, title, body_file.read_text(encoding="utf-8")), snapshot
    )
    _json([asdict(finding) for finding in findings])


@app.command("discover")
def discover(query: str, limit: Annotated[int, typer.Option(min=1, max=50)] = 20) -> None:
    """Rank potentially suitable subreddits with visible evidence."""
    config = _config()
    database = build_database(config)

    async def run() -> Any:
        async with httpx.AsyncClient(timeout=30) as http:
            return await DiscoveryApplication(database, build_reddit(config, http)).discover(
                query, limit=limit
            )

    _json([asdict(item) for item in asyncio.run(run())])


@draft_app.command("new")
def new_draft(
    subreddit: str,
    notes_file: Annotated[Path, typer.Option("--from")],
    kind: Annotated[str, typer.Option()] = "self",
) -> None:
    """Send an explicit rules-and-notes bundle to Gemini and save its draft."""
    config = _config()
    if not config.gemini.enabled:
        raise typer.BadParameter("Enable Gemini in config.toml after reviewing data sharing")
    if not config.gemini.project:
        raise typer.BadParameter("Set gemini.project to a Google Cloud project with Vertex AI")
    database = build_database(config)
    subreddit = subreddit.removeprefix("r/")
    snapshot = database.latest_rule_snapshot(subreddit)
    if snapshot is None:
        raise typer.BadParameter("Synchronize the subreddit rules first")
    request = DraftRequest(notes_file.read_text(encoding="utf-8"), subreddit, snapshot, kind=kind)
    manager = GeminiOAuthManager(KeyringCredentialStore())
    llm = GeminiGateway.from_oauth(
        manager,
        config.gemini.model,
        config.gemini.project,
        config.gemini.location,
    )
    draft_id, content = asyncio.run(
        DraftingService(database, llm, SystemClock(), config.gemini.model).create(request)
    )
    _json({"id": draft_id, "draft": asdict(content), "rule_hash": snapshot.content_hash})


@schedule_app.command("add")
def add_schedule(
    draft_id: str,
    at: Annotated[str, typer.Option("--at")],
) -> None:
    """Add a saved draft to the approval queue."""
    config = _config()
    database = build_database(config)
    current = database.current_draft(draft_id)
    if current is None:
        raise typer.BadParameter(f"Unknown draft: {draft_id}")
    content, rule_hash = current
    now = datetime.now(UTC)
    action_type = ActionType.SUBMIT_LINK if content.kind == "link" else ActionType.SUBMIT_SELF
    action_id = SchedulePlanner(database, config.scheduling).plan(
        action_type,
        parse_when(at, now, config.zone),
        content.subreddit,
        asdict(content),
        now,
        rule_hash=rule_hash,
    )
    typer.echo(action_id)


@schedule_app.command("approve")
def approve_schedule(action_id: str) -> None:
    """Approve a frozen scheduled payload."""
    if not build_database(_config()).approve_action(action_id, datetime.now(UTC)):
        raise typer.BadParameter("Action is missing or cannot be approved from its current state")
    typer.echo(f"Approved {action_id}")


@update_app.command("plan")
def plan_update(
    fullname: str,
    at: Annotated[str, typer.Option("--at")],
    edit_body: Annotated[Path | None, typer.Option("--edit-body")] = None,
    comment: Annotated[Path | None, typer.Option("--comment")] = None,
) -> None:
    """Queue either a self-post body edit or a follow-up comment for approval."""
    if (edit_body is None) == (comment is None):
        raise typer.BadParameter("Choose exactly one of --edit-body or --comment")
    config = _config()
    database = build_database(config)
    thing = database.get_thing(fullname)
    if thing is None:
        raise typer.BadParameter("Synchronize the target thread first")
    action_type = (
        ActionType.EDIT_SELF_BODY if edit_body is not None else ActionType.POST_FOLLOWUP_COMMENT
    )
    content_file = edit_body or comment
    assert content_file is not None
    now = datetime.now(UTC)
    action_id = SchedulePlanner(database, config.scheduling).plan(
        action_type,
        parse_when(at, now, config.zone),
        thing.subreddit,
        {"fullname": fullname, "body": content_file.read_text(encoding="utf-8")},
        now,
        rule_hash=(
            snapshot.content_hash
            if (snapshot := database.latest_rule_snapshot(thing.subreddit))
            else None
        ),
    )
    typer.echo(action_id)


@schedule_app.command("cancel")
def cancel_schedule(action_id: str) -> None:
    """Cancel an action that has not begun."""
    database = build_database(_config())
    changed = database.transition_action(
        action_id,
        {
            ActionState.PENDING_APPROVAL,
            ActionState.APPROVED,
            ActionState.RETRY_WAIT,
            ActionState.NEEDS_REVIEW,
        },
        ActionState.CANCELLED,
        datetime.now(UTC),
    )
    if not changed:
        raise typer.BadParameter("Action is missing or cannot be cancelled")
    typer.echo(f"Cancelled {action_id}")


@schedule_app.command("list")
def list_schedule() -> None:
    """List scheduled actions and their state."""
    _json([asdict(action) for action in build_database(_config()).list_actions()])


@schedule_app.command("run-once")
def run_worker_once() -> None:
    """Claim and execute at most one due approved action."""
    config = _config()
    database = build_database(config)

    async def run() -> Any:
        async with httpx.AsyncClient(timeout=30) as http:
            worker = SchedulerWorker(
                database, build_reddit(config, http), SystemClock(), config.scheduling
            )
            with WorkerLock(config.data_dir / "worker.lock"):
                return await worker.run_once()

    _json(asdict(asyncio.run(run())))


@audit_app.command("list")
def list_audit(action_id: Annotated[str | None, typer.Option()] = None) -> None:
    """List append-only scheduler audit events."""
    _json(build_database(_config()).audit_events(action_id))


@links_app.command("create")
def create_link(
    destination: str,
    slug: Annotated[str, typer.Option()],
    relay_url: Annotated[str, typer.Option()],
) -> None:
    """Create a redirect mapping without sharing Reddit credentials."""
    config = _config()
    token = KeyringCredentialStore().get("relay:admin")
    if token is None:
        raise typer.BadParameter("Store the relay admin token in the OS credential store first")

    async def create() -> str:
        async with httpx.AsyncClient(timeout=15) as http:
            await LinkRelayClient(relay_url, token, http).create_mapping(slug, destination)
            return f"{relay_url.rstrip('/')}/r/{slug}"

    url = asyncio.run(create())
    build_database(config).upsert_link_mapping(slug, destination, datetime.now(UTC))
    typer.echo(url)


@links_app.command("stats")
def link_stats(
    slug: str,
    relay_url: Annotated[str, typer.Option()],
) -> None:
    """Fetch aggregate human/bot click buckets from the relay."""
    config = _config()
    token = KeyringCredentialStore().get("relay:admin")
    if token is None:
        raise typer.BadParameter("Store the relay admin token in the OS credential store first")

    async def stats() -> Any:
        async with httpx.AsyncClient(timeout=15) as http:
            return await LinkRelayClient(relay_url, token, http).stats(slug)

    response = asyncio.run(stats())
    database = build_database(config)
    for bucket in response.buckets:
        database.upsert_link_snapshot(
            slug,
            bucket.bucket_at,
            bucket.referrer_class,
            bucket.bot,
            bucket.count,
        )
    _json(
        {
            "buckets": [bucket.model_dump(mode="json") for bucket in response.buckets],
            "totals": database.link_totals(slug),
        }
    )


@app.command("worker")
def worker(poll_seconds: Annotated[float, typer.Option(min=1)] = 30) -> None:
    """Run the scheduler continuously until interrupted."""
    config = _config()
    database = build_database(config)

    async def run() -> None:
        async with httpx.AsyncClient(timeout=30) as http:
            scheduler = SchedulerWorker(
                database, build_reddit(config, http), SystemClock(), config.scheduling
            )
            with WorkerLock(config.data_dir / "worker.lock"):
                while True:
                    result = await scheduler.run_once()
                    if result.action_id is not None:
                        _json(asdict(result))
                    await asyncio.sleep(poll_seconds)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        typer.echo("Worker stopped")


@relay_app.command("serve")
def serve_relay(
    database: Annotated[Path, typer.Option()] = Path("relay.db"),
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8787,
) -> None:
    """Serve the isolated aggregate redirect component."""
    import uvicorn

    from redditctl.relay import RelayStore, create_relay_app

    token = os.getenv("REDDITCTL_RELAY_ADMIN_TOKEN")
    if not token:
        raise typer.BadParameter("Set REDDITCTL_RELAY_ADMIN_TOKEN for the isolated relay")
    uvicorn.run(create_relay_app(RelayStore(database), token), host=host, port=port)


@app.command("tui")
def tui() -> None:
    """Open the keyboard-driven terminal interface."""
    from redditctl.tui import RedditctlApp

    RedditctlApp(build_database(_config())).run()


def run_cli() -> None:
    try:
        app()
    except RedditctlError as exc:
        typer.echo(f"Error: {exc.message}", err=True)
        raise typer.Exit(1) from exc
