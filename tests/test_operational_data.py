import sys, os, random, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import seed_data
seed_data.seed()

_email_counter = [0]

import app as flask_app_module
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


_period_counter = [0]


def unique_period():
    """
    Guaranteed-unique (not just randomly unlikely to collide) period
    generator. The previous random.randint approach had only 240 possible
    year-month slots, which could collide across this file's ~30 record-
    creating tests -- a real flakiness bug, not an app bug. A monotonic
    counter mapped across a wide year range eliminates collisions entirely.
    """
    _period_counter[0] += 1
    year = 2030 + (_period_counter[0] // 12)
    month = (_period_counter[0] % 12) + 1
    return f"{year}-{month:02d}"


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
    "coal_production_t": 95000, "diesel_consumption_l": 620000,
    "electricity_consumption_kwh": 1150000, "renewable_electricity_share": 6,
    "fugitive_methane_t": 2.5, "transport_activity_tkm": 400000, "commute_activity_pkm": 160000,
}


def _valid_payload(period=None):
    payload = dict(VALID_PAYLOAD_BASE)
    payload["period"] = period if period is not None else unique_period()
    return payload


# ---------------------------------------------------------------------------
# Valid creation / editing
# ---------------------------------------------------------------------------

def test_manager_can_create_valid_record():
    c = _register_and_login("MINE_MANAGER", "PM001")
    payload = _valid_payload()
    r = c.post("/api/mine/PM001/data", json=payload)
    assert r.status_code == 201, r.get_json()
    rec = r.get_json()["record"]
    assert rec["period"] == payload["period"]
    assert rec["coal_production_t"] == payload["coal_production_t"]
    assert rec["renewable_electricity_share"] == 0.06  # percent -> fraction conversion
    assert rec["renewable_electricity_share_pct"] == 6.0


def test_admin_can_create_valid_record():
    c = _register_and_login("ADMIN", None)
    r = c.post("/api/mine/PM002/data", json=_valid_payload())
    assert r.status_code == 201


def test_record_editing():
    c = _register_and_login("MINE_MANAGER", "PM001")
    period = unique_period()
    r1 = c.post("/api/mine/PM001/data", json=_valid_payload(period))
    record_id = r1.get_json()["record"]["id"]

    r2 = c.put(f"/api/mine/PM001/data/{record_id}", json={"diesel_consumption_l": 700000})
    assert r2.status_code == 200
    rec = r2.get_json()["record"]
    assert rec["diesel_consumption_l"] == 700000
    assert rec["updated_at"] is not None
    # other fields preserved from original create (partial update)
    assert rec["coal_production_t"] == VALID_PAYLOAD_BASE["coal_production_t"]


# ---------------------------------------------------------------------------
# Duplicate month rejection
# ---------------------------------------------------------------------------

def test_duplicate_month_rejected():
    c = _register_and_login("MINE_MANAGER", "PM001")
    period = unique_period()
    r1 = c.post("/api/mine/PM001/data", json=_valid_payload(period))
    assert r1.status_code == 201
    r2 = c.post("/api/mine/PM001/data", json=_valid_payload(period))
    assert r2.status_code == 409
    assert "already exists" in r2.get_json()["error"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_missing_required_field_rejected():
    c = _register_and_login("MINE_MANAGER", "PM001")
    payload = _valid_payload()
    del payload["coal_production_t"]
    r = c.post("/api/mine/PM001/data", json=payload)
    assert r.status_code == 400
    assert "field_errors" in r.get_json()
    assert "coal_production_t" in r.get_json()["field_errors"]


def test_invalid_period_format_rejected():
    c = _register_and_login("MINE_MANAGER", "PM001")
    for bad_period in ("2025-13", "2025/01", "25-01", "not-a-period", ""):
        payload = _valid_payload(bad_period)
        r = c.post("/api/mine/PM001/data", json=payload)
        assert r.status_code == 400, f"expected 400 for period={bad_period!r}, got {r.status_code}"


def test_non_numeric_value_rejected():
    c = _register_and_login("MINE_MANAGER", "PM001")
    payload = _valid_payload()
    payload["diesel_consumption_l"] = "not-a-number"
    r = c.post("/api/mine/PM001/data", json=payload)
    assert r.status_code == 400


def test_negative_activity_rejected():
    c = _register_and_login("MINE_MANAGER", "PM001")
    for field in ("coal_production_t", "diesel_consumption_l", "electricity_consumption_kwh",
                  "fugitive_methane_t", "transport_activity_tkm", "commute_activity_pkm"):
        payload = _valid_payload()
        payload[field] = -1
        r = c.post("/api/mine/PM001/data", json=payload)
        assert r.status_code == 400, f"expected 400 for negative {field}"


def test_renewable_share_percentage_range_validated():
    c = _register_and_login("MINE_MANAGER", "PM001")
    over = _valid_payload()
    over["renewable_electricity_share"] = 150
    r1 = c.post("/api/mine/PM001/data", json=over)
    assert r1.status_code == 400

    under = _valid_payload()
    under["renewable_electricity_share"] = -10
    r2 = c.post("/api/mine/PM001/data", json=under)
    assert r2.status_code == 400

    boundary = _valid_payload()
    boundary["renewable_electricity_share"] = 100
    r3 = c.post("/api/mine/PM001/data", json=boundary)
    assert r3.status_code == 201


def test_optional_fields_can_be_omitted():
    c = _register_and_login("MINE_MANAGER", "PM001")
    payload = {
        "period": unique_period(), "coal_production_t": 1000, "diesel_consumption_l": 1000,
        "electricity_consumption_kwh": 1000, "renewable_electricity_share": 0,
    }
    r = c.post("/api/mine/PM001/data", json=payload)
    assert r.status_code == 201
    rec = r.get_json()["record"]
    assert rec["fugitive_methane_t"] is None
    assert rec["data_quality_status"] == "WARNING"  # missing optional fields -> WARNING, not INCOMPLETE


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

def test_analyst_read_only_cannot_create_or_edit():
    c = _register_and_login("ANALYST", "PM001")
    r = c.post("/api/mine/PM001/data", json=_valid_payload())
    assert r.status_code == 403

    # analyst CAN still read
    r2 = c.get("/api/mine/PM001/data")
    assert r2.status_code == 200


def test_unauthenticated_denied():
    r = client().post("/api/mine/PM001/data", json=_valid_payload())
    assert r.status_code == 401
    r2 = client().get("/api/mine/PM001/data")
    assert r2.status_code == 401


def test_cross_mine_write_denied():
    c = _register_and_login("MINE_MANAGER", "PM001")
    r = c.post("/api/mine/PM002/data", json=_valid_payload())
    assert r.status_code == 403


def test_cross_mine_read_denied():
    c = _register_and_login("ANALYST", "PM001")
    r = c.get("/api/mine/PM002/data")
    assert r.status_code == 403


def test_admin_has_full_write_access_any_mine():
    c = _register_and_login("ADMIN", None)
    for mine_id in ("PM001", "PM002", "PM003"):
        r = c.post(f"/api/mine/{mine_id}/data", json=_valid_payload())
        assert r.status_code == 201, f"admin should write to {mine_id}"


# ---------------------------------------------------------------------------
# Provenance / source metadata / audit fields
# ---------------------------------------------------------------------------

def test_default_provenance_is_measured_not_verified():
    c = _register_and_login("MINE_MANAGER", "PM001")
    payload = _valid_payload()
    del payload["renewable_electricity_share"]
    payload["renewable_electricity_share"] = 5
    r = c.post("/api/mine/PM001/data", json=payload)
    rec = r.get_json()["record"]
    assert rec["provenance"] == "measured"
    assert rec["provenance"] != "verified"  # never auto-labelled verified


def test_manual_entry_cannot_claim_synthetic_or_reference_or_verified():
    c = _register_and_login("MINE_MANAGER", "PM001")
    for bad_prov in ("synthetic_prototype", "reference", "verified"):
        payload = _valid_payload()
        payload["provenance"] = bad_prov
        r = c.post("/api/mine/PM001/data", json=payload)
        assert r.status_code == 400, f"expected rejection for provenance={bad_prov}"


def test_source_metadata_saved():
    c = _register_and_login("MINE_MANAGER", "PM001")
    payload = _valid_payload()
    payload["source_type"] = "sensor"
    payload["source_note"] = "SCADA export batch 44"
    r = c.post("/api/mine/PM001/data", json=payload)
    rec = r.get_json()["record"]
    assert rec["source_type"] == "sensor"
    assert rec["source_note"] == "SCADA export batch 44"


def test_created_by_and_updated_at_recorded():
    c = _register_and_login("MINE_MANAGER", "PM001")
    payload = _valid_payload()
    r = c.post("/api/mine/PM001/data", json=payload)
    rec = r.get_json()["record"]
    assert rec["created_by"] is not None
    assert rec["created_at"] is not None
    assert rec["updated_at"] is None  # not yet edited

    r2 = c.put(f"/api/mine/PM001/data/{rec['id']}", json={"diesel_consumption_l": 999999})
    assert r2.get_json()["record"]["updated_at"] is not None


# ---------------------------------------------------------------------------
# Data quality status
# ---------------------------------------------------------------------------

def test_data_quality_good_when_complete_and_measured():
    c = _register_and_login("MINE_MANAGER", "PM001")
    r = c.post("/api/mine/PM001/data", json=_valid_payload())
    rec = r.get_json()["record"]
    assert rec["data_quality_status"] == "GOOD"
    assert rec["data_quality_reasons"] == []


def test_data_quality_warning_when_provisional():
    c = _register_and_login("MINE_MANAGER", "PM001")
    payload = _valid_payload()
    payload["provenance"] = "provisional"
    r = c.post("/api/mine/PM001/data", json=payload)
    rec = r.get_json()["record"]
    assert rec["data_quality_status"] == "WARNING"
    assert any("provisional" in reason.lower() for reason in rec["data_quality_reasons"])


def test_data_quality_never_a_fake_percentage():
    c = _register_and_login("MINE_MANAGER", "PM001")
    r = c.post("/api/mine/PM001/data", json=_valid_payload())
    rec = r.get_json()["record"]
    assert rec["data_quality_status"] in ("GOOD", "WARNING", "INCOMPLETE")
    assert "data_quality_score" not in rec
    assert "%" not in str(rec["data_quality_status"])


# ---------------------------------------------------------------------------
# Calculation integration
# ---------------------------------------------------------------------------

def test_new_record_recalculates_emissions_via_carbon_engine():
    c = _register_and_login("MINE_MANAGER", "PM001")
    period = unique_period()
    c.post("/api/mine/PM001/data", json=_valid_payload(period))

    conn = get_connection()
    calc = conn.execute(
        "SELECT * FROM emission_calculations_monthly WHERE mine_id='PM001' AND period=?", (period,)
    ).fetchone()
    conn.close()
    assert calc is not None
    assert calc["scope1_tco2e"] > 0
    assert calc["scope2_tco2e"] > 0
    assert calc["provenance"] == "measured"


def test_dashboard_baseline_reflects_new_record():
    c = _register_and_login("MINE_MANAGER", "PM001")
    baseline_before = c.get("/api/mine/PM001/baseline").get_json()
    months_before = len(baseline_before["monthly_trend"])

    period = unique_period()
    c.post("/api/mine/PM001/data", json=_valid_payload(period))

    baseline_after = c.get("/api/mine/PM001/baseline").get_json()
    months_after = len(baseline_after["monthly_trend"])
    assert months_after == months_before + 1
    assert any(m["period"] == period for m in baseline_after["monthly_trend"])


def test_optimizer_still_works_with_extra_manual_record():
    c = _register_and_login("MINE_MANAGER", "PM001")
    c.post("/api/mine/PM001/data", json=_valid_payload())
    r = c.post("/api/optimize", json={"mine_id": "PM001", "budget_inr": 100_000_000, "target_reduction_pct": 30})
    assert r.status_code == 200
    assert r.get_json()["status"] in ("TARGET_MET", "TARGET_NOT_FEASIBLE_WITHIN_BUDGET")


def test_edit_recalculates_emissions():
    c = _register_and_login("MINE_MANAGER", "PM001")
    period = unique_period()
    r1 = c.post("/api/mine/PM001/data", json=_valid_payload(period))
    record_id = r1.get_json()["record"]["id"]

    conn = get_connection()
    before = conn.execute(
        "SELECT scope1_tco2e FROM emission_calculations_monthly WHERE mine_id='PM001' AND period=?", (period,)
    ).fetchone()["scope1_tco2e"]
    conn.close()

    c.put(f"/api/mine/PM001/data/{record_id}", json={"diesel_consumption_l": VALID_PAYLOAD_BASE["diesel_consumption_l"] * 3})

    conn = get_connection()
    after = conn.execute(
        "SELECT scope1_tco2e FROM emission_calculations_monthly WHERE mine_id='PM001' AND period=?", (period,)
    ).fetchone()["scope1_tco2e"]
    conn.close()
    assert after > before  # tripling diesel must increase Scope 1


# ---------------------------------------------------------------------------
# Historical data preservation
# ---------------------------------------------------------------------------

def test_original_synthetic_records_untouched():
    c = _register_and_login("ADMIN", None)
    c.post("/api/mine/PM001/data", json=_valid_payload())  # add a new record

    conn = get_connection()
    row = conn.execute(
        "SELECT diesel_consumption_l, provenance FROM operations_monthly WHERE mine_id='PM001' AND period='2025-01'"
    ).fetchone()
    conn.close()
    assert abs(row["diesel_consumption_l"] - 693272.0) < 0.5
    assert row["provenance"] == "synthetic_prototype"


def test_record_count_only_grows_not_replaces():
    conn = get_connection()
    before = conn.execute("SELECT COUNT(*) FROM operations_monthly WHERE mine_id='PM001'").fetchone()[0]
    conn.close()

    c = _register_and_login("MINE_MANAGER", "PM001")
    c.post("/api/mine/PM001/data", json=_valid_payload())

    conn = get_connection()
    after = conn.execute("SELECT COUNT(*) FROM operations_monthly WHERE mine_id='PM001'").fetchone()[0]
    conn.close()
    assert after == before + 1


# ---------------------------------------------------------------------------
# Phase 6E: unknown mine_id must return a clean 404, never a raw 500 or a
# silently-empty 200. Regression coverage for a real bug found during
# inspection: POST used to crash with an unhandled FOREIGN KEY
# IntegrityError (500), and GET silently returned an empty record list (200)
# instead of signalling the mine doesn't exist.
# ---------------------------------------------------------------------------

def test_get_unknown_mine_returns_clean_404_not_empty_200():
    c = _register_and_login("ADMIN", None)
    r = c.get("/api/mine/DOES_NOT_EXIST_999/data")
    assert r.status_code == 404
    body = r.get_json()
    assert "error" in body
    assert "Traceback" not in str(body)


def test_post_unknown_mine_returns_clean_404_not_500():
    c = _register_and_login("ADMIN", None)
    r = c.post("/api/mine/DOES_NOT_EXIST_999/data", json=_valid_payload())
    assert r.status_code == 404
    body = r.get_json()
    assert "error" in body
    assert "Traceback" not in str(body)
    assert "FOREIGN KEY" not in str(body)  # raw DB error must never leak to the client

    # and it must not have inserted an orphan row either
    conn = get_connection()
    orphan = conn.execute(
        "SELECT COUNT(*) FROM operations_monthly WHERE mine_id='DOES_NOT_EXIST_999'"
    ).fetchone()[0]
    conn.close()
    assert orphan == 0


def test_put_unknown_mine_returns_clean_404():
    c = _register_and_login("ADMIN", None)
    r = c.put("/api/mine/DOES_NOT_EXIST_999/data/1", json={"diesel_consumption_l": 500})
    assert r.status_code == 404
    assert "error" in r.get_json()


def test_valid_mine_get_and_post_unaffected_by_the_fix():
    """Guard against the fix accidentally breaking the normal, valid-mine path."""
    c = _register_and_login("MINE_MANAGER", "PM001")
    r_get = c.get("/api/mine/PM001/data")
    assert r_get.status_code == 200
    assert isinstance(r_get.get_json()["records"], list)

    r_post = c.post("/api/mine/PM001/data", json=_valid_payload())
    assert r_post.status_code == 201


# ---------------------------------------------------------------------------
# Phase 6E: calculation result surfaced on save (section 9 of the spec)
# ---------------------------------------------------------------------------

def test_create_response_includes_calculated_emissions():
    c = _register_and_login("MINE_MANAGER", "PM001")
    r = c.post("/api/mine/PM001/data", json=_valid_payload())
    calc = r.get_json()["record"]["calculation"]
    assert calc is not None
    assert calc["scope1_tco2e"] > 0
    assert calc["scope2_tco2e"] > 0
    assert calc["total_tco2e"] > 0
    assert "intensity_tco2e_per_t" in calc


def test_update_response_includes_recalculated_emissions():
    c = _register_and_login("MINE_MANAGER", "PM001")
    period = unique_period()
    r1 = c.post("/api/mine/PM001/data", json=_valid_payload(period))
    record_id = r1.get_json()["record"]["id"]
    before_calc = r1.get_json()["record"]["calculation"]

    r2 = c.put(f"/api/mine/PM001/data/{record_id}", json={"diesel_consumption_l": VALID_PAYLOAD_BASE["diesel_consumption_l"] * 2})
    after_calc = r2.get_json()["record"]["calculation"]
    assert after_calc is not None
    assert after_calc["scope1_tco2e"] > before_calc["scope1_tco2e"]


def test_hotspots_endpoint_survives_record_with_null_optional_fields():
    """
    Regression test: a record created without optional fields (fugitive
    methane, transport, commuting -- all left NULL) used to crash
    GET /api/mine/<id>/hotspots with a TypeError (float + NoneType) in its
    raw SQL aggregation. carbon_engine/recalc_period already handled NULLs
    correctly; this was a separate, unguarded aggregation in app.py.
    """
    c = _register_and_login("MINE_MANAGER", "PM001")
    period = unique_period()
    r = c.post("/api/mine/PM001/data", json={
        "period": period, "coal_production_t": 90000, "diesel_consumption_l": 600000,
        "electricity_consumption_kwh": 1100000, "renewable_electricity_share": 7,
        # fugitive_methane_t, transport_activity_tkm, commute_activity_pkm intentionally omitted -> NULL
    })
    assert r.status_code == 201
    assert r.get_json()["record"]["fugitive_methane_t"] is None

    hotspots = c.get("/api/mine/PM001/hotspots")
    assert hotspots.status_code == 200
    assert len(hotspots.get_json()["hotspots"]) == 5

    baseline = c.get("/api/mine/PM001/baseline")
    assert baseline.status_code == 200


# ---------------------------------------------------------------------------
# Phase 6H: auditability -- created_by/updated_by name resolution, and
# updated_by is actually tracked on edit (it previously wasn't -- only
# updated_at existed, so WHO last edited a record was never recorded).
# ---------------------------------------------------------------------------

def test_create_resolves_created_by_name_and_leaves_updated_fields_empty():
    c = _register_and_login("MINE_MANAGER", "PM001")
    r = c.post("/api/mine/PM001/data", json=_valid_payload())
    rec = r.get_json()["record"]
    assert rec["created_by_name"] is not None
    assert rec["updated_by_name"] is None
    assert rec["updated_at"] is None


def test_update_records_who_made_the_edit():
    c = _register_and_login("MINE_MANAGER", "PM001")
    period = unique_period()
    r1 = c.post("/api/mine/PM001/data", json=_valid_payload(period))
    record_id = r1.get_json()["record"]["id"]

    r2 = c.put(f"/api/mine/PM001/data/{record_id}", json={"diesel_consumption_l": 700000})
    rec = r2.get_json()["record"]
    assert rec["updated_by_name"] is not None
    assert rec["updated_at"] is not None

    conn = get_connection()
    row = conn.execute("SELECT updated_by FROM operations_monthly WHERE id=?", (record_id,)).fetchone()
    conn.close()
    assert row["updated_by"] is not None


def test_different_user_editing_updates_updated_by_to_the_new_editor():
    """Auditability must reflect the CURRENT editor, not always the original creator."""
    c1 = _register_and_login("ADMIN", None)
    period = unique_period()
    r1 = c1.post("/api/mine/PM001/data", json=_valid_payload(period))
    record_id = r1.get_json()["record"]["id"]
    creator_name = r1.get_json()["record"]["created_by_name"]

    c2 = _register_and_login("MINE_MANAGER", "PM001")
    r2 = c2.put(f"/api/mine/PM001/data/{record_id}", json={"diesel_consumption_l": 720000})
    rec = r2.get_json()["record"]
    assert rec["created_by_name"] == creator_name  # unchanged, reflects true original creator
    assert rec["updated_by_name"] != creator_name  # reflects the actual editor, not the creator
    assert rec["updated_by_name"] is not None


def test_original_synthetic_records_have_no_fabricated_audit_history():
    """The original seeded PM001/PM002/PM003 data must NOT be assigned a fake creator/editor."""
    c = _register_and_login("ADMIN", None)
    records = c.get("/api/mine/PM001/data").get_json()["records"]
    original = next(r for r in records if r["period"] == "2025-01")
    assert original["created_by_name"] is None
    assert original["updated_by_name"] is None
    assert original["provenance"] == "synthetic_prototype"


def test_csv_import_records_creator_but_no_fabricated_updater():
    c = _register_and_login("MINE_MANAGER", "PM001")
    import io
    period = unique_period()
    csv_text = (
        "period,coal_production_t,diesel_consumption_l,electricity_consumption_kwh,"
        "renewable_electricity_share_pct,fugitive_methane_t,transport_activity_tkm,"
        "commute_activity_pkm,provenance,source_note\n"
        f"{period},90000,600000,1100000,7,2,300000,140000,measured,csv audit test\n"
    )
    data = {"file": (io.BytesIO(csv_text.encode()), "audit.csv")}
    c.post("/api/mine/PM001/data/import/preview", data=data, content_type="multipart/form-data")
    data2 = {"file": (io.BytesIO(csv_text.encode()), "audit.csv")}
    c.post("/api/mine/PM001/data/import/confirm", data=data2, content_type="multipart/form-data")

    records = c.get("/api/mine/PM001/data").get_json()["records"]
    imported = next(r for r in records if r["period"] == period)
    assert imported["created_by_name"] is not None
    assert imported["updated_by_name"] is None  # never edited since import -- no fabricated editor


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
