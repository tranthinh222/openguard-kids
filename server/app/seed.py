"""Explicit local provisioning; passwords are prompted and never logged."""
import argparse
import getpass
from sqlalchemy import select
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User
from app.core.encrypted import email_lookup
from app.services.auth_service import validate_password
from app.services.child_service import create_child


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", choices=["parent", "admin"], default="parent")
    parser.add_argument("--demo-child", action="store_true")
    args = parser.parse_args()
    if args.demo_child and (args.role != "parent" or settings.environment not in {"development", "test"}):
        parser.error("--demo-child is only for a development/test parent")
    password = getpass.getpass("Password (not displayed): ")
    validate_password(password)
    with SessionLocal() as db:
        lookup = email_lookup(args.email)
        if db.scalar(select(User).where(User.email_lookup_hash == lookup)):
            parser.error("Account already exists; no changes made")
        user = User(email=args.email.strip().lower(), email_lookup_hash=lookup,
                    password_hash=hash_password(password), role=args.role)
        db.add(user)
        db.commit()
        if args.demo_child:
            create_child(db, user.id, "Demo Child", None)
    print("Account created. No device has been enrolled.")


if __name__ == "__main__":
    main()
