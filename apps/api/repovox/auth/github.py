"""GitHub OAuth 2.0 sign-in for operator-provisioned accounts.

The API's database role cannot create users, so this adapter never signs anyone up: an
operator provisions each allowed GitHub account first (`python -m repovox.auth.accounts`). The
callback exchanges the authorization code, reads the account's numeric id from GitHub, and
signs in only an active account provisioned under that id. The owner id is derived from the
numeric id alone, so a renamed GitHub login keeps the same tenant. The GitHub access token is
used for one request and never stored, logged or sent to the browser.
"""

import base64
import hashlib
import secrets
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid5

import httpx
from sqlalchemy import Engine

from repovox.core.config import Settings
from repovox.core.errors import DomainError
from repovox.db.database import rows, tenant

ISSUER = "https://github.com"
AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
# Only the public profile is read: its numeric id identifies the account.
SCOPE = "read:user"
CALLBACK_PATH = "/api/v1/auth/github/callback"
STATE_COOKIE = "rv_oauth_state"
VERIFIER_COOKIE = "rv_oauth_verifier"  # PKCE (RFC 7636): proves the callback is this login.
STATE_SECONDS = 600
# Fixed for the life of the deployment: changing it would move every account to a new owner.
NAMESPACE = UUID("44765a42-e98a-407c-ad19-38f3285c3000")
MAX_RESPONSE = 64 * 1024


def pkce() -> tuple[str, str]:
    """A PKCE code verifier and its S256 challenge."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def owner_for(github_id: int) -> UUID:
    """The RepoVox owner id of a GitHub account, from its numeric id only."""
    if type(github_id) is not int or github_id <= 0:
        raise ValueError("GitHub account ids are positive integers")
    return uuid5(NAMESPACE, f"github:{github_id}")


@dataclass(frozen=True)
class GitHubAccount:
    id: int
    login: str


class GitHubOAuth:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        if not settings.github_configured or settings.github_client_secret is None:
            raise ValueError("GitHub OAuth requires a client id and secret")
        self.client_id = (settings.github_client_id or "").strip()
        self._secret = settings.github_client_secret
        self.redirect_uri = settings.origin + CALLBACK_PATH
        self.secure = settings.origin.startswith("https://")
        self.transport = transport  # Injected only by tests.

    def authorize_url(self, state: str, challenge: str) -> str:
        query = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "allow_signup": "false",
        }
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    def account(self, code: str, verifier: str) -> GitHubAccount:
        """The GitHub account an authorization code belongs to. Fails closed on anything odd."""
        try:
            with httpx.Client(
                timeout=10,
                follow_redirects=False,
                verify=ssl.create_default_context(),
                transport=self.transport,
                headers={"User-Agent": "RepoVox"},
            ) as client:
                exchanged = self._json(
                    client.post(
                        TOKEN_URL,
                        headers={"Accept": "application/json"},
                        data={
                            "client_id": self.client_id,
                            "client_secret": self._secret.get_secret_value(),
                            "code": code,
                            "code_verifier": verifier,
                            "redirect_uri": self.redirect_uri,
                        },
                    )
                )
                token = exchanged.get("access_token")
                if not isinstance(token, str) or not token or "error" in exchanged:
                    raise DomainError("oauth_rejected", 401)
                profile = self._json(
                    client.get(
                        USER_URL,
                        headers={
                            "Accept": "application/vnd.github+json",
                            "Authorization": f"Bearer {token}",
                            "X-GitHub-Api-Version": "2022-11-28",
                        },
                    )
                )
                del token
        except httpx.HTTPError:
            raise DomainError("oauth_unavailable", 502) from None
        github_id, login = profile.get("id"), profile.get("login")
        if type(github_id) is not int or github_id <= 0 or not isinstance(login, str):
            raise DomainError("oauth_rejected", 401)
        return GitHubAccount(github_id, login)

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        if response.status_code != 200 or len(response.content) > MAX_RESPONSE:
            raise DomainError("oauth_unavailable", 502)
        try:
            body = response.json()
        except ValueError:
            raise DomainError("oauth_unavailable", 502) from None
        if not isinstance(body, dict):
            raise DomainError("oauth_unavailable", 502)
        return body


def provisioned(engine: Engine, github_id: int) -> UUID | None:
    """The owner id of an active, provisioned GitHub account, read as that owner (RLS)."""
    owner = owner_for(github_id)
    with tenant(engine, owner) as connection:
        found = rows(
            connection,
            "SELECT id FROM users WHERE id=:owner AND issuer=:issuer AND auth_subject=:subject "
            "AND status='active' AND deleted_at IS NULL",
            owner=owner,
            issuer=ISSUER,
            subject=str(github_id),
        )
    return owner if found else None
