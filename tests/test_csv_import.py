import sys, os, random, io, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import seed_data
seed_data.seed()

_email_counter = [0]

import app as flask_app_module
from database import get_connection

app = flask_app_module.app
app.testing = True

_period_counter = [1000]


def unique_period():
    _period_counter[0] += 1
    year = 2050 + (_period_counter[0] // 12)
    month = (_period_counter[0] % 12) + 1
    return f"{year}-{month:02d}"


def client():
    return app.test_client()


def unique_email(prefix):
    # See tests/test_auth.py for rationale: combines a microsecond timestamp
    # + monotonic counter + random component, avoiding the narrow-random-range
    # collision risk observed against the intentionally-never-wiped users table.
    _email_counter[0] += 1
    return f"{prefix}-{int(time.time()*1000000)}-{_email_counter[0]}-{random.randint(1000,9999)}@example.com"


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


def csv_bytes(rows, header=None):
    header = header or ["period", "coal_production_t", "diesel_consumption_l", "electricity_consumption_kwh",
                         "renewable_electricity_share_pct", "fugitive_methane_t", "transport_activity_tkm",
                         "commute_activity_pkm", "provenance", "source_note"]
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(str(v) if v is not None else "" for v in row))
    return ("\n".join(lines) + "\n").encode()


def valid_row(period=None, **overrides):
    row = {
        "period": period or unique_period(), "coal_production_t": 90000, "diesel_consumption_l": 600000,
        "electricity_consumption_kwh": 1100000, "renewable_electricity_share_pct": 7,
        "fugitive_methane_t": 2, "transport_activity_tkm": 300000, "commute_activity_pkm": 140000,
        "provenance": "measured", "source_note": "test",
    }
    row.update(overrides)
    return [row["period"], row["coal_production_t"], row["diesel_consumption_l"], row["electricity_consumption_kwh"],
            row["renewable_electricity_share_pct"], row["fugitive_methane_t"], row["transport_activity_tkm"],
            row["commute_activity_pkm"], row["provenance"], row["source_note"]]


def upload(c, mine_id, mode, content, filename="data.csv"):
    return c.post(
        f"/api/mine/{mine_id}/data/import/{mode}",
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

def test_template_download():
    c = _register_and_login("ADMIN", None)
    r = c.get("/api/mine/PM001/data/template")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/csv")
    text = r.get_data(as_text=True)
    assert "period" in text
    assert "coal_production_t" in text
    assert "renewable_electricity_share_pct" in text
    assert "EXAMPLE ROW" in text  # clearly labelled as example, not real data


# ---------------------------------------------------------------------------
# Valid CSV / preview / confirm
# ---------------------------------------------------------------------------

def test_valid_csv_preview_and_confirm():
    c = _register_and_login("MINE_MANAGER", "PM001")
    content = csv_bytes([valid_row(), valid_row()])

    preview = upload(c, "PM001", "preview", content)
    assert preview.status_code == 200
    body = preview.get_json()
    assert body["total_rows"] == 2
    assert body["valid_rows"] == 2
    assert body["invalid_rows"] == 0
    assert body["can_import"] is True

    confirm = upload(c, "PM001", "confirm", content)
    assert confirm.status_code == 200
    result = confirm.get_json()
    assert result["rows_imported"] == 2
    assert result["calculations_updated"] == 2


def test_preview_never_writes_to_database():
    c = _register_and_login("MINE_MANAGER", "PM001")
    conn = get_connection()
    before = conn.execute("SELECT COUNT(*) FROM operations_monthly WHERE mine_id='PM001'").fetchone()[0]
    conn.close()

    content = csv_bytes([valid_row()])
    upload(c, "PM001", "preview", content)

    conn = get_connection()
    after = conn.execute("SELECT COUNT(*) FROM operations_monthly WHERE mine_id='PM001'").fetchone()[0]
    conn.close()
    assert after == before


# ---------------------------------------------------------------------------
# File-level validation
# ---------------------------------------------------------------------------

def test_missing_headers_rejected():
    c = _register_and_login("MINE_MANAGER", "PM001")
    content = b"period,coal_production_t\n2060-01,1000\n"
    r = upload(c, "PM001", "preview", content)
    assert r.status_code == 400
    assert "Missing required column" in r.get_json()["error"]


def test_malformed_csv_rejected_safely():
    c = _register_and_login("MINE_MANAGER", "PM001")
    content = b'\x00\x01\xfe\xff not really a csv at all \x00\x00'
    r = upload(c, "PM001", "preview", content)
    assert r.status_code == 400
    assert "error" in r.get_json()
    assert "Traceback" not in str(r.get_json())


def test_empty_file_rejected():
    c = _register_and_login("MINE_MANAGER", "PM001")
    r = upload(c, "PM001", "preview", b"")
    assert r.status_code == 400
    assert "empty" in r.get_json()["error"].lower()


def test_header_only_no_data_rows_rejected():
    c = _register_and_login("MINE_MANAGER", "PM001")
    content = b"period,coal_production_t,diesel_consumption_l,electricity_consumption_kwh,renewable_electricity_share_pct\n"
    r = upload(c, "PM001", "preview", content)
    assert r.status_code == 400


def test_non_csv_file_rejected():
    c = _register_and_login("MINE_MANAGER", "PM001")
    r = c.post(
        "/api/mine/PM001/data/import/preview",
        data={"file": (io.BytesIO(b"hello"), "not_a_csv.txt")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400
    assert ".csv" in r.get_json()["error"]


def test_no_file_uploaded_rejected():
    c = _register_and_login("MINE_MANAGER", "PM001")
    r = c.post("/api/mine/PM001/data/import/preview", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Row-level validation
# ---------------------------------------------------------------------------

def test_invalid_numeric_value_row_flagged():
    c = _register_and_login("MINE_MANAGER", "PM001")
    content = csv_bytes([valid_row(diesel_consumption_l="not-a-number")])
    r = upload(c, "PM001", "preview", content)
    body = r.get_json()
    assert body["can_import"] is False
    assert body["invalid_rows"] == 1
    assert body["rows"][0]["status"] == "error"


def test_negative_value_row_flagged():
    c = _register_and_login("MINE_MANAGER", "PM001")
    content = csv_bytes([valid_row(coal_production_t=-500)])
    r = upload(c, "PM001", "preview", content)
    body = r.get_json()
    assert body["invalid_rows"] == 1


def test_invalid_renewable_percentage_flagged():
    c = _register_and_login("MINE_MANAGER", "PM001")
    content = csv_bytes([valid_row(renewable_electricity_share_pct=150)])
    r = upload(c, "PM001", "preview", content)
    assert r.get_json()["invalid_rows"] == 1


def test_invalid_month_flagged():
    c = _register_and_login("MINE_MANAGER", "PM001")
    content = csv_bytes([valid_row(period="2060-13")])
    r = upload(c, "PM001", "preview", content)
    assert r.get_json()["invalid_rows"] == 1


def test_duplicate_rows_inside_file_flagged():
    c = _register_and_login("MINE_MANAGER", "PM001")
    period = unique_period()
    content = csv_bytes([valid_row(period), valid_row(period)])
    r = upload(c, "PM001", "preview", content)
    body = r.get_json()
    assert body["invalid_rows"] >= 1
    assert any("Duplicate period" in (row.get("error") or "") for row in body["rows"])


def test_duplicate_of_existing_record_flagged_not_overwritten():
    c = _register_and_login("MINE_MANAGER", "PM001")
    content = csv_bytes([valid_row("2025-01")])  # collides with original synthetic PM001 data
    r = upload(c, "PM001", "preview", content)
    body = r.get_json()
    assert body["invalid_rows"] == 1
    assert "already exists" in body["rows"][0]["error"]

    conn = get_connection()
    row = conn.execute(
        "SELECT diesel_consumption_l, provenance FROM operations_monthly WHERE mine_id='PM001' AND period='2025-01'"
    ).fetchone()
    conn.close()
    assert row["provenance"] == "synthetic_prototype"  # untouched


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

def test_unauthorized_mine_rejected():
    c = _register_and_login("MINE_MANAGER", "PM001")
    content = csv_bytes([valid_row()])
    r = upload(c, "PM002", "preview", content)
    assert r.status_code == 403


def test_admin_can_import():
    c = _register_and_login("ADMIN", None)
    content = csv_bytes([valid_row()])
    r = upload(c, "PM003", "confirm", content)
    assert r.status_code == 200
    assert r.get_json()["rows_imported"] == 1


def test_mine_manager_can_import_own_mine():
    c = _register_and_login("MINE_MANAGER", "PM002")
    content = csv_bytes([valid_row()])
    r = upload(c, "PM002", "confirm", content)
    assert r.status_code == 200


def test_mine_manager_cross_mine_import_denied():
    c = _register_and_login("MINE_MANAGER", "PM002")
    content = csv_bytes([valid_row()])
    r = upload(c, "PM001", "confirm", content)
    assert r.status_code == 403


def test_analyst_import_denied():
    c = _register_and_login("ANALYST", "PM001")
    content = csv_bytes([valid_row()])
    r = upload(c, "PM001", "preview", content)
    assert r.status_code == 403
    r2 = upload(c, "PM001", "confirm", content)
    assert r2.status_code == 403


def test_unauthenticated_denied():
    content = csv_bytes([valid_row()])
    r = client().post(
        "/api/mine/PM001/data/import/preview",
        data={"file": (io.BytesIO(content), "d.csv")}, content_type="multipart/form-data",
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Zero-row-on-failure / transactional behavior
# ---------------------------------------------------------------------------

def test_failed_validation_at_confirm_imports_zero_rows():
    c = _register_and_login("MINE_MANAGER", "PM001")
    good_period = unique_period()
    content = csv_bytes([valid_row(good_period), valid_row(coal_production_t=-1)])  # one good, one bad

    conn = get_connection()
    before = conn.execute("SELECT COUNT(*) FROM operations_monthly WHERE mine_id='PM001'").fetchone()[0]
    conn.close()

    r = upload(c, "PM001", "confirm", content)
    assert r.status_code == 400

    conn = get_connection()
    after = conn.execute("SELECT COUNT(*) FROM operations_monthly WHERE mine_id='PM001'").fetchone()[0]
    conn.close()
    assert after == before  # zero rows imported, including the one valid row


def test_successful_import_is_all_or_nothing_atomic():
    c = _register_and_login("MINE_MANAGER", "PM001")
    p1, p2, p3 = unique_period(), unique_period(), unique_period()
    content = csv_bytes([valid_row(p1), valid_row(p2), valid_row(p3)])
    r = upload(c, "PM001", "confirm", content)
    assert r.status_code == 200
    assert set(r.get_json()["periods_imported"]) == {p1, p2, p3}


# ---------------------------------------------------------------------------
# Provenance / audit / calculation integration
# ---------------------------------------------------------------------------

def test_provenance_preserved_from_csv():
    c = _register_and_login("MINE_MANAGER", "PM001")
    period = unique_period()
    content = csv_bytes([valid_row(period, provenance="provisional")])
    upload(c, "PM001", "confirm", content)

    conn = get_connection()
    row = conn.execute(
        "SELECT provenance, source_type FROM operations_monthly WHERE mine_id='PM001' AND period=?", (period,)
    ).fetchone()
    conn.close()
    assert row["provenance"] == "provisional"
    assert row["source_type"] == "csv_import"


def test_csv_cannot_claim_verified_or_synthetic():
    c = _register_and_login("MINE_MANAGER", "PM001")
    for bad_prov in ("verified", "synthetic_prototype", "reference"):
        content = csv_bytes([valid_row(provenance=bad_prov)])
        r = upload(c, "PM001", "preview", content)
        assert r.get_json()["invalid_rows"] == 1, f"expected rejection for provenance={bad_prov}"


def test_created_by_and_created_at_recorded_on_import():
    c = _register_and_login("MINE_MANAGER", "PM001")
    period = unique_period()
    content = csv_bytes([valid_row(period)])
    upload(c, "PM001", "confirm", content)

    conn = get_connection()
    row = conn.execute(
        "SELECT created_by, created_at FROM operations_monthly WHERE mine_id='PM001' AND period=?", (period,)
    ).fetchone()
    conn.close()
    assert row["created_by"] is not None
    assert row["created_at"] is not None


def test_automatic_recalculation_after_import():
    c = _register_and_login("MINE_MANAGER", "PM001")
    period = unique_period()
    content = csv_bytes([valid_row(period)])
    upload(c, "PM001", "confirm", content)

    conn = get_connection()
    calc = conn.execute(
        "SELECT scope1_tco2e, scope2_tco2e FROM emission_calculations_monthly WHERE mine_id='PM001' AND period=?", (period,)
    ).fetchone()
    conn.close()
    assert calc is not None
    assert calc["scope1_tco2e"] > 0


def test_data_quality_status_after_import():
    c = _register_and_login("MINE_MANAGER", "PM001")
    period = unique_period()
    content = csv_bytes([valid_row(period, fugitive_methane_t="")])  # missing optional field
    r = upload(c, "PM001", "preview", content)
    body = r.get_json()
    assert body["rows"][0]["status"] == "valid"
    assert "Fugitive Methane not recorded" in body["rows"][0]["warnings"]


def test_dashboard_reflects_imported_data():
    c = _register_and_login("MINE_MANAGER", "PM001")
    before = c.get("/api/mine/PM001/baseline").get_json()
    months_before = len(before["monthly_trend"])

    period = unique_period()
    content = csv_bytes([valid_row(period)])
    upload(c, "PM001", "confirm", content)

    after = c.get("/api/mine/PM001/baseline").get_json()
    assert len(after["monthly_trend"]) == months_before + 1


# ---------------------------------------------------------------------------
# Historical data preservation
# ---------------------------------------------------------------------------

def test_original_synthetic_data_untouched_after_import():
    c = _register_and_login("ADMIN", None)
    content = csv_bytes([valid_row()])
    upload(c, "PM001", "confirm", content)

    conn = get_connection()
    row = conn.execute(
        "SELECT diesel_consumption_l, provenance FROM operations_monthly WHERE mine_id='PM001' AND period='2025-01'"
    ).fetchone()
    conn.close()
    assert abs(row["diesel_consumption_l"] - 693272.0) < 0.5
    assert row["provenance"] == "synthetic_prototype"


def test_optimizer_still_works_after_import():
    c = _register_and_login("ADMIN", None)
    content = csv_bytes([valid_row()])
    upload(c, "PM001", "confirm", content)
    r = c.post("/api/optimize", json={"mine_id": "PM001", "budget_inr": 100_000_000, "target_reduction_pct": 30})
    assert r.status_code == 200
    assert r.get_json()["status"] in ("TARGET_MET", "TARGET_NOT_FEASIBLE_WITHIN_BUDGET")


# ---------------------------------------------------------------------------
# Phase 6F: calculated Scope 1/2/3/Total/Intensity surfaced after import
# ---------------------------------------------------------------------------

def test_import_confirm_returns_calculated_scopes_per_period():
    c = _register_and_login("MINE_MANAGER", "PM001")
    period = unique_period()
    content = csv_bytes([valid_row(period)])
    r = upload(c, "PM001", "confirm", content)
    assert r.status_code == 200
    body = r.get_json()
    assert "calculations" in body
    assert len(body["calculations"]) == 1
    calc = body["calculations"][0]
    assert calc["period"] == period
    assert calc["scope1_tco2e"] > 0
    assert calc["scope2_tco2e"] > 0
    assert "total_tco2e" in calc
    assert "intensity_tco2e_per_t" in calc


def test_import_confirm_returns_calculations_for_multiple_rows():
    c = _register_and_login("ADMIN", None)
    p1, p2 = unique_period(), unique_period()
    content = csv_bytes([valid_row(p1), valid_row(p2)])
    r = upload(c, "PM003", "confirm", content)
    body = r.get_json()
    assert len(body["calculations"]) == 2
    assert {c["period"] for c in body["calculations"]} == {p1, p2}


# ---------------------------------------------------------------------------
# Phase 6F: unexpected/extra columns flagged (informational, non-blocking)
# ---------------------------------------------------------------------------

def test_unexpected_extra_column_rejected():
    c = _register_and_login("MINE_MANAGER", "PM001")
    period = unique_period()
    header = ["period", "coal_production_t", "diesel_consumption_l", "electricity_consumption_kwh",
              "renewable_electricity_share_pct", "fugitive_methane_t", "transport_activity_tkm",
              "commute_activity_pkm", "provenance", "source_note", "totally_made_up_column"]
    content = csv_bytes([valid_row(period) + ["extra value"]], header=header)
    r = upload(c, "PM001", "preview", content)
    assert r.status_code == 400
    body = r.get_json()
    assert "Unrecognized column" in body["error"]
    assert "totally_made_up_column" in body["error"]

    # zero database writes -- rejection happens at file-parse time, before any row validation
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) FROM operations_monthly WHERE mine_id='PM001' AND period=?", (period,)
    ).fetchone()[0]
    conn.close()
    assert row == 0


def test_unexpected_column_rejected_at_confirm_too_zero_writes():
    c = _register_and_login("ADMIN", None)
    period = unique_period()
    header = ["period", "coal_production_t", "diesel_consumption_l", "electricity_consumption_kwh",
              "renewable_electricity_share_pct", "unexpected_col"]
    content = csv_bytes([[period, 90000, 600000, 1100000, 7, "x"]], header=header)
    r = upload(c, "PM001", "confirm", content)
    assert r.status_code == 400

    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) FROM operations_monthly WHERE mine_id='PM001' AND period=?", (period,)
    ).fetchone()[0]
    conn.close()
    assert row == 0


def test_exact_template_header_accepted_no_rejection():
    c = _register_and_login("ADMIN", None)
    content = csv_bytes([valid_row()])
    r = upload(c, "PM001", "preview", content)
    assert r.status_code == 200
    assert r.get_json()["can_import"] is True


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
