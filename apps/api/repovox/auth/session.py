import hashlib
import secrets
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import Engine, text

from repovox.core.config import Settings
from repovox.core.errors import DomainError
from repovox.db.database import rows, tenant


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class Identity:
    owner_id: UUID
    session_id: UUID
    csrf_hash: str
    display_name: str
    email: str


class IdentityAdapter(Protocol):
    """Future OIDC adapter resolves a verified issuer/subject to the same Identity."""

    def authenticate(self, cookie: str | None) -> Identity: ...


class DevelopmentSessions:
    def __init__(self, engine: Engine, settings: Settings) -> None:
        self.engine = engine
        self.settings = settings
        self.signer = URLSafeTimedSerializer(
            settings.session_secret.get_secret_value(), salt="repovox-development-session-v1"
        )

    def sign_in(self, subject: str, client_address: str = "local") -> tuple[str, str]:
        if not self.settings.dev_auth or self.settings.environment not in {"development", "test"}:
            raise DomainError("development_auth_disabled", 503)
        with self.engine.begin() as connection:
            users = rows(
                connection,
                "SELECT id FROM rv.dev_identity(:subject,:client)",
                subject=subject,
                client=digest(client_address),
            )
        if not users:
            raise DomainError("invalid_development_identity", 401)
        owner = users[0]["id"]
        nonce, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with tenant(self.engine, owner) as connection:
            connection.execute(
                text(
                    "INSERT INTO auth_sessions(owner_id,nonce_hash,csrf_hash,expires_at) "
                    "VALUES(:owner,:nonce,:csrf,now()+:duration*interval '1 second')"
                ),
                {
                    "owner": owner,
                    "nonce": digest(nonce),
                    "csrf": digest(csrf),
                    "duration": self.settings.session_seconds,
                },
            )
        return self.signer.dumps({"owner": str(owner), "nonce": nonce}), csrf

    def authenticate(self, cookie: str | None) -> Identity:
        if not cookie:
            raise DomainError("session_required", 401)
        try:
            data = self.signer.loads(cookie, max_age=self.settings.session_seconds)
            owner = UUID(data["owner"])
            nonce = digest(data["nonce"])
        except (BadSignature, ValueError, KeyError, TypeError):
            raise DomainError("session_expired", 401) from None
        with tenant(self.engine, owner) as connection:
            found = rows(
                connection,
                "SELECT s.id,s.csrf_hash,u.display_name,u.email FROM auth_sessions s "
                "JOIN users u ON u.id=s.owner_id WHERE s.nonce_hash=:nonce "
                "AND s.owner_id=:owner AND s.revoked_at IS NULL AND s.expires_at>now() "
                "AND u.status='active' AND u.deleted_at IS NULL",
                owner=owner,
                nonce=nonce,
            )
        if not found:
            raise DomainError("session_expired", 401)
        row = found[0]
        return Identity(owner, row["id"], row["csrf_hash"], row["display_name"], row["email"])

    def sign_out(self, identity: Identity) -> None:
        with tenant(self.engine, identity.owner_id) as connection:
            connection.execute(
                text("UPDATE auth_sessions SET revoked_at=now() WHERE id=:id"),
                {"id": identity.session_id},
            )
