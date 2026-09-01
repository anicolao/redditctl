from __future__ import annotations

import hashlib
import hmac
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route


class MappingRequest(BaseModel):
    slug: str
    destination: str


class RelayStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def migrate(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS mappings (
                    slug TEXT PRIMARY KEY,
                    destination TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS buckets (
                    slug TEXT NOT NULL REFERENCES mappings(slug),
                    bucket_at TEXT NOT NULL,
                    referrer_class TEXT NOT NULL,
                    bot INTEGER NOT NULL,
                    count INTEGER NOT NULL,
                    PRIMARY KEY (slug, bucket_at, referrer_class, bot)
                );
                """
            )

    def put(self, slug: str, destination: str) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", slug):
            raise ValueError("Slug must contain 2-63 lowercase letters, numbers, or hyphens")
        parsed = urlparse(destination)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Destination must be an HTTPS URL without embedded credentials")
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO mappings(slug, destination, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(slug) DO UPDATE SET destination = excluded.destination, active = 1",
                (slug, destination, datetime.now(UTC).isoformat()),
            )

    def destination(self, slug: str) -> str | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT destination FROM mappings WHERE slug = ? AND active = 1", (slug,)
            ).fetchone()
        return str(row["destination"]) if row else None

    def hit(self, slug: str, referrer_class: str, bot: bool, now: datetime) -> None:
        bucket = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0).isoformat()
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO buckets(slug, bucket_at, referrer_class, bot, count)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(slug, bucket_at, referrer_class, bot)
                DO UPDATE SET count = count + 1
                """,
                (slug, bucket, referrer_class, int(bot)),
            )

    def stats(self, slug: str) -> list[dict[str, object]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT bucket_at, referrer_class, bot, count FROM buckets "
                "WHERE slug = ? ORDER BY bucket_at",
                (slug,),
            ).fetchall()
        return [
            {
                "bucket_at": row["bucket_at"],
                "referrer_class": row["referrer_class"],
                "bot": bool(row["bot"]),
                "count": row["count"],
            }
            for row in rows
        ]


def create_relay_app(store: RelayStore, admin_token: str) -> Starlette:
    store.migrate()
    expected = hashlib.sha256(admin_token.encode()).digest()

    def authorized(request: Request) -> bool:
        supplied = request.headers.get("authorization", "")
        if not supplied.startswith("Bearer "):
            return False
        actual = hashlib.sha256(supplied.removeprefix("Bearer ").encode()).digest()
        return hmac.compare_digest(expected, actual)

    async def redirect(request: Request) -> Response:
        slug = request.path_params["slug"]
        destination = store.destination(slug)
        if destination is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        user_agent = request.headers.get("user-agent", "").casefold()
        bot = any(marker in user_agent for marker in ("bot", "crawler", "spider", "preview"))
        referrer = request.headers.get("referer", "")
        hostname = (urlparse(referrer).hostname or "").casefold()
        referrer_class = (
            "reddit" if hostname.endswith("reddit.com") else ("direct" if not hostname else "other")
        )
        store.hit(slug, referrer_class, bot, datetime.now(UTC))
        return RedirectResponse(
            destination,
            status_code=302,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    async def put_mapping(request: Request) -> Response:
        if not authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            mapping = MappingRequest.model_validate(await request.json())
            store.put(mapping.slug, mapping.destination)
        except (PydanticValidationError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(
            {"slug": mapping.slug, "destination": mapping.destination}, status_code=201
        )

    async def stats(request: Request) -> Response:
        if not authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        slug = request.path_params["slug"]
        return JSONResponse({"slug": slug, "buckets": store.stats(slug)})

    return Starlette(
        routes=[
            Route("/r/{slug:str}", redirect, methods=["GET"]),
            Route("/admin/mappings", put_mapping, methods=["POST"]),
            Route("/admin/stats/{slug:str}", stats, methods=["GET"]),
        ]
    )
