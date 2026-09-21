"""
auth.py

Authentication and authorization logic for the Mine Carbon Intelligence
platform. Session-based (Flask's signed-cookie session), Werkzeug password
hashing, and a small mine-scoping layer -- kept intentionally minimal per
the "do not over-engineer authorization" instruction.

ARCHITECTURE RULE (same as app.py): this module owns auth business logic.
Routes in app.py call into this module rather than reimplementing checks.
"""

import re
import functools

from flask import session, jsonify, redirect, url_for, request, g
from werkzeug.security import generate_password_hash, check_password_hash

VALID_ROLES = {"ADMIN", "MINE_MANAGER", "ANALYST"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# User data access
# ---------------------------------------------------------------------------

def _row_to_public_user(row):
    """Never include password_hash in anything returned toward the client."""
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
        "mine_id": row["mine_id"],
        "is_active": bool(row["is_active"]),
    }


def get_user_by_email(conn, email):
    return conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()


def get_user_by_id(conn, user_id):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


class AuthError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def register_user(conn, name, email, password, confirm_password, role, mine_id):
    name = (name or "").strip()
    email = (email or "").strip().lower()

    if not name:
        raise AuthError("Name is required.")
    if not email or not EMAIL_RE.match(email):
        raise AuthError("A valid email address is required.")
    if not password or len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    if password != confirm_password:
        raise AuthError("Passwords do not match.")
    if role not in VALID_ROLES:
        raise AuthError("Invalid role.")
    if role != "ADMIN" and not mine_id:
        raise AuthError("Mine selection is required for this role.")

    if get_user_by_email(conn, email) is not None:
        raise AuthError("An account with this email already exists.", status_code=409)

    if mine_id:
        mine = conn.execute("SELECT mine_id FROM mine_master WHERE mine_id = ?", (mine_id,)).fetchone()
        if mine is None:
            raise AuthError(f"Unknown mine_id '{mine_id}'.")

    password_hash = generate_password_hash(password)
    cur = conn.execute(
        """INSERT INTO users (name, email, password_hash, role, mine_id, is_active)
           VALUES (?,?,?,?,?,1)""",
        (name, email, password_hash, role, mine_id if role != "ADMIN" else None),
    )
    conn.commit()
    return _row_to_public_user(get_user_by_id(conn, cur.lastrowid))


def authenticate(conn, email, password):
    email = (email or "").strip().lower()
    user = get_user_by_email(conn, email)
    if user is None or not check_password_hash(user["password_hash"], password or ""):
        raise AuthError("Invalid email or password.", status_code=401)
    if not user["is_active"]:
        raise AuthError("This account has been deactivated.", status_code=403)
    return user


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def log_in_user(user_row):
    session.clear()
    session["user_id"] = user_row["id"]
    session.permanent = True


def log_out_user():
    session.clear()


def current_user(conn):
    """Returns the full DB row (not the public dict) for the session user, or None."""
    user_id = session.get("user_id")
    if user_id is None:
        return None
    user = get_user_by_id(conn, user_id)
    if user is None or not user["is_active"]:
        session.clear()
        return None
    return user


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def login_required_page(view_func):
    """For server-rendered page routes: redirects to /login if not authenticated."""
    @functools.wraps(view_func)
    def wrapped(*args, **kwargs):
        from database import get_connection
        conn = get_connection()
        user = current_user(conn)
        conn.close()
        if user is None:
            return redirect(url_for("page_login", next=request.path))
        g.user = user
        return view_func(*args, **kwargs)
    return wrapped


def login_required_api(view_func):
    """For JSON API routes: returns 401 JSON instead of redirecting."""
    @functools.wraps(view_func)
    def wrapped(*args, **kwargs):
        from database import get_connection
        conn = get_connection()
        user = current_user(conn)
        conn.close()
        if user is None:
            return jsonify({"error": "Authentication required."}), 401
        g.user = user
        return view_func(*args, **kwargs)
    return wrapped


def mine_scope_allowed(user_row, mine_id):
    """
    ADMIN: access to any mine.
    MINE_MANAGER / ANALYST: access only to their own assigned mine.
    """
    if user_row["role"] == "ADMIN":
        return True
    return user_row["mine_id"] == mine_id


def require_mine_access(user_row, mine_id):
    """
    Centralized mine-scoping check, called explicitly at the top of any route
    that takes a mine_id (from URL path or JSON body). Raises AuthError(403)
    rather than letting a MINE_MANAGER/ANALYST access another mine's data by
    editing the mine_id in a URL or request body -- this is the single place
    that logic lives, so it isn't duplicated per-route.
    """
    if not mine_scope_allowed(user_row, mine_id):
        raise AuthError(
            f"Your account is not authorized to access mine '{mine_id}'.",
            status_code=403,
        )


def require_admin(user_row):
    """Phase 6: mine creation and cross-mine management are ADMIN-only."""
    if user_row["role"] != "ADMIN":
        raise AuthError("This action requires administrator privileges.", status_code=403)


def require_mine_write_access(user_row, mine_id):
    """
    Phase 6: write access (create/update/delete operational data, CSV import)
    to a mine's data is allowed for ADMIN (any mine) or MINE_MANAGER (their
    own assigned mine only). ANALYST remains read/analyze-only, per the
    project's role design -- never granted write access here.
    """
    require_mine_access(user_row, mine_id)  # read access is a prerequisite
    if user_row["role"] == "ADMIN":
        return
    if user_row["role"] == "MINE_MANAGER" and user_row["mine_id"] == mine_id:
        return
    raise AuthError(
        "Your account does not have write access to this mine's data. "
        "Only administrators and the assigned mine manager can add or edit records.",
        status_code=403,
    )
