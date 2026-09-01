from __future__ import annotations

import httpx

from redditctl.config import AppConfig
from redditctl.credentials import KeyringCredentialStore
from redditctl.errors import ConfigurationError
from redditctl.persistence import Database
from redditctl.reddit import RedditClient
from redditctl.reddit.oauth import RedditOAuth, RedditTokenProvider


def build_database(config: AppConfig) -> Database:
    database = Database(config.database)
    database.migrate()
    return database


def build_reddit(config: AppConfig, http: httpx.AsyncClient) -> RedditClient:
    if not config.reddit_client_id:
        raise ConfigurationError("Set reddit.client_id in config.toml first")
    credentials = KeyringCredentialStore()
    oauth = RedditOAuth(
        config.reddit_client_id,
        config.reddit_redirect_uri,
        http,
    )
    return RedditClient(RedditTokenProvider(oauth, credentials), http)
