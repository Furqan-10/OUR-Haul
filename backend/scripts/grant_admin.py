"""Grant or revoke platform administrator rights.

This is the **only** way `platform_role` is ever set. No API route, registration
path or OAuth response can produce an administrator, so the admin console
cannot be reached by privilege escalation -- it requires access to the server
and the database.

Usage (from backend/, with the venv active):

    python scripts/grant_admin.py --list
    python scripts/grant_admin.py --grant you@example.com
    python scripts/grant_admin.py --revoke someone@example.com
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tenancy import PLATFORM_ROLE_ADMIN, PLATFORM_ROLE_USER  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--grant", metavar="EMAIL", help="make this account a platform admin")
    group.add_argument("--revoke", metavar="EMAIL", help="remove platform admin rights")
    group.add_argument("--list", action="store_true", help="show current platform admins")
    args = parser.parse_args()

    mongo_url, db_name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("MONGO_URL and DB_NAME must be set (see backend/.env.example)")
        return 2
    db = AsyncIOMotorClient(mongo_url)[db_name]

    if args.list:
        admins = await db.users.find({"platform_role": PLATFORM_ROLE_ADMIN},
                                     {"_id": 0, "email": 1, "name": 1, "last_login_at": 1}).to_list(100)
        if not admins:
            print("No platform administrators.")
            print("Create one with:  python scripts/grant_admin.py --grant you@example.com")
            return 0
        print(f"Platform administrators ({len(admins)}):")
        for a in admins:
            print(f"  {a.get('email','?'):<40} {a.get('name','')}  last login: {a.get('last_login_at') or 'never'}")
        return 0

    email = (args.grant or args.revoke).lower().strip()
    user = await db.users.find_one({"email": email}, {"_id": 0, "user_id": 1, "name": 1})
    if not user:
        print(f"No account found for {email}.")
        print("The person must register in the app first; this only changes an existing account.")
        return 1

    if args.grant:
        await db.users.update_one({"email": email},
                                  {"$set": {"platform_role": PLATFORM_ROLE_ADMIN}})
        print(f"{email} is now a platform administrator.")
        print("They must sign out and back in for the change to take effect "
              "(the role is read at authentication).")
    else:
        # Revoking also invalidates live tokens, so rights are withdrawn at once
        # rather than lingering until the current session expires.
        await db.users.update_one({"email": email},
                                  {"$set": {"platform_role": PLATFORM_ROLE_USER},
                                   "$inc": {"token_version": 1}})
        await db.user_sessions.delete_many({"user_id": user["user_id"]})
        print(f"Platform administrator rights removed from {email}; sessions revoked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
