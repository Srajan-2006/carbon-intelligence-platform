import sys, os, random, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import seed_data
seed_data.seed()

import app as flask_app_module
import operational_data as od
from database import get_connection

app = flask_app_module.app
app.testing = True

_email_counter = [0]


def client():
    return app.test_client()


def unique_email(prefix):
    _email_counter[0] += 1
    return f"{prefix}-{int(time.time()*1000000)}-{_email_counter[0]}-{random.randint(1000,9999)}@example.com"


def unique_mine_id(prefix="DQ"):
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
    return c


VALID_PAYLOAD_BASE = {
    "coal_production_t": 90000, "diesel_consumption_l": 600000,
    "electricity_consumption_kwh": 1100000, "renewable_electricity_share": 6,
    "fugitive_methane_t": 2, "transport_activity_tkm": 300000, "commute_activity_pkm": 140000,
}


# ---------------------------------------------------------------------------
# Unit tests: pure gap-detection / mine-quality logic (no DB/API involved)
# ---------------------------------------------------------------------------

def test_no_gaps_for_consecutive_months():
    assert od._find_reporting_gaps(["2025-01", "2025-02", "2025-03"]) == []


def test_gap_detected_between_non_consecutive_months():
    gaps = od._find_reporting_gaps(["2025-01", "2025-02", "2025-04"])
    assert gaps == ["2025-03"]


def test_gap_detection_across_year_boundary():
    gaps = od._find_reporting_gaps(["2025-11", "2026-01"])
    assert gaps == ["2025-12"]


def test_single_period_has_no_gaps():
    assert od._find_reporting_gaps(["2025-06"]) == []


def test_empty_periods_has_no_gaps():
    assert od._find_reporting_gaps([]) == []


def test_mine_quality_incomplete_when_no_records():
    status, reasons = od.compute_mine_data_quality([])
    assert status == "INCOMPLETE"
    assert "No operational data" in reasons[0]


def test_mine_quality_warning_for_all_synthetic_but_complete_data():
    records = [
        {"period": f"2025-{m:02d}", "data_quality_status": "GOOD", "provenance": "synthetic_prototype"}
        for m in range(1, 13)
    ]
    status, reasons = od.compute_mine_data_quality(records)
    assert status == "WARNING"
    assert any("synthetic prototype" in r for r in reasons)


def test_mine_quality_incomplete_when_any_record_incomplete():
    records = [
        {"period": "2025-01", "data_quality_status": "GOOD", "provenance": "measured"},
        {"period": "2025-02", "data_quality_status": "INCOMPLETE", "provenance": "measured"},
    ]
    status, reasons = od.compute_mine_data_quality(records)
    assert status == "INCOMPLETE"
    assert any("missing required fields" in r for r in reasons)


def test_mine_quality_warning_for_gaps_with_measured_data():
    records = [
        {"period": "2025-01", "data_quality_status": "GOOD", "provenance": "measured"},
        {"period": "2025-03", "data_quality_status": "GOOD", "provenance": "measured"},
    ]
    status, reasons = od.compute_mine_data_quality(records)
    assert status == "WARNING"
    assert any("missing between" in r for r in reasons)


def test_mine_quality_good_for_complete_measured_no_gaps():
    records = [
        {"period": "2025-01", "data_quality_status": "GOOD", "provenance": "measured"},
        {"period": "2025-02", "data_quality_status": "GOOD", "provenance": "measured"},
    ]
    status, reasons = od.compute_mine_data_quality(records)
    assert status == "GOOD"
    assert reasons == []


def test_mine_quality_never_a_fabricated_percentage():
    records = [{"period": "2025-01", "data_quality_status": "GOOD", "provenance": "measured"}]
    status, reasons = od.compute_mine_data_quality(records)
    assert status in ("GOOD", "WARNING", "INCOMPLETE")
    assert "%" not in status
    for r in reasons:
        assert "%" not in r


# ---------------------------------------------------------------------------
# Integration: real seeded PM001/PM002/PM003 via the actual API
# ---------------------------------------------------------------------------

def test_pm001_shows_warning_all_synthetic_no_gaps():
    c = _register_and_login("ADMIN", None)
    mine = c.get("/api/mine/PM001").get_json()["mine"]
    assert mine["data_quality_status"] == "WARNING"
    assert any("synthetic prototype" in r for r in mine["data_quality_reasons"])
    assert mine["record_count"] == 12
    assert mine["coverage_start"] == "2025-01"
    assert mine["coverage_end"] == "2025-12"


def test_new_mine_with_no_data_is_incomplete():
    c = _register_and_login("ADMIN", None)
    mine_id = unique_mine_id()
    c.post("/api/mines", json={"mine_id": mine_id, "mine_name": "Quality Test Mine"})
    mine = c.get(f"/api/mine/{mine_id}").get_json()["mine"]
    assert mine["data_quality_status"] == "INCOMPLETE"
    assert mine["record_count"] == 0


def test_new_mine_with_gap_shows_warning_via_api():
    c = _register_and_login("ADMIN", None)
    mine_id = unique_mine_id()
    c.post("/api/mines", json={"mine_id": mine_id, "mine_name": "Gap Test Mine"})

    payload1 = dict(VALID_PAYLOAD_BASE); payload1["period"] = "2040-01"
    payload2 = dict(VALID_PAYLOAD_BASE); payload2["period"] = "2040-03"  # skips 2040-02
    r1 = c.post(f"/api/mine/{mine_id}/data", json=payload1)
    r2 = c.post(f"/api/mine/{mine_id}/data", json=payload2)
    assert r1.status_code == 201 and r2.status_code == 201

    mine = c.get(f"/api/mine/{mine_id}").get_json()["mine"]
    assert mine["data_quality_status"] == "WARNING"
    assert any("2040-02" in r for r in mine["data_quality_reasons"])


def test_mine_management_list_includes_quality_fields():
    c = _register_and_login("ADMIN", None)
    mines = c.get("/api/mine-management").get_json()["mines"]
    for m in mines:
        assert "data_quality_status" in m
        assert "data_quality_reasons" in m
        assert m["data_quality_status"] in ("GOOD", "WARNING", "INCOMPLETE")


def test_mine_manager_sees_own_mine_quality_only():
    c = _register_and_login("MINE_MANAGER", "PM002")
    mines = c.get("/api/mine-management").get_json()["mines"]
    assert len(mines) == 1
    assert mines[0]["mine_id"] == "PM002"
    assert "data_quality_status" in mines[0]


def test_cross_mine_quality_access_denied():
    c = _register_and_login("MINE_MANAGER", "PM001")
    r = c.get("/api/mine/PM002")
    assert r.status_code == 403


def test_existing_synthetic_mines_and_optimizer_unaffected():
    c = _register_and_login("ADMIN", None)
    baseline = c.get("/api/mine/PM001/baseline")
    assert baseline.status_code == 200
    b = baseline.get_json()["baseline_annual"]
    assert abs(b["scope1_tco2e"] - 22440) < 5
    opt = c.post("/api/optimize", json={"mine_id": "PM001", "budget_inr": 100_000_000, "target_reduction_pct": 30})
    assert opt.status_code == 200
    assert opt.get_json()["status"] == "TARGET_MET"


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
