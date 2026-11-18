"""Operator command: provision, disable and list GitHub accounts allowed to sign in.

    python -m repovox.auth.accounts add --github-id 123 --name "Ada" --email ada@example.com
    python -m repovox.auth.accounts disable --github-id 123
    python -m repovox.auth.accounts list

It runs with the migration role (`REPOVOX_MIGRATION_DATABASE_URL`, set on the `migrate`
service) and acts as `rv_executor`, the same way the development identities are seeded. The
API's own role cannot create, change or list users; nothing here is reachable over HTTP.
A GitHub account is identified by its numeric id (https://api.github.com/users/<login>
shows it), never by its login, which its owner can change.
"""

import argparse
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text

from repovox.auth.github import ISSUER, owner_for

EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,189}")


@contextmanager
def executor(engine: Engine) -> Iterator[Connection]:
    """A transaction acting as rv_executor; the migration role is NOINHERIT."""
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL ROLE rv_executor"))
        yield connection


def provision(engine: Engine, github_id: int, name: str, email: str) -> UUID:
    """Create or reactivate one account and its quota. A deleted account stays deleted."""
    name, email = name.strip(), email.strip()
    if not 1 <= len(name) <= 200:
        raise ValueError("A display name of 1 to 200 characters is required")
    if not EMAIL.fullmatch(email):
        raise ValueError("A valid email address is required")
    owner = owner_for(github_id)
    with executor(engine) as connection:
        stored = connection.execute(
            text(
                "INSERT INTO users(id,owner_id,issuer,auth_subject,display_name,email) "
                "VALUES(:owner,:owner,:issuer,:subject,:name,:email) "
                "ON CONFLICT (issuer,auth_subject) DO UPDATE SET "
                "display_name=EXCLUDED.display_name,email=EXCLUDED.email,status='active' "
                "WHERE users.deleted_at IS NULL "
                "RETURNING id"
            ),
            {
                "owner": owner,
                "issuer": ISSUER,
                "subject": str(github_id),
                "name": name,
                "email": email,
            },
        ).scalar()
        if stored is None:
            raise ValueError("This account was deleted and cannot be provisioned again")
        connection.execute(
            text("INSERT INTO quota_accounts(owner_id) VALUES(:owner) ON CONFLICT DO NOTHING"),
            {"owner": owner},
        )
    return owner


def disable(engine: Engine, github_id: int) -> bool:
    """Stop an account signing in and end its open sessions. Its data is kept."""
    owner = owner_for(github_id)
    with executor(engine) as connection:
        changed = connection.execute(
            text(
                "UPDATE users SET status='disabled' "
                "WHERE id=:owner AND issuer=:issuer AND auth_subject=:subject"
            ),
            {"owner": owner, "issuer": ISSUER, "subject": str(github_id)},
        ).rowcount
        connection.execute(
            text(
                "UPDATE auth_sessions SET revoked_at=now() "
                "WHERE owner_id=:owner AND revoked_at IS NULL"
            ),
            {"owner": owner},
        )
    return bool(changed)


def listing(engine: Engine) -> list[dict[str, Any]]:
    with executor(engine) as connection:
        return [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT auth_subject AS github_id,display_name,email,status FROM users "
                    "WHERE issuer=:issuer AND deleted_at IS NULL ORDER BY display_name"
                ),
                {"issuer": ISSUER},
            ).mappings()
        ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m repovox.auth.accounts")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="provision or reactivate a GitHub account")
    add.add_argument("--github-id", type=int, required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--email", required=True)
    off = commands.add_parser("disable", help="stop an account signing in")
    off.add_argument("--github-id", type=int, required=True)
    commands.add_parser("list", help="list provisioned GitHub accounts")
    args = parser.parse_args(argv)
    url = os.environ.get("REPOVOX_MIGRATION_DATABASE_URL")
    if not url:
        print("REPOVOX_MIGRATION_DATABASE_URL is not set; run this on the migrate service.")
        return 2
    engine = create_engine(url)
    try:
        if args.command == "add":
            owner = provision(engine, args.github_id, args.name, args.email)
            print(f"GitHub account {args.github_id} may sign in (owner {owner}).")
        elif args.command == "disable":
            found = disable(engine, args.github_id)
            print(
                f"GitHub account {args.github_id} disabled; its sessions are revoked."
                if found
                else f"No GitHub account {args.github_id} is provisioned."
            )
        else:
            for row in listing(engine):
                print(f"{row['github_id']}\t{row['status']}\t{row['display_name']}\t{row['email']}")
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
