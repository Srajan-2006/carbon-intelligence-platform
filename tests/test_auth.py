import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import seed_data
seed_data.seed()

import app as flask_app_module
import auth
from database import get_connection

_email_counter = [0]

app = flask_app_module.app
app.testing = True


def client():
    return app.test_client()


def unique_email(prefix):
    import random
    # Combines microsecond timestamp + a monotonic per-process counter + a
    # random component. random.randint(100000,999999) alone (900,000
    # possible values) has become a real, observed collision risk given the
    # users table is intentionally never wiped across the many accumulated
    # test runs in this environment (a duplicate-email 409 caused an
    # intermittent test failure). This combination is unique within a
    # process run by construction (the counter) and unique across separate
    # runs in practice (the timestamp), so it doesn't depend on random luck.
    _email_counter[0] += 1
    return f"{prefix}-{int(time.time()*1000000)}-{_email_counter[0]}-{random.randint(1000,9999)}@example.com"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration_success():
    email = unique_email("reg-success")
    r = client().post("/api/auth/register", json={
        "name": "Priya Sharma", "email": email, "password": "strongpass123",
        "confirm_password": "strongpass123", "role": "ANALYST", "mine_id": "PM001",
    })
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["user"]["email"] == email.lower()
    assert body["user"]["role"] == "ANALYST"
    assert body["user"]["mine_id"] == "PM001"
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]


def test_registration_password_is_hashed_not_plaintext():
    email = unique_email("hash-check")
    client().post("/api/auth/register", json={
        "name": "Hash Check", "email": email, "password": "supersecretpw1",
        "confirm_password": "supersecretpw1", "role": "ANALYST", "mine_id": "PM001",
    })
    conn = get_connection()
    row = auth.get_user_by_email(conn, email)
    conn.close()
    assert row["password_hash"] != "supersecretpw1"
    assert row["password_hash"].startswith("scrypt:") or row["password_hash"].startswith("pbkdf2:")


def test_duplicate_email_registration_rejected():
    email = unique_email("dup")
    payload = {
        "name": "Dup User", "email": email, "password": "password123",
        "confirm_password": "password123", "role": "ANALYST", "mine_id": "PM001",
    }
    r1 = client().post("/api/auth/register", json=payload)
    assert r1.status_code == 201
    r2 = client().post("/api/auth/register", json=payload)
    assert r2.status_code == 409
    assert "error" in r2.get_json()


def test_invalid_registration_rejected():
    c = client()
    # missing password confirmation match
    r = c.post("/api/auth/register", json={
        "name": "Bad Match", "email": unique_email("badmatch"), "password": "password123",
        "confirm_password": "different123", "role": "ANALYST", "mine_id": "PM001",
    })
    assert r.status_code == 400

    # password too short
    r2 = c.post("/api/auth/register", json={
        "name": "Short PW", "email": unique_email("shortpw"), "password": "short",
        "confirm_password": "short", "role": "ANALYST", "mine_id": "PM001",
    })
    assert r2.status_code == 400

    # invalid email
    r3 = c.post("/api/auth/register", json={
        "name": "Bad Email", "email": "not-an-email", "password": "password123",
        "confirm_password": "password123", "role": "ANALYST", "mine_id": "PM001",
    })
    assert r3.status_code == 400

    # non-admin role without mine
    r4 = c.post("/api/auth/register", json={
        "name": "No Mine", "email": unique_email("nomine"), "password": "password123",
        "confirm_password": "password123", "role": "ANALYST", "mine_id": "",
    })
    assert r4.status_code == 400


def test_registration_cannot_self_grant_admin_role():
    """
    SECURITY: the API silently downgrades any role outside the allowed
    self-registration set (MINE_MANAGER/ANALYST) to ANALYST -- a user cannot
    grant themselves ADMIN by editing the request body.
    """
    email = unique_email("wannabe-admin")
    r = client().post("/api/auth/register", json={
        "name": "Wannabe Admin", "email": email, "password": "password123",
        "confirm_password": "password123", "role": "ADMIN", "mine_id": "PM001",
    })
    assert r.status_code == 201
    body = r.get_json()
    assert body["user"]["role"] != "ADMIN"
    assert body["user"]["role"] == "ANALYST"


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

def test_login_success():
    email = unique_email("login-ok")
    client().post("/api/auth/register", json={
        "name": "Login OK", "email": email, "password": "password123",
        "confirm_password": "password123", "role": "ANALYST", "mine_id": "PM001",
    })
    r = client().post("/api/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200
    assert r.get_json()["user"]["email"] == email.lower()


def test_login_failure_wrong_password():
    email = unique_email("login-fail")
    client().post("/api/auth/register", json={
        "name": "Login Fail", "email": email, "password": "password123",
        "confirm_password": "password123", "role": "ANALYST", "mine_id": "PM001",
    })
    r = client().post("/api/auth/login", json={"email": email, "password": "wrongpassword"})
    assert r.status_code == 401
    assert "error" in r.get_json()


def test_login_failure_unknown_email():
    r = client().post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
    assert r.status_code == 401


def test_logout_clears_session():
    email = unique_email("logout")
    client().post("/api/auth/register", json={
        "name": "Logout Test", "email": email, "password": "password123",
        "confirm_password": "password123", "role": "ANALYST", "mine_id": "PM001",
    })
    c = client()
    c.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert c.get("/api/auth/me").get_json()["user"] is not None

    r = c.post("/api/auth/logout")
    assert r.status_code == 200
    assert c.get("/api/auth/me").get_json()["user"] is None


def test_inactive_user_cannot_log_in():
    email = unique_email("inactive")
    client().post("/api/auth/register", json={
        "name": "Inactive User", "email": email, "password": "password123",
        "confirm_password": "password123", "role": "ANALYST", "mine_id": "PM001",
    })
    conn = get_connection()
    conn.execute("UPDATE users SET is_active = 0 WHERE email = ?", (email.lower(),))
    conn.commit()
    conn.close()

    r = client().post("/api/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 403


def test_auth_me_unauthenticated_returns_null_user():
    r = client().get("/api/auth/me")
    assert r.status_code == 200
    assert r.get_json()["user"] is None


# ---------------------------------------------------------------------------
# Protected pages
# ---------------------------------------------------------------------------

def test_protected_page_without_login_redirects():
    r = client().get("/", follow_redirects=False)
    assert r.status_code in (301, 302)
    assert "/login" in r.headers.get("Location", "")


def test_protected_page_with_login_succeeds():
    email = unique_email("page-access")
    client().post("/api/auth/register", json={
        "name": "Page Access", "email": email, "password": "password123",
        "confirm_password": "password123", "role": "ANALYST", "mine_id": "PM001",
    })
    c = client()
    c.post("/api/auth/login", json={"email": email, "password": "password123"})
    r = c.get("/")
    assert r.status_code == 200


def test_login_and_register_pages_public():
    c = client()
    assert c.get("/login").status_code == 200
    assert c.get("/register").status_code == 200


# ---------------------------------------------------------------------------
# Authorization: role + mine scoping
# ---------------------------------------------------------------------------

def _register_and_login(role, mine_id):
    email = unique_email(role.lower())
    # Self-registration always requires a mine_id for non-ADMIN roles (ADMIN
    # itself isn't self-registrable -- see test_registration_cannot_self_grant_admin_role).
    # For the ADMIN test case we register as ANALYST with a placeholder mine
    # first, then promote to ADMIN (and clear mine_id) directly in the DB,
    # simulating the documented dev-seed mechanism.
    registration_mine_id = mine_id if role != "ADMIN" else "PM001"
    reg = client().post("/api/auth/register", json={
        "name": f"{role} User", "email": email, "password": "password123",
        "confirm_password": "password123", "role": role if role != "ADMIN" else "ANALYST",
        "mine_id": registration_mine_id,
    })
    assert reg.status_code == 201, f"registration failed: {reg.get_json()}"
    if role == "ADMIN":
        conn = get_connection()
        conn.execute("UPDATE users SET role='ADMIN', mine_id=NULL WHERE email=?", (email.lower(),))
        conn.commit()
        conn.close()
    c = client()
    r = c.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200, f"login failed: {r.get_json()}"
    return c


def test_admin_can_access_all_mines():
    c = _register_and_login("ADMIN", None)
    for mine_id in ("PM001", "PM002", "PM003"):
        r = c.get(f"/api/mine/{mine_id}/baseline")
        assert r.status_code == 200, f"admin should access {mine_id}: {r.get_json()}"


def test_mine_manager_restricted_to_assigned_mine():
    c = _register_and_login("MINE_MANAGER", "PM001")
    assert c.get("/api/mine/PM001/baseline").status_code == 200
    assert c.get("/api/mine/PM002/baseline").status_code == 403
    assert c.get("/api/mine/PM003/baseline").status_code == 403


def test_analyst_restricted_to_assigned_mine():
    c = _register_and_login("ANALYST", "PM002")
    assert c.get("/api/mine/PM002/baseline").status_code == 200
    assert c.get("/api/mine/PM001/baseline").status_code == 403


def test_unauthorized_mine_access_denied_not_leaked():
    """A restricted user changing the mine_id in the URL must not receive data."""
    c = _register_and_login("ANALYST", "PM001")
    r = c.get("/api/mine/PM002/baseline")
    assert r.status_code == 403
    body = r.get_json()
    assert "error" in body
    assert "scope1_tco2e" not in str(body)  # no PM002 data leaked in the error body


def test_optimizer_mine_authorization():
    c = _register_and_login("ANALYST", "PM001")
    ok = c.post("/api/optimize", json={"mine_id": "PM001", "budget_inr": 100000000, "target_reduction_pct": 30})
    assert ok.status_code == 200
    denied = c.post("/api/optimize", json={"mine_id": "PM002", "budget_inr": 100000000, "target_reduction_pct": 30})
    assert denied.status_code == 403


def test_simulator_mine_authorization():
    c = _register_and_login("ANALYST", "PM001")
    ok = c.post("/api/simulate", json={"mine_id": "PM001", "deployments": {}})
    assert ok.status_code == 200
    denied = c.post("/api/simulate", json={"mine_id": "PM002", "deployments": {}})
    assert denied.status_code == 403


# ---------------------------------------------------------------------------
# Database safety: reseeding must not destroy users
# ---------------------------------------------------------------------------

def test_reseeding_does_not_delete_users():
    email = unique_email("survives-reseed")
    client().post("/api/auth/register", json={
        "name": "Survivor", "email": email, "password": "password123",
        "confirm_password": "password123", "role": "ANALYST", "mine_id": "PM001",
    })
    conn = get_connection()
    before = auth.get_user_by_email(conn, email)
    assert before is not None
    conn.close()

    seed_data.seed()  # reseed emissions/intervention data

    conn = get_connection()
    after = auth.get_user_by_email(conn, email)
    conn.close()
    assert after is not None
    assert after["id"] == before["id"]


def test_reseeding_still_rebuilds_emissions_data_correctly():
    seed_data.seed()
    conn = get_connection()
    mine_count = conn.execute("SELECT COUNT(*) FROM mine_master").fetchone()[0]
    calc_count = conn.execute("SELECT COUNT(*) FROM emission_calculations_monthly").fetchone()[0]
    conn.close()
    assert mine_count == 3
    assert calc_count == 36


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
