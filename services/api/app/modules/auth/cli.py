"""Bootstrap command: create the first platform administrator.

    python -m app.modules.auth.cli create-platform-admin --email you@example.com --name "Your Name"

The password is prompted for, so it never appears in shell history or the process list.
"""

import argparse
import getpass
import sys

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

import app.main  # noqa: F401  # importing the app registers every module's models on Base
from app.core.db import get_engine
from app.core.errors import AppError
from app.modules.audit import service as audit
from app.modules.auth import service


def main() -> int:
    parser = argparse.ArgumentParser(description="Authentication administration.")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser(
        "create-platform-admin", help="Create a platform administrator account."
    )
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    args = parser.parse_args()

    try:
        email = TypeAdapter(EmailStr).validate_python(args.email)
    except ValidationError:
        print("Error: that is not a valid email address.", file=sys.stderr)
        return 1

    password = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != password:
        print("Error: the passwords do not match.", file=sys.stderr)
        return 1

    with Session(get_engine()) as session, session.begin():
        try:
            user = service.create_user(
                session,
                email=email,
                full_name=args.name,
                password=password,
                is_platform_admin=True,
            )
        except AppError as exc:
            detail = "; ".join(f"{d.field}: {d.message}" for d in exc.details)
            print(f"Error: {exc.message} {detail}".rstrip(), file=sys.stderr)
            return 1
        audit.record(
            session,
            "user.created",
            target_type="user",
            target_id=str(user.id),
            detail={"via": "cli", "is_platform_admin": True},
        )
        print(f"Created platform administrator {user.email}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
