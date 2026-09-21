"""
create_demo_users.py

DEVELOPMENT / DEMO SEED MECHANISM ONLY.

Creates a small set of demonstration accounts (one per role) for judges,
mentors, or developers to explore the platform without needing to register
manually. This is explicitly NOT a production user-provisioning mechanism.

Passwords are:
  - fixed, simple, memorable DEVELOPMENT/DEMO values (see DEMO_ACCOUNTS below) --
    intentionally NOT random, so anyone running this script gets predictable
    demo credentials without having to read terminal output from a prior run
  - still always stored as a salted hash via werkzeug's generate_password_hash()
    -- plaintext is never written to the database, only used transiently in
    memory to compute the hash, exactly as with any other account in this app
  - overridable via environment variables if you want different demo
    credentials for a specific presentation

These fixed passwords are intentionally simple and are NOT suitable for
anything beyond local development/demo use -- never reuse this mechanism or
these values for a real deployment.

Usage:
    # Fixed, documented demo passwords (admin123 / manager123 / analyst123):
    python backend/create_demo_users.py

    # Override with your own values instead:
    MCI_DEMO_ADMIN_PASSWORD=... MCI_DEMO_MANAGER_PASSWORD=... MCI_DEMO_ANALYST_PASSWORD=... \\
        python backend/create_demo_users.py

Safe to re-run: if a demo account's email already exists, its password is
reset to the current fixed/overridden demo value (role and mine assignment
are left unchanged) -- this script only ever touches these three documented
demo emails, never any other user's account, and never touches mine,
operational, or emissions data.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from database import get_connection
from seed_data import ensure_users_table
import auth
from werkzeug.security import generate_password_hash

DEMO_ACCOUNTS = [
    {"name": "Demo Administrator", "email": "admin@demo.mci.local", "role": "ADMIN", "mine_id": None,
     "default_password": "admin123", "env_var": "MCI_DEMO_ADMIN_PASSWORD"},
    {"name": "Demo Mine Manager (PM001)", "email": "manager@demo.mci.local", "role": "MINE_MANAGER", "mine_id": "PM001",
     "default_password": "manager123", "env_var": "MCI_DEMO_MANAGER_PASSWORD"},
    {"name": "Demo Analyst (PM001)", "email": "analyst@demo.mci.local", "role": "ANALYST", "mine_id": "PM001",
     "default_password": "analyst123", "env_var": "MCI_DEMO_ANALYST_PASSWORD"},
]


def create_demo_users():
    conn = get_connection()
    ensure_users_table(conn)

    created = []
    updated = []
    for account in DEMO_ACCOUNTS:
        password = os.environ.get(account["env_var"]) or account["default_password"]
        password_hash = generate_password_hash(password)

        existing = auth.get_user_by_email(conn, account["email"])
        if existing is not None:
            # Only ever resets the password for these three documented demo
            # emails -- role and mine_id are left exactly as configured
            # above (requirement: keep roles/mine assignments unchanged),
            # and no other table (mines, operations, emissions) is touched.
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (password_hash, existing["id"]),
            )
            conn.commit()
            updated.append((account, password))
            print(f"UPDATED {account['email']}  role={account['role']}  mine_id={account['mine_id']}  (password reset to demo default)")
            continue

        # ADMIN cannot be created via the public /api/auth/register endpoint
        # (see auth.py / app.py api_auth_register: role is restricted to
        # MINE_MANAGER/ANALYST there). This script inserts directly using the
        # same hashing utility, which is the documented, explicit way an
        # ADMIN account is meant to be provisioned for this prototype.
        conn.execute(
            """INSERT INTO users (name, email, password_hash, role, mine_id, is_active)
               VALUES (?,?,?,?,?,1)""",
            (account["name"], account["email"], password_hash,
             account["role"], account["mine_id"]),
        )
        conn.commit()
        created.append((account, password))
        print(f"CREATED {account['email']}  role={account['role']}  mine_id={account['mine_id']}")

    conn.close()

    all_accounts = created + updated
    if all_accounts:
        print("\n" + "=" * 60)
        print("DEVELOPMENT/DEMO CREDENTIALS ONLY -- fixed, memorable values.")
        print("Never reuse these for a real deployment.")
        print("=" * 60)
        for account, password in all_accounts:
            print(f"  {account['role']:14s} {account['email']:28s} password: {password}")
        print("=" * 60)
    else:
        print("\nNo accounts to create or update.")


if __name__ == "__main__":
    create_demo_users()
