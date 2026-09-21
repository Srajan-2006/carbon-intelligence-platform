"""
mine_management.py

Business logic for Phase 6 Mine Management: create/edit mines and list them
with role-appropriate scope and data status. Kept separate from app.py's
routing/auth-wiring concerns, matching the project's existing separation of
business logic from web plumbing (see carbon_engine.py, optimizer.py).

Nothing here duplicates carbon calculation logic -- data status is derived
from simple counts/aggregates over existing tables, not from re-deriving
emissions.
"""

import re

import operational_data as od

VALID_MINE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,20}$")
# Mines created through this UI are never allowed to claim 'synthetic_prototype'
# (reserved for the original seeded demo dataset) -- only 'reference' or
# 'provisional' identity data, consistent with the honesty requirements
# threaded through the whole platform.
ALLOWED_NEW_MINE_PROVENANCE = {"reference", "provisional"}


class ValidationError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _clean_str(value, max_len=200):
    if value is None:
        return None
    value = str(value).strip()
    return value[:max_len] if value else None


def _validate_mine_id(mine_id):
    if not mine_id or not VALID_MINE_ID_RE.match(mine_id):
        raise ValidationError(
            "Mine code must be 2-20 characters: letters, numbers, hyphens, or underscores only."
        )
    return mine_id.strip().upper()


def _validate_production(value):
    if value in (None, ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValidationError("Annual production must be a number.")
    if value < 0:
        raise ValidationError("Annual production cannot be negative.")
    if value > 1e9:
        raise ValidationError("Annual production value is unrealistically large.")
    return value


def _validate_provenance(value):
    value = (value or "provisional").strip().lower()
    if value not in ALLOWED_NEW_MINE_PROVENANCE:
        raise ValidationError(
            f"Provenance for a newly managed mine must be one of: {', '.join(sorted(ALLOWED_NEW_MINE_PROVENANCE))}."
        )
    return value


def create_mine(conn, payload, created_by_user_id):
    """
    Validates and inserts a new mine. Caller is responsible for the
    authorization check (auth.require_admin) before calling this.
    """
    mine_id = _validate_mine_id(payload.get("mine_id"))
    mine_name = _clean_str(payload.get("mine_name"))
    if not mine_name:
        raise ValidationError("Mine name is required.")

    company = _clean_str(payload.get("company"))
    state = _clean_str(payload.get("state"))
    mine_type = _clean_str(payload.get("mine_type"))
    notes = _clean_str(payload.get("notes"), max_len=2000)
    annual_production_t = _validate_production(payload.get("annual_production_t"))
    provenance = _validate_provenance(payload.get("provenance"))

    existing = conn.execute("SELECT mine_id FROM mine_master WHERE mine_id = ?", (mine_id,)).fetchone()
    if existing is not None:
        raise ValidationError(f"A mine with code '{mine_id}' already exists.", status_code=409)

    conn.execute(
        """INSERT INTO mine_master
           (mine_id, mine_name, company, state, mine_type, annual_production_t,
            provenance, notes, is_active, created_by, created_at)
           VALUES (?,?,?,?,?,?,?,?,1,?,datetime('now'))""",
        (mine_id, mine_name, company, state, mine_type, annual_production_t,
         provenance, notes, created_by_user_id),
    )
    conn.commit()
    return get_mine_detail(conn, mine_id)


def update_mine(conn, mine_id, payload, updated_by_user_id=None):
    """
    Validates and updates an existing mine. mine_id (the code/primary key)
    is never changed by this function, regardless of what the payload
    contains -- identity integrity is preserved by construction, not just by
    convention. Caller is responsible for the authorization check
    (auth.require_mine_write_access) before calling this.
    """
    existing = conn.execute("SELECT * FROM mine_master WHERE mine_id = ?", (mine_id,)).fetchone()
    if existing is None:
        raise ValidationError(f"Unknown mine_id '{mine_id}'.", status_code=404)

    mine_name = _clean_str(payload.get("mine_name")) or existing["mine_name"]
    if not mine_name:
        raise ValidationError("Mine name cannot be empty.")

    company = _clean_str(payload.get("company")) if "company" in payload else existing["company"]
    state = _clean_str(payload.get("state")) if "state" in payload else existing["state"]
    mine_type = _clean_str(payload.get("mine_type")) if "mine_type" in payload else existing["mine_type"]
    notes = _clean_str(payload.get("notes"), max_len=2000) if "notes" in payload else existing["notes"]

    annual_production_t = existing["annual_production_t"]
    if "annual_production_t" in payload:
        annual_production_t = _validate_production(payload.get("annual_production_t"))

    provenance = existing["provenance"]
    if "provenance" in payload and payload.get("provenance"):
        # Existing seeded demo mines keep 'synthetic_prototype' unless an
        # admin explicitly changes it; new-mine restrictions apply to any
        # value actually submitted for change.
        candidate = (payload.get("provenance") or "").strip().lower()
        if candidate != existing["provenance"]:
            provenance = _validate_provenance(candidate)

    is_active = existing["is_active"]
    if "is_active" in payload:
        is_active = 1 if payload.get("is_active") else 0

    conn.execute(
        """UPDATE mine_master
           SET mine_name = ?, company = ?, state = ?, mine_type = ?,
               annual_production_t = ?, provenance = ?, notes = ?, is_active = ?,
               updated_at = datetime('now'), updated_by = ?
           WHERE mine_id = ?""",
        (mine_name, company, state, mine_type, annual_production_t, provenance, notes, is_active,
         updated_by_user_id, mine_id),
    )
    conn.commit()
    return get_mine_detail(conn, mine_id)


def get_mine_detail(conn, mine_id):
    row = conn.execute("SELECT * FROM mine_master WHERE mine_id = ?", (mine_id,)).fetchone()
    if row is None:
        return None
    return _row_with_data_status(conn, row)


def _assigned_users(conn, mine_id):
    """
    Read-only visibility into which MINE_MANAGER/ANALYST accounts are
    assigned to this mine (requirement: expose user/mine assignment where
    the existing auth model already supports it, without restructuring
    authentication). Deliberately excludes email addresses here -- name and
    role are enough for this visibility need.
    """
    rows = conn.execute(
        "SELECT name, role FROM users WHERE mine_id = ? AND is_active = 1 ORDER BY role, name",
        (mine_id,),
    ).fetchall()
    return [{"name": r["name"], "role": r["role"]} for r in rows]


def _row_with_data_status(conn, row):
    mine = dict(row)
    records = od.list_records(conn, mine["mine_id"])  # reuses existing per-record quality logic, no duplication
    op_count = len(records)
    periods = [r["period"] for r in records]
    creator = None
    if mine.get("created_by"):
        creator_row = conn.execute("SELECT name FROM users WHERE id = ?", (mine["created_by"],)).fetchone()
        creator = creator_row["name"] if creator_row else None
    updater = None
    if mine.get("updated_by"):
        updater_row = conn.execute("SELECT name FROM users WHERE id = ?", (mine["updated_by"],)).fetchone()
        updater = updater_row["name"] if updater_row else None

    quality_status, quality_reasons = od.compute_mine_data_quality(records)

    mine["is_active"] = bool(mine["is_active"])
    mine["record_count"] = op_count
    mine["data_status"] = "HAS_DATA" if op_count > 0 else "NO_DATA"
    mine["coverage_start"] = min(periods) if periods else None
    mine["coverage_end"] = max(periods) if periods else None
    mine["created_by_name"] = creator
    mine["updated_by_name"] = updater
    mine["assigned_users"] = _assigned_users(conn, mine["mine_id"])
    mine["data_quality_status"] = quality_status
    mine["data_quality_reasons"] = quality_reasons
    return mine


def list_mines_for_management(conn, user_row):
    """
    ADMIN: every mine (active and inactive).
    MINE_MANAGER / ANALYST: only their own assigned mine, if any.
    """
    if user_row["role"] == "ADMIN":
        rows = conn.execute("SELECT * FROM mine_master ORDER BY mine_id").fetchall()
    elif user_row["mine_id"]:
        rows = conn.execute(
            "SELECT * FROM mine_master WHERE mine_id = ?", (user_row["mine_id"],)
        ).fetchall()
    else:
        rows = []
    return [_row_with_data_status(conn, r) for r in rows]
