"""Create the first operator account. There is no self-service registration."""
from __future__ import annotations

import argparse
import getpass
import sys

from app.repositories.user_repository import UserRepository
from app.services.auth_service import hash_password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", default="admin", choices=["admin", "operator"])
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args(argv)

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("password: ")
    if len(password) < 8:
        print("password must be at least 8 characters", file=sys.stderr)
        return 2

    from app.db.database import SessionLocal  # imported late so --help works without a DB

    with SessionLocal() as session:
        repo = UserRepository(session)
        if repo.by_username(args.username) is not None:
            print(f"user {args.username} already exists", file=sys.stderr)
            return 1
        repo.create(args.username, hash_password(password), args.role)
    print(f"created {args.role} {args.username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
