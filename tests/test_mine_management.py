import sys, os, random, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import seed_data
seed_data.seed()

_email_counter = [0]

import app as flask_app_module
import auth
from database import get_connection

app = flask_app_module.app
app.testing = True


def client():
    return app.test_client()


def unique_email(prefix):
    # See tests/test_auth.py for rationale: combines a microsecond timestamp
    # + monotonic counter + random component, avoiding the narrow-random-range
    # collision risk observed against the intentionally-never-wiped users table.
    _email_counter[0] += 1
    return f"{prefix}-{int(time.time()*1000000)}-{_email_counter[0]}-{random.randint(1000,9999)}@example.com"


def unique_mine_id(prefix="ZZ"):
    return f"{prefix}{random.randint(1000,9999)}"


def _register_and_login(role, mine_id):
    email = unique_email(role.lower())
    registration_mine_id = mine_id if role != "ADMIN" else "PM001"
    reg = client().post("/api/auth/register", json={
        "name": f"{role} User", "email": email, "password": "password123",
        "confirm_password": "password123", "role": role if role != "ADMIN" else "ANALYST",
        "mine_id": registration_mine_id,
    })
    assert reg.status_code == 201, reg.get_json()
    if role == "ADMIN":
        conn = get_connection()
        conn.execute("UPDATE users SET role='ADMIN', mine_id=NULL WHERE email=?", (email.lower(),))
        conn.commit()
        conn.close()
    c = client()
    r = c.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.get_json()
    c._test_email = email
    return c


# ---------------------------------------------------------------------------
# Mine listing
# ---------------------------------------------------------------------------

def test_admin_sees_all_mines_in_management_view():
    c = _register_and_login("ADMIN", None)
    r = c.get("/api/mine-management")
    assert r.status_code == 200
    ids = {m["mine_id"] for m in r.get_json()["mines"]}
    assert {"PM001", "PM002", "PM003"}.issubset(ids)


def test_mine_manager_sees_only_own_mine():
    c = _register_and_login("MINE_MANAGER", "PM002")
    r = c.get("/api/mine-management")
    assert r.status_code == 200
    mines = r.get_json()["mines"]
    assert len(mines) == 1
    assert mines[0]["mine_id"] == "PM002"


def test_analyst_sees_only_own_mine_read_only_view():
    c = _register_and_login("ANALYST", "PM003")
    r = c.get("/api/mine-management")
    assert r.status_code == 200
    mines = r.get_json()["mines"]
    assert len(mines) == 1
    assert mines[0]["mine_id"] == "PM003"


def test_synthetic_demo_mines_labelled_correctly():
    c = _register_and_login("ADMIN", None)
    mines = c.get("/api/mine-management").get_json()["mines"]
    pm001 = next(m for m in mines if m["mine_id"] == "PM001")
    assert pm001["provenance"] == "synthetic_prototype"
    assert pm001["is_active"] is True
    assert pm001["data_status"] == "HAS_DATA"
    assert pm001["record_count"] == 12


# ---------------------------------------------------------------------------
# Mine creation
# ---------------------------------------------------------------------------

def test_admin_can_create_mine():
    c = _register_and_login("ADMIN", None)
    mine_id = unique_mine_id()
    r = c.post("/api/mines", json={
        "mine_id": mine_id, "mine_name": "New Test Mine", "state": "Odisha",
        "mine_type": "Opencast", "annual_production_t": 800000,
    })
    assert r.status_code == 201, r.get_json()
    body = r.get_json()["mine"]
    assert body["mine_id"] == mine_id.upper()
    assert body["is_active"] is True  # safe default
    assert body["provenance"] == "provisional"  # default, never synthetic_prototype for new mines
    assert body["created_by_name"] is not None
    assert body["data_status"] == "NO_DATA"


def test_created_by_and_created_at_recorded():
    c = _register_and_login("ADMIN", None)
    mine_id = unique_mine_id()
    r = c.post("/api/mines", json={"mine_id": mine_id, "mine_name": "Audit Check Mine"})
    body = r.get_json()["mine"]
    assert body["created_by_name"]  # resolved to the creating admin's name

    conn = get_connection()
    row = conn.execute("SELECT created_by, created_at FROM mine_master WHERE mine_id=?", (mine_id.upper(),)).fetchone()
    conn.close()
    assert row["created_by"] is not None
    assert row["created_at"] is not None


def test_duplicate_mine_code_rejected():
    c = _register_and_login("ADMIN", None)
    mine_id = unique_mine_id()
    r1 = c.post("/api/mines", json={"mine_id": mine_id, "mine_name": "First"})
    assert r1.status_code == 201
    r2 = c.post("/api/mines", json={"mine_id": mine_id, "mine_name": "Second (dup)"})
    assert r2.status_code == 409
    assert "already exists" in r2.get_json()["error"]


def test_duplicate_check_is_case_insensitive():
    c = _register_and_login("ADMIN", None)
    mine_id = unique_mine_id().lower()
    r1 = c.post("/api/mines", json={"mine_id": mine_id, "mine_name": "First"})
    assert r1.status_code == 201
    r2 = c.post("/api/mines", json={"mine_id": mine_id.upper(), "mine_name": "Second"})
    assert r2.status_code == 409


def test_create_mine_validation_rejects_bad_input():
    c = _register_and_login("ADMIN", None)
    # empty name
    r1 = c.post("/api/mines", json={"mine_id": unique_mine_id(), "mine_name": ""})
    assert r1.status_code == 400
    # invalid mine_id characters
    r2 = c.post("/api/mines", json={"mine_id": "bad id!!", "mine_name": "X"})
    assert r2.status_code == 400
    # negative production
    r3 = c.post("/api/mines", json={"mine_id": unique_mine_id(), "mine_name": "X", "annual_production_t": -500})
    assert r3.status_code == 400
    # non-numeric production
    r4 = c.post("/api/mines", json={"mine_id": unique_mine_id(), "mine_name": "X", "annual_production_t": "abc"})
    assert r4.status_code == 400
    # cannot create with synthetic_prototype provenance
    r5 = c.post("/api/mines", json={"mine_id": unique_mine_id(), "mine_name": "X", "provenance": "synthetic_prototype"})
    assert r5.status_code == 400


def test_mine_manager_cannot_create_mine():
    c = _register_and_login("MINE_MANAGER", "PM001")
    r = c.post("/api/mines", json={"mine_id": unique_mine_id(), "mine_name": "Should Fail"})
    assert r.status_code == 403


def test_analyst_cannot_create_mine():
    c = _register_and_login("ANALYST", "PM001")
    r = c.post("/api/mines", json={"mine_id": unique_mine_id(), "mine_name": "Should Fail"})
    assert r.status_code == 403


def test_unauthenticated_cannot_create_mine():
    r = client().post("/api/mines", json={"mine_id": unique_mine_id(), "mine_name": "Should Fail"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Mine editing
# ---------------------------------------------------------------------------

def test_admin_can_edit_any_mine():
    c = _register_and_login("ADMIN", None)
    r = c.put("/api/mine/PM003", json={"mine_name": "Ridgeway Opencast Mine (Updated)"})
    assert r.status_code == 200
    assert r.get_json()["mine"]["mine_name"] == "Ridgeway Opencast Mine (Updated)"
    # restore to avoid polluting other tests relying on the original name
    c.put("/api/mine/PM003", json={"mine_name": "Ridgeway Opencast Mine"})


def test_mine_manager_can_edit_own_mine_only():
    c = _register_and_login("MINE_MANAGER", "PM001")
    ok = c.put("/api/mine/PM001", json={"notes": "Manager-updated note"})
    assert ok.status_code == 200
    denied = c.put("/api/mine/PM002", json={"notes": "Should fail"})
    assert denied.status_code == 403


def test_analyst_cannot_edit():
    c = _register_and_login("ANALYST", "PM001")
    r = c.put("/api/mine/PM001", json={"notes": "Should fail"})
    assert r.status_code == 403


def test_edit_preserves_mine_id_identity():
    c = _register_and_login("ADMIN", None)
    mine_id = unique_mine_id()
    c.post("/api/mines", json={"mine_id": mine_id, "mine_name": "Identity Test"})
    r = c.put(f"/api/mine/{mine_id}", json={"mine_id": "SOMETHING_ELSE", "mine_name": "Renamed"})
    assert r.status_code == 200
    body = r.get_json()["mine"]
    assert body["mine_id"] == mine_id.upper()  # unchanged despite payload attempting to change it
    assert body["mine_name"] == "Renamed"


def test_edit_validates_fields():
    c = _register_and_login("ADMIN", None)
    mine_id = unique_mine_id()
    c.post("/api/mines", json={"mine_id": mine_id, "mine_name": "Validation Test"})
    r = c.put(f"/api/mine/{mine_id}", json={"annual_production_t": -100})
    assert r.status_code == 400


def test_edit_unknown_mine_returns_404():
    c = _register_and_login("ADMIN", None)
    r = c.put("/api/mine/DOES_NOT_EXIST", json={"mine_name": "X"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Deactivation (safe "delete" behavior)
# ---------------------------------------------------------------------------

def test_deactivation_hides_mine_from_public_selector_but_preserves_data():
    c = _register_and_login("ADMIN", None)
    mine_id = unique_mine_id()
    c.post("/api/mines", json={"mine_id": mine_id, "mine_name": "Deactivate Test"})

    r = c.put(f"/api/mine/{mine_id}", json={"is_active": False})
    assert r.status_code == 200
    assert r.get_json()["mine"]["is_active"] is False

    public = c.get("/api/mines").get_json()["mines"]
    assert mine_id.upper() not in [m["mine_id"] for m in public]

    # still fully present via management view -- not deleted
    mgmt = c.get("/api/mine-management").get_json()["mines"]
    assert mine_id.upper() in [m["mine_id"] for m in mgmt]


def test_reactivation_restores_visibility():
    c = _register_and_login("ADMIN", None)
    mine_id = unique_mine_id()
    c.post("/api/mines", json={"mine_id": mine_id, "mine_name": "Reactivate Test"})
    c.put(f"/api/mine/{mine_id}", json={"is_active": False})
    c.put(f"/api/mine/{mine_id}", json={"is_active": True})
    public = c.get("/api/mines").get_json()["mines"]
    assert mine_id.upper() in [m["mine_id"] for m in public]


def test_no_hard_delete_route_exists():
    """Per design: hard deletion is intentionally not implemented."""
    c = _register_and_login("ADMIN", None)
    r = c.delete("/api/mine/PM001")
    assert r.status_code in (404, 405)  # no DELETE route registered


# ---------------------------------------------------------------------------
# Regression: existing mines/data untouched by these features
# ---------------------------------------------------------------------------

def test_existing_synthetic_mines_and_data_preserved():
    c = _register_and_login("ADMIN", None)
    baseline = c.get("/api/mine/PM001/baseline")
    assert baseline.status_code == 200
    b = baseline.get_json()["baseline_annual"]
    assert abs(b["scope1_tco2e"] - 22440) < 5
    assert abs(b["scope2_tco2e"] - 10203) < 5


def test_optimizer_still_works_after_mine_management_changes():
    c = _register_and_login("ADMIN", None)
    r = c.post("/api/optimize", json={"mine_id": "PM001", "budget_inr": 100_000_000, "target_reduction_pct": 30})
    assert r.status_code == 200
    assert r.get_json()["status"] == "TARGET_MET"


# ---------------------------------------------------------------------------
# Phase 6D: single-mine detail endpoint (GET /api/mine/<id>)
# ---------------------------------------------------------------------------

def test_admin_can_get_mine_detail():
    c = _register_and_login("ADMIN", None)
    r = c.get("/api/mine/PM001")
    assert r.status_code == 200
    mine = r.get_json()["mine"]
    assert mine["mine_id"] == "PM001"
    assert mine["provenance"] == "synthetic_prototype"
    assert "assigned_users" in mine
    assert "record_count" in mine


def test_mine_manager_can_get_own_mine_detail():
    c = _register_and_login("MINE_MANAGER", "PM002")
    r = c.get("/api/mine/PM002")
    assert r.status_code == 200
    assert r.get_json()["mine"]["mine_id"] == "PM002"


def test_mine_manager_cannot_get_other_mine_detail():
    c = _register_and_login("MINE_MANAGER", "PM001")
    r = c.get("/api/mine/PM002")
    assert r.status_code == 403


def test_analyst_can_get_own_mine_detail_read_only():
    c = _register_and_login("ANALYST", "PM003")
    r = c.get("/api/mine/PM003")
    assert r.status_code == 200
    assert r.get_json()["mine"]["mine_id"] == "PM003"


def test_get_detail_unauthenticated_denied():
    r = client().get("/api/mine/PM001")
    assert r.status_code == 401


def test_get_detail_unknown_mine_returns_clean_404():
    c = _register_and_login("ADMIN", None)
    r = c.get("/api/mine/DOES_NOT_EXIST_XYZ")
    assert r.status_code == 404
    body = r.get_json()
    assert "error" in body
    assert "Traceback" not in str(body)


# ---------------------------------------------------------------------------
# Phase 6D: updated_at / updated_by auditability
# ---------------------------------------------------------------------------

def test_updated_at_and_updated_by_recorded_on_edit():
    c = _register_and_login("ADMIN", None)
    mine_id = unique_mine_id()
    c.post("/api/mines", json={"mine_id": mine_id, "mine_name": "Audit Edit Test"})

    before = c.get(f"/api/mine/{mine_id}").get_json()["mine"]
    assert before["updated_at"] is None
    assert before["updated_by_name"] is None

    r = c.put(f"/api/mine/{mine_id}", json={"notes": "edited note"})
    assert r.status_code == 200
    mine = r.get_json()["mine"]
    assert mine["updated_at"] is not None
    assert mine["updated_by_name"] is not None

    conn = get_connection()
    row = conn.execute("SELECT updated_by FROM mine_master WHERE mine_id=?", (mine_id.upper(),)).fetchone()
    conn.close()
    assert row["updated_by"] is not None


def test_created_at_still_recorded_unaffected_by_updated_fields():
    c = _register_and_login("ADMIN", None)
    mine_id = unique_mine_id()
    r = c.post("/api/mines", json={"mine_id": mine_id, "mine_name": "Created Audit Test"})
    mine = r.get_json()["mine"]
    assert mine["created_at"] is not None
    assert mine["created_by_name"] is not None


# ---------------------------------------------------------------------------
# Phase 6D: user/mine assignment visibility
# ---------------------------------------------------------------------------

def test_assigned_users_visible_on_mine_detail():
    email = unique_email("assignee")
    reg = client().post("/api/auth/register", json={
        "name": "Assigned Manager", "email": email, "password": "password123",
        "confirm_password": "password123", "role": "MINE_MANAGER", "mine_id": "PM001",
    })
    assert reg.status_code == 201

    c = _register_and_login("ADMIN", None)
    r = c.get("/api/mine/PM001")
    assigned = r.get_json()["mine"]["assigned_users"]
    assert any(u["name"] == "Assigned Manager" and u["role"] == "MINE_MANAGER" for u in assigned)


def test_assigned_users_does_not_leak_email():
    email = unique_email("privacycheck")
    client().post("/api/auth/register", json={
        "name": "Privacy Check User", "email": email, "password": "password123",
        "confirm_password": "password123", "role": "ANALYST", "mine_id": "PM002",
    })
    c = _register_and_login("ADMIN", None)
    r = c.get("/api/mine/PM002")
    assigned = r.get_json()["mine"]["assigned_users"]
    for u in assigned:
        assert "email" not in u


def test_unassigned_mine_shows_empty_assigned_users():
    c = _register_and_login("ADMIN", None)
    mine_id = unique_mine_id()
    c.post("/api/mines", json={"mine_id": mine_id, "mine_name": "No Assignment Test"})
    r = c.get(f"/api/mine/{mine_id}")
    assert r.get_json()["mine"]["assigned_users"] == []


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
