from __future__ import annotations

from datetime import UTC
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

import redditctl.cli as cli_module
from redditctl.bootstrap import build_reddit
from redditctl.cli import app
from redditctl.clock import SystemClock
from redditctl.config import AppConfig
from redditctl.credentials import MemoryCredentialStore
from redditctl.errors import ConfigurationError


def config(tmp_path: Path, *, client_id: str | None = None, timezone: str = "UTC") -> AppConfig:
    return AppConfig(
        data_dir=tmp_path,
        config_dir=tmp_path,
        cache_dir=tmp_path,
        database=tmp_path / "db.sqlite",
        reddit_client_id=client_id,
        timezone=timezone,
    )


@pytest.mark.asyncio
async def test_bootstrap_validates_reddit_client_id(tmp_path: Path) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    ) as http:
        with pytest.raises(ConfigurationError):
            build_reddit(config(tmp_path), http)
        assert build_reddit(config(tmp_path, client_id="client"), http).http is http


def test_clock_and_unknown_timezone(tmp_path: Path) -> None:
    assert SystemClock().now().tzinfo is UTC
    with pytest.raises(ConfigurationError, match="Unknown timezone"):
        _ = config(tmp_path, timezone="Mars/Olympus").zone


def test_cli_stores_relay_token(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemoryCredentialStore()
    monkeypatch.setattr(cli_module, "KeyringCredentialStore", lambda: store)
    result = CliRunner().invoke(app, ["auth", "relay", "--token", "secret"])
    assert result.exit_code == 0
    assert store.get("relay:admin") == "secret"
