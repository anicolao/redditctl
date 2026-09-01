from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from platformdirs import PlatformDirs

from redditctl.errors import ConfigurationError


def _section(raw: object, name: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigurationError(f"Configuration section {name} must be a table")
    unknown = set(raw) - allowed
    if unknown:
        raise ConfigurationError(f"Unknown {name} configuration keys: {', '.join(sorted(unknown))}")
    return raw


@dataclass(frozen=True)
class SchedulingConfig:
    require_approval: bool = True
    minimum_global_gap_seconds: int = 21_600
    minimum_subreddit_gap_seconds: int = 604_800
    maximum_attempts: int = 3
    lease_seconds: int = 300


@dataclass(frozen=True)
class GeminiConfig:
    model: str = "gemini-2.5-flash"
    oauth_client: Path | None = None
    project: str | None = None
    location: str = "global"
    enabled: bool = False


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    config_dir: Path
    cache_dir: Path
    database: Path
    timezone: str = "UTC"
    reddit_client_id: str | None = None
    reddit_redirect_uri: str = "http://127.0.0.1:8765/callback"
    scheduling: SchedulingConfig = field(default_factory=SchedulingConfig)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)

    @property
    def zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except Exception as exc:
            raise ConfigurationError(f"Unknown timezone: {self.timezone}") from exc

    @classmethod
    def defaults(cls) -> AppConfig:
        dirs = PlatformDirs("redditctl", appauthor=False)
        config_dir = Path(os.getenv("REDDITCTL_CONFIG_DIR", dirs.user_config_dir))
        data_dir = Path(os.getenv("REDDITCTL_DATA_DIR", dirs.user_data_dir))
        cache_dir = Path(os.getenv("REDDITCTL_CACHE_DIR", dirs.user_cache_dir))
        return cls(
            data_dir=data_dir,
            config_dir=config_dir,
            cache_dir=cache_dir,
            database=data_dir / "redditctl.db",
        )

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        defaults = cls.defaults()
        path = path or defaults.config_dir / "config.toml"
        if not path.exists():
            return defaults
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        allowed = {"timezone", "database", "reddit", "scheduling", "gemini"}
        unknown = set(raw) - allowed
        if unknown:
            raise ConfigurationError(f"Unknown configuration keys: {', '.join(sorted(unknown))}")
        reddit = _section(raw.get("reddit", {}), "reddit", {"client_id", "redirect_uri"})
        scheduling = _section(
            raw.get("scheduling", {}),
            "scheduling",
            {
                "require_approval",
                "minimum_global_gap_seconds",
                "minimum_subreddit_gap_seconds",
                "maximum_attempts",
                "lease_seconds",
            },
        )
        gemini = _section(
            raw.get("gemini", {}),
            "gemini",
            {"model", "oauth_client", "project", "location", "enabled"},
        )
        return cls(
            data_dir=defaults.data_dir,
            config_dir=defaults.config_dir,
            cache_dir=defaults.cache_dir,
            database=Path(raw.get("database", defaults.database)).expanduser(),
            timezone=raw.get("timezone", "UTC"),
            reddit_client_id=reddit.get("client_id"),
            reddit_redirect_uri=reddit.get("redirect_uri", defaults.reddit_redirect_uri),
            scheduling=SchedulingConfig(**scheduling),
            gemini=GeminiConfig(
                model=gemini.get("model", "gemini-2.5-flash"),
                oauth_client=(
                    Path(gemini["oauth_client"]).expanduser()
                    if gemini.get("oauth_client")
                    else None
                ),
                project=gemini.get("project"),
                location=gemini.get("location", "global"),
                enabled=gemini.get("enabled", False),
            ),
        )

    def initialize(self) -> Path:
        for directory in (self.config_dir, self.data_dir, self.cache_dir):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.config_dir / "config.toml"
        if not path.exists():
            path.write_text(
                'timezone = "UTC"\n\n'
                '[reddit]\nclient_id = ""\n'
                f'redirect_uri = "{self.reddit_redirect_uri}"\n\n'
                '[gemini]\nenabled = false\nmodel = "gemini-2.5-flash"\n'
                'oauth_client = ""\nproject = ""\nlocation = "global"\n',
                encoding="utf-8",
            )
            path.chmod(0o600)
        return path
