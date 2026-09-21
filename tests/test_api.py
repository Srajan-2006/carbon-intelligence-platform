import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# Ensure DB exists/fresh before importing app
import seed_data
seed_data.seed()

import app as flask_app_module
import auth
from database import get_connection

app = flask_app_module.app
app.testing = True

TEST_ADMIN_EMAIL = "test-admin@example.com"
TEST_ADMIN_PASSWORD = "test-admin-pw-123"


def _ensure_test_admin():
    """
    Creates a throwaway ADMIN account for exercising the now-protected data
    endpoints in this suite. This is a TEST FIXTURE ONLY (ephemeral,
    test-database-scoped credentials) -- not a real seeded demo account, and
    not committed application data. See tests/test_auth.py for the actual
    authentication/authorization test coverage.
    """
    conn = get_connection()
    existing = auth.get_user_by_email(conn, TEST_ADMIN_EMAIL)
    if existing is None:
        auth.register_user(
            conn, name="Test Admin", email=TEST_ADMIN_EMAIL,
            password=TEST_ADMIN_PASSWORD, confirm_password=TEST_ADMIN_PASSWORD,
            role="ADMIN", mine_id=None,
        )
    conn.close()


_ensure_test_admin()


def client():
    return app.test_client()


def admin_client():
    """A fresh test client, already logged in as the ADMIN test fixture."""
    c = app.test_client()
    r = c.post("/api/auth/login", json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD})
    assert r.status_code == 200, f"test admin login failed: {r.get_json()}"
    return c


def test_health():
    r = client().get("/api/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["database_connected"] is True


def test_pm001_baseline():
    r = admin_client().get("/api/mine/PM001/baseline")
    assert r.status_code == 200
    body = r.get_json()
    b = body["baseline_annual"]
    # Cross-check against the tested carbon engine's expected PM001 design values
    assert abs(b["scope1_tco2e"] - 22440) < 5, b["scope1_tco2e"]
    assert abs(b["scope2_tco2e"] - 10203) < 5, b["scope2_tco2e"]  # w/ 5% renewable applied
    assert abs(b["scope3_tco2e"] - 850) < 5, b["scope3_tco2e"]
    assert body["data_provenance"] == ["synthetic_prototype"]
    assert len(body["monthly_trend"]) == 12


def test_hotspots():
    r = admin_client().get("/api/mine/PM001/hotspots")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["hotspots"]) == 5
    # ranked descending
    values = [h["tco2e"] for h in body["hotspots"]]
    assert values == sorted(values, reverse=True)
    pcts = sum(h["pct_of_total"] for h in body["hotspots"])
    assert abs(pcts - 100.0) < 1.0


def test_interventions_endpoint():
    r = client().get("/api/interventions")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["interventions"]) == 7
    ev = next(i for i in body["interventions"] if i["intervention_id"] == "INT_EV_TRUCKS")
    assert ev["has_interaction"] == 1
    assert ev["provenance"] == "synthetic_prototype"


def test_optimize_default_demo_scenario():
    r = admin_client().post("/api/optimize", json={"mine_id": "PM001", "budget_inr": 100_000_000, "target_reduction_pct": 30})
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "TARGET_MET"
    assert body["achieved_reduction_pct"] >= 30.0
    assert body["recommended_investment_inr"] <= 100_000_000
    assert "run_id" in body
    ids = [s["intervention_id"] for s in body["selected_interventions"]]
    assert "INT_EV_TRUCKS" in ids


def test_optimize_infeasible_budget():
    r = admin_client().post("/api/optimize", json={"mine_id": "PM001", "budget_inr": 1000, "target_reduction_pct": 30})
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "TARGET_NOT_FEASIBLE_WITHIN_BUDGET"
    assert "gap_to_target_pct" in body
    assert body["achieved_reduction_pct"] < 30.0


def test_optimize_unrealistic_target():
    r = admin_client().post("/api/optimize", json={"mine_id": "PM001", "budget_inr": 1_000_000_000, "target_reduction_pct": 95})
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "TARGET_NOT_FEASIBLE_WITHIN_BUDGET"
    assert body["achieved_reduction_pct"] < 95


def test_optimize_invalid_mine_id():
    r = admin_client().post("/api/optimize", json={"mine_id": "NOT_A_MINE", "budget_inr": 1000000, "target_reduction_pct": 30})
    assert r.status_code == 404
    body = r.get_json()
    assert "error" in body
    assert "traceback" not in str(body).lower()


def test_optimize_invalid_budget():
    c = admin_client()
    r = c.post("/api/optimize", json={"mine_id": "PM001", "budget_inr": -500, "target_reduction_pct": 30})
    assert r.status_code == 400
    assert "error" in r.get_json()

    r2 = c.post("/api/optimize", json={"mine_id": "PM001", "budget_inr": "not-a-number", "target_reduction_pct": 30})
    assert r2.status_code == 400


def test_optimize_invalid_target():
    c = admin_client()
    r = c.post("/api/optimize", json={"mine_id": "PM001", "budget_inr": 1000000, "target_reduction_pct": 150})
    assert r.status_code == 400

    r2 = c.post("/api/optimize", json={"mine_id": "PM001", "budget_inr": 1000000, "target_reduction_pct": -5})
    assert r2.status_code == 400


def test_baseline_invalid_mine_returns_404_not_500():
    r = admin_client().get("/api/mine/ZZZZZ/baseline")
    assert r.status_code == 404
    assert "error" in r.get_json()


def test_roadmap_endpoint():
    r = admin_client().get("/api/mine/PM001/roadmap")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["roadmap"]) == 6
    years = [m["year"] for m in body["roadmap"]]
    assert years == sorted(years)


def test_simulate_endpoint_uses_same_logic_as_optimizer():
    """
    Simulating exactly the optimizer's chosen combination for the default
    demo scenario should reproduce the same investment/reduction numbers,
    proving simulate and optimize share the same underlying calculation.
    """
    c = admin_client()
    opt_r = c.post("/api/optimize", json={"mine_id": "PM001", "budget_inr": 100_000_000, "target_reduction_pct": 30})
    opt_body = opt_r.get_json()
    deployments = {s["intervention_id"]: s["deployment_level"] for s in opt_body["selected_interventions"]}

    sim_r = c.post("/api/simulate", json={"mine_id": "PM001", "deployments": deployments})
    assert sim_r.status_code == 200
    sim_body = sim_r.get_json()

    assert abs(sim_body["investment_inr"] - opt_body["recommended_investment_inr"]) < 1.0
    assert abs(sim_body["reduction_pct"] - opt_body["achieved_reduction_pct"]) < 0.1
    assert sim_body["mode"] == "SCENARIO_SIMULATION"
    assert "disclaimer" in sim_body


def test_simulate_invalid_intervention_id():
    r = admin_client().post("/api/simulate", json={"mine_id": "PM001", "deployments": {"FAKE_ID": 0.5}})
    assert r.status_code == 400


def test_mines_endpoint():
    r = client().get("/api/mines")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["mines"]) == 3
    ids = [m["mine_id"] for m in body["mines"]]
    assert "PM001" in ids


def test_protected_endpoints_reject_unauthenticated_requests():
    """
    Newly protected in Phase 5: mine-scoped data and optimizer/simulator
    endpoints must reject an unauthenticated request with 401, not silently
    serve data or 500.
    """
    c = client()
    assert c.get("/api/mine/PM001/baseline").status_code == 401
    assert c.get("/api/mine/PM001/hotspots").status_code == 401
    assert c.get("/api/mine/PM001/roadmap").status_code == 401
    assert c.get("/api/mine/PM001/calculation-sample").status_code == 401
    assert c.post("/api/optimize", json={"mine_id": "PM001", "budget_inr": 1000000, "target_reduction_pct": 30}).status_code == 401
    assert c.post("/api/simulate", json={"mine_id": "PM001", "deployments": {}}).status_code == 401


def test_public_endpoints_remain_accessible_unauthenticated():
    """Reference-data endpoints are intentionally public (not user-sensitive)."""
    c = client()
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/mines").status_code == 200
    assert c.get("/api/interventions").status_code == 200
    assert c.get("/api/emission-factors").status_code == 200


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
