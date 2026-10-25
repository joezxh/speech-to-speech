"""Create the first operator account, or reset one password. No self-service registration."""
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
    parser.add_argument(
        "--update-password",
        action="store_true",
        help="reset the password of an existing user instead of failing",
    )
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
        existing = repo.by_username(args.username)
        if existing is not None:
            if not args.update_password:
                print(f"user {args.username} already exists", file=sys.stderr)
                return 1
            repo.update_password(existing, hash_password(password))
            print(f"updated the password of {existing.role} {args.username}")
            return 0
        repo.create(args.username, hash_password(password), args.role)
    print(f"created {args.role} {args.username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
