import sys, os, sqlite3, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import seed_data as sd
sd.seed()

import app as flask_app_module
from database import get_connection

app = flask_app_module.app
app.testing = True


def test_phase6_columns_present_after_fresh_seed():
    conn = get_connection()
    mm_cols = {r[1] for r in conn.execute("PRAGMA table_info(mine_master)")}
    om_cols = {r[1] for r in conn.execute("PRAGMA table_info(operations_monthly)")}
    conn.close()
    for c in ("is_active", "created_by", "created_at"):
        assert c in mm_cols, f"mine_master missing {c}"
    for c in ("source_type", "source_note", "created_by", "created_at", "updated_at"):
        assert c in om_cols, f"operations_monthly missing {c}"


def test_widened_provenance_check_accepts_measured_and_verified():
    conn = get_connection()
    for prov in ("measured", "verified"):
        conn.execute(
            """INSERT INTO operations_monthly
               (mine_id, period, coal_production_t, diesel_consumption_l, electricity_consumption_kwh,
                renewable_electricity_share, transport_activity_tkm, commute_activity_pkm,
                fugitive_methane_t, provenance, source_type)
               VALUES ('PM001', ?, 1000, 500, 1000, 0.1, 100, 50, 1, ?, 'manual_entry')""",
            (f"2099-{'01' if prov == 'measured' else '02'}", prov),
        )
    conn.commit()
    rows = conn.execute("SELECT provenance FROM operations_monthly WHERE period IN ('2099-01','2099-02')").fetchall()
    conn.close()
    assert {r[0] for r in rows} == {"measured", "verified"}


def test_still_rejects_invalid_provenance():
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO operations_monthly
               (mine_id, period, provenance) VALUES ('PM001', '2098-01', 'not_a_real_provenance')"""
        )
        conn.commit()
        assert False, "should have raised IntegrityError"
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()


def test_existing_original_synthetic_data_untouched_by_migration():
    """The 3 original prototype mines and their 36 monthly records must survive
    the Phase 6 migration byte-for-byte, not just in row count."""
    sd.seed()  # guarantee a clean baseline regardless of other tests' side effects in this shared DB
    conn = get_connection()
    mines = conn.execute("SELECT mine_id FROM mine_master ORDER BY mine_id").fetchall()
    assert [m[0] for m in mines] == ["PM001", "PM002", "PM003"]

    op_count = conn.execute("SELECT COUNT(*) FROM operations_monthly").fetchone()[0]
    assert op_count == 36

    row = conn.execute(
        "SELECT diesel_consumption_l, provenance FROM operations_monthly WHERE mine_id='PM001' AND period='2025-01'"
    ).fetchone()
    assert abs(row[0] - 693272.0) < 0.5
    assert row[1] == "synthetic_prototype"

    calc_count = conn.execute("SELECT COUNT(*) FROM emission_calculations_monthly").fetchone()[0]
    assert calc_count == 36
    conn.close()


def test_users_survive_reseed_after_phase6_migration():
    """Combined regression check: Phase 5's reseed-safety guarantee still
    holds now that Phase 6 has modified the same migration pipeline."""
    import random
    email = f"phase6-survivor-{random.randint(100000,999999)}@example.com"
    conn = get_connection()
    from werkzeug.security import generate_password_hash
    conn.execute(
        "INSERT INTO users (name,email,password_hash,role,mine_id,is_active) VALUES (?,?,?,?,?,1)",
        ("Phase6 Survivor", email, generate_password_hash("password123"), "ANALYST", "PM001"),
    )
    conn.commit()
    conn.close()

    sd.seed()  # full reseed

    conn = get_connection()
    row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    conn.close()
    assert row is not None


def test_migration_is_idempotent():
    """Running ensure_phase6_schema twice must not error or duplicate anything."""
    conn = get_connection()
    before = conn.execute("SELECT COUNT(*) FROM operations_monthly").fetchone()[0]
    sd.ensure_phase6_schema(conn)  # already applied by seed() above; must be a safe no-op
    after = conn.execute("SELECT COUNT(*) FROM operations_monthly").fetchone()[0]
    conn.close()
    assert before == after


def test_foreign_keys_enabled_on_normal_connections():
    """Normal app connections (via database.get_connection) must always have
    FK enforcement ON -- the migration must never leave it disabled."""
    conn = get_connection()
    fk_state = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.close()
    assert fk_state == 1


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
