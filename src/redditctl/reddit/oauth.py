from __future__ import annotations

import asyncio
import base64
import secrets
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from redditctl.credentials import CredentialStore
from redditctl.errors import AuthenticationError, NetworkError

AUTH_URL = "https://www.reddit.com/api/v1/authorize"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"


@dataclass(frozen=True)
class OAuthTokens:
    access_token: str
    expires_in: int
    refresh_token: str | None = None


class RedditOAuth:
    def __init__(
        self,
        client_id: str,
        redirect_uri: str,
        http: httpx.AsyncClient,
        *,
        user_agent: str = "redditctl/0.1 by its authenticated user",
    ) -> None:
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.http = http
        self.user_agent = user_agent

    def authorization_url(self, state: str, scopes: tuple[str, ...]) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "state": state,
                "redirect_uri": self.redirect_uri,
                "duration": "permanent",
                "scope": " ".join(scopes),
            }
        )
        return f"{AUTH_URL}?{query}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        credentials = base64.b64encode(f"{self.client_id}:".encode()).decode()
        try:
            response = await self.http.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                },
                headers={
                    "Authorization": f"Basic {credentials}",
                    "User-Agent": self.user_agent,
                },
            )
        except httpx.HTTPError as exc:
            raise NetworkError("Could not exchange the Reddit authorization code") from exc
        return self._parse_token_response(response)

    async def refresh(self, refresh_token: str) -> OAuthTokens:
        credentials = base64.b64encode(f"{self.client_id}:".encode()).decode()
        try:
            response = await self.http.post(
                TOKEN_URL,
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                headers={
                    "Authorization": f"Basic {credentials}",
                    "User-Agent": self.user_agent,
                },
            )
        except httpx.HTTPError as exc:
            raise NetworkError("Could not refresh Reddit authorization") from exc
        return self._parse_token_response(response)

    @staticmethod
    def _parse_token_response(response: httpx.Response) -> OAuthTokens:
        if response.status_code != 200:
            raise AuthenticationError(f"Reddit OAuth failed with HTTP {response.status_code}")
        try:
            payload = response.json()
            if payload.get("error"):
                raise AuthenticationError(f"Reddit OAuth failed: {payload['error']}")
            return OAuthTokens(
                access_token=str(payload["access_token"]),
                expires_in=int(payload.get("expires_in", 3600)),
                refresh_token=payload.get("refresh_token"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthenticationError("Reddit returned an invalid OAuth response") from exc

    async def authorize_interactive(
        self, scopes: tuple[str, ...], wait_seconds: int = 180
    ) -> OAuthTokens:
        parsed = urlparse(self.redirect_uri)
        if parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.port:
            raise AuthenticationError(
                "Interactive OAuth requires a loopback redirect URI with a port"
            )
        state = secrets.token_urlsafe(32)
        result: dict[str, str] = {}
        completed = Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                query = parse_qs(urlparse(self.path).query)
                if query.get("state", [None])[0] != state:
                    self.send_response(400)
                    body = b"Invalid OAuth state. You may close this window."
                    completed.set()
                elif query.get("error"):
                    result["error"] = query["error"][0]
                    self.send_response(400)
                    body = b"Reddit authorization was denied. You may close this window."
                    completed.set()
                elif query.get("code"):
                    result["code"] = query["code"][0]
                    self.send_response(200)
                    body = b"redditctl is authorized. You may close this window."
                    completed.set()
                else:
                    self.send_response(400)
                    body = b"Missing authorization code."
                    completed.set()
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer((parsed.hostname, parsed.port), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            webbrowser.open(self.authorization_url(state, scopes))
            received = await asyncio.to_thread(completed.wait, wait_seconds)
            if not received:
                raise AuthenticationError("Timed out waiting for Reddit authorization")
            if "error" in result:
                raise AuthenticationError(f"Reddit authorization failed: {result['error']}")
            code = result.get("code")
            if code is None:
                raise AuthenticationError("Reddit authorization returned no code")
            return await self.exchange_code(code)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class RedditTokenProvider:
    def __init__(
        self,
        oauth: RedditOAuth,
        credentials: CredentialStore,
        credential_name: str = "reddit:refresh",
    ) -> None:
        self.oauth = oauth
        self.credentials = credentials
        self.credential_name = credential_name
        self._access_token: str | None = None
        self._expires_at = 0.0

    async def get_access_token(self) -> str:
        if self._access_token and self._expires_at > time.monotonic() + 30:
            return self._access_token
        refresh_token = self.credentials.get(self.credential_name)
        if not refresh_token:
            raise AuthenticationError("Reddit is not authorized; run `redditctl auth reddit`")
        tokens = await self.oauth.refresh(refresh_token)
        self._access_token = tokens.access_token
        self._expires_at = time.monotonic() + tokens.expires_in
        return tokens.access_token

    def store(self, tokens: OAuthTokens) -> None:
        if not tokens.refresh_token:
            raise AuthenticationError("Reddit did not return a permanent refresh token")
        self.credentials.set(self.credential_name, tokens.refresh_token)
        self._access_token = tokens.access_token
        self._expires_at = time.monotonic() + tokens.expires_in


class StaticTokenProvider:
    def __init__(self, token: str) -> None:
        self.token = token

    async def get_access_token(self) -> str:
        return self.token
