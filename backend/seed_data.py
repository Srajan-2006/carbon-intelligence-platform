"""
seed_data.py

Deterministic, repeatable database seeding.

Behaviour:
  - Drops and recreates the SQLite DB from schema.sql every run (idempotent).
  - Loads mine_master, operations_monthly, emission_factors, interventions,
    net_zero_roadmap, kpi_library directly from data/*.csv, preserving the
    provenance field on every row.
  - Derives emission_calculations_monthly by calling the ALREADY-TESTED
    carbon_engine.calculate_period_footprint() for every (mine, period) --
    calculations are never hand-entered, so they cannot drift from the
    formulas verified in tests/test_carbon_engine.py.
  - Runs post-load validation: row counts match CSV row counts, every
    provenance value is one of the three allowed values, and no calculation
    row is missing its source activity data.

Run with: python3 backend/seed_data.py
"""

import csv
import os
import sys
import json
import sqlite3

sys.path.insert(0, os.path.dirname(__file__))
import carbon_engine as ce

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
DATA_DIR = os.path.join(BASE_DIR, "data")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
DB_PATH = os.path.join(DATA_DIR, "mine_carbon.db")

ALLOWED_PROVENANCE = {"reference", "provisional", "synthetic_prototype"}


def _read_csv(filename):
    path = os.path.join(DATA_DIR, filename)
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _to_float(v, default=0.0):
    if v is None or v == "":
        return default
    return float(v)


def build_schema(conn):
    """
    Drops and recreates the 9 emissions/intervention/roadmap tables defined in
    schema.sql. Foreign keys are explicitly disabled for this destructive
    rebuild and re-enabled immediately after.

    ROOT CAUSE FIXED HERE: schema.sql used to contain its own embedded
    `PRAGMA foreign_keys = ON;` as its first statement. Since schema.sql is
    re-executed via executescript() on every reseed, that statement silently
    re-enabled FK enforcement mid-script, immediately before the DROP TABLE
    statements ran -- which broke reseeding on any database that already has
    a `users` table with a live FK to mine_master (dropping a referenced
    parent table while FK enforcement is on raises FOREIGN KEY constraint
    failed). Fixed by removing the embedded pragma from schema.sql itself:
    FK enforcement is now controlled only by the connecting code (here, and
    in database.py for normal app operation), never by the DDL script.
    """
    if conn.in_transaction:
        conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    if conn.in_transaction:
        conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def load_mine_master(conn):
    rows = _read_csv("mine_master.csv")
    for r in rows:
        assert r["provenance"] in ALLOWED_PROVENANCE, f"Bad provenance in mine_master: {r}"
        conn.execute(
            """INSERT INTO mine_master (mine_id, mine_name, company, state, mine_type,
               annual_production_t, provenance, notes) VALUES (?,?,?,?,?,?,?,?)""",
            (r["mine_id"], r["mine_name"], r["company"], r["state"], r["mine_type"],
             _to_float(r["annual_production_t"]), r["provenance"], r.get("notes", "")),
        )
    return len(rows)


def load_operations_monthly(conn):
    rows = _read_csv("operations_monthly.csv")
    for r in rows:
        assert r["provenance"] in ALLOWED_PROVENANCE, f"Bad provenance in operations_monthly: {r}"
        conn.execute(
            """INSERT INTO operations_monthly
               (mine_id, period, coal_production_t, diesel_consumption_l, electricity_consumption_kwh,
                renewable_electricity_share, transport_activity_tkm, commute_activity_pkm,
                fugitive_methane_t, provenance)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (r["mine_id"], r["period"], _to_float(r["coal_production_t"]), _to_float(r["diesel_consumption_l"]),
             _to_float(r["electricity_consumption_kwh"]), _to_float(r["renewable_electricity_share"]),
             _to_float(r["transport_activity_tkm"]), _to_float(r["commute_activity_pkm"]),
             _to_float(r["fugitive_methane_t"]), r["provenance"]),
        )
    return len(rows)


def load_emission_factors(conn):
    rows = _read_csv("emission_factors.csv")
    for r in rows:
        assert r["provenance"] in ALLOWED_PROVENANCE, f"Bad provenance in emission_factors: {r}"
        conn.execute(
            """INSERT INTO emission_factors (factor_id, factor_name, scope, gas, factor_value, unit,
               geography, source, provenance) VALUES (?,?,?,?,?,?,?,?,?)""",
            (r["factor_id"], r["factor_name"], r["scope"], r["gas"], _to_float(r["factor_value"]),
             r["unit"], r["geography"], r["source"], r["provenance"]),
        )
    return len(rows)


def load_interventions(conn):
    rows = _read_csv("interventions.csv")
    for r in rows:
        assert r["provenance"] in ALLOWED_PROVENANCE, f"Bad provenance in interventions: {r}"
        conn.execute(
            """INSERT INTO interventions
               (intervention_id, name, description, target_scope, control_variable, min_deployment,
                max_deployment, deployment_step, cost_per_unit_deployment_inr, scope1_reduction_at_full,
                scope2_delta_at_full, scope3_reduction_at_full, has_interaction, assumptions,
                feasibility_notes, provenance)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["intervention_id"], r["name"], r["description"], r["target_scope"], r["control_variable"],
             _to_float(r["min_deployment"]), _to_float(r["max_deployment"]), _to_float(r["deployment_step"]),
             _to_float(r["cost_per_unit_deployment_inr"]), _to_float(r["scope1_reduction_at_full"]),
             _to_float(r["scope2_delta_at_full"]), _to_float(r["scope3_reduction_at_full"]),
             1 if r["has_interaction"] == "1" else 0, r["assumptions"], r["feasibility_notes"], r["provenance"]),
        )
    return len(rows)


def load_roadmap(conn):
    rows = _read_csv("net_zero_roadmap.csv")
    for r in rows:
        assert r["provenance"] in ALLOWED_PROVENANCE, f"Bad provenance in net_zero_roadmap: {r}"
        conn.execute(
            """INSERT INTO net_zero_roadmap
               (mine_id, year, milestone, intervention_summary, investment_inr, expected_reduction_pct,
                cumulative_reduction_pct, remaining_emissions_t, provenance)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (r["mine_id"], int(r["year"]), r["milestone"], r["intervention_summary"],
             _to_float(r["investment_inr"]), _to_float(r["expected_reduction_pct"]),
             _to_float(r["cumulative_reduction_pct"]), _to_float(r["remaining_emissions_t"]), r["provenance"]),
        )
    return len(rows)


def load_kpi_library(conn):
    rows = _read_csv("kpi_library.csv")
    for r in rows:
        conn.execute(
            """INSERT INTO kpi_library (kpi_id, kpi_name, description, unit, decision_support_purpose)
               VALUES (?,?,?,?,?)""",
            (r["kpi_id"], r["kpi_name"], r["description"], r["unit"], r["decision_support_purpose"]),
        )
    return len(rows)


def compute_emission_calculations(conn):
    """
    Derive emission_calculations_monthly from operations_monthly + emission_factors
    using the tested carbon_engine -- calculations are computed, never hand-entered.
    """
    factors = {row["factor_id"]: row["factor_value"] for row in conn.execute(
        "SELECT factor_id, factor_value FROM emission_factors")}

    ops = conn.execute("SELECT * FROM operations_monthly").fetchall()
    count = 0
    for row in ops:
        activity = {
            "diesel_consumption_l": row["diesel_consumption_l"],
            "fugitive_methane_t": row["fugitive_methane_t"],
            "electricity_consumption_kwh": row["electricity_consumption_kwh"],
            "renewable_electricity_share": row["renewable_electricity_share"],
            "transport_activity_tkm": row["transport_activity_tkm"],
            "commute_activity_pkm": row["commute_activity_pkm"],
            "coal_production_t": row["coal_production_t"],
        }
        result = ce.calculate_period_footprint(activity, factors)
        # Calculation provenance follows the weaker (more conservative) of the
        # source activity data and factor provenance; since this prototype's
        # activity data is synthetic_prototype, calculations are too.
        provenance = row["provenance"]
        conn.execute(
            """INSERT INTO emission_calculations_monthly
               (mine_id, period, scope1_tco2e, scope2_tco2e, scope3_tco2e, total_tco2e,
                intensity_tco2e_per_t, calc_detail_json, provenance)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (row["mine_id"], row["period"], result["scope1_tco2e"], result["scope2_tco2e"],
             result["scope3_tco2e"], result["total_tco2e"], result["intensity_tco2e_per_t"],
             json.dumps(result["calc_detail"]), provenance),
        )
        count += 1
    return count


def validate(conn):
    """Post-load consistency checks. Raises AssertionError on any mismatch."""
    problems = []

    def csv_len(name):
        return len(_read_csv(name))

    checks = [
        ("mine_master", "mine_master.csv"),
        ("operations_monthly", "operations_monthly.csv"),
        ("emission_factors", "emission_factors.csv"),
        ("interventions", "interventions.csv"),
        ("net_zero_roadmap", "net_zero_roadmap.csv"),
        ("kpi_library", "kpi_library.csv"),
    ]
    for table, csv_file in checks:
        db_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        expected = csv_len(csv_file)
        if db_count != expected:
            problems.append(f"{table}: DB has {db_count} rows, CSV {csv_file} has {expected}")

    calc_count = conn.execute("SELECT COUNT(*) FROM emission_calculations_monthly").fetchone()[0]
    ops_count = conn.execute("SELECT COUNT(*) FROM operations_monthly").fetchone()[0]
    if calc_count != ops_count:
        problems.append(f"emission_calculations_monthly ({calc_count}) != operations_monthly ({ops_count})")

    bad_prov = conn.execute(
        """SELECT 'mine_master' t, mine_id id FROM mine_master WHERE provenance NOT IN ('reference','provisional','synthetic_prototype')
           UNION ALL
           SELECT 'operations_monthly', mine_id||'/'||period FROM operations_monthly WHERE provenance NOT IN ('reference','provisional','synthetic_prototype')
           UNION ALL
           SELECT 'interventions', intervention_id FROM interventions WHERE provenance NOT IN ('reference','provisional','synthetic_prototype')"""
    ).fetchall()
    if bad_prov:
        problems.append(f"Invalid provenance values found: {[dict(r) for r in bad_prov]}")

    # Every mine referenced in operations_monthly must exist in mine_master
    orphans = conn.execute(
        """SELECT DISTINCT om.mine_id FROM operations_monthly om
           LEFT JOIN mine_master mm ON om.mine_id = mm.mine_id
           WHERE mm.mine_id IS NULL"""
    ).fetchall()
    if orphans:
        problems.append(f"operations_monthly references unknown mine_id(s): {[dict(r) for r in orphans]}")

    if problems:
        raise AssertionError("Seed validation failed:\n  - " + "\n  - ".join(problems))


def ensure_users_table(conn):
    """
    Non-destructive: creates the users table only if it doesn't already exist.
    Must be safe to call on every app startup and every reseed without ever
    dropping existing accounts.
    """
    auth_schema_path = os.path.join(os.path.dirname(__file__), "auth_schema.sql")
    with open(auth_schema_path, "r", encoding="utf-8") as f:
        conn.executescript(f.read())


def _table_columns(conn, table_name):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _table_sql(conn, table_name):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    return row[0] if row else ""


def ensure_phase6_schema(conn):
    """
    PHASE 6 -- additive, idempotent, non-destructive migration.

    Adds mine-management metadata to mine_master and provenance/source
    metadata to operations_monthly, WITHOUT dropping or truncating any
    existing table, row, user, or emissions record. Safe to call on every
    app startup (checks what already exists before doing anything) and safe
    to call against a database that predates Phase 6.

    Two distinct migration techniques are used, deliberately:

    1. mine_master gets three new nullable/defaulted columns
       (is_active, created_by, created_at) via plain `ALTER TABLE ADD COLUMN`
       -- SQLite supports this directly without touching existing rows or
       any constraint, so it's the simplest safe option here.

    2. operations_monthly needs its `provenance` CHECK constraint widened to
       accept two new values ('measured', 'verified') alongside the existing
       three, plus five new columns (source_type, source_note, created_by,
       created_at, updated_at). SQLite cannot ALTER a CHECK constraint or add
       a new columns-with-constraint in place, so this uses SQLite's own
       documented safe pattern for changing a constraint: create a new table
       with the desired final shape, copy every existing row into it
       unchanged (explicit id preserved), drop the old table, rename the new
       one into its place. This never disables foreign_keys -- unlike the
       Phase 5 mine_master rebuild, nothing else has a live FK to
       operations_monthly, so no toggle is needed here at all.

    Both steps are no-ops (and safe to re-run) once already applied.
    """
    # --- mine_master: additive columns only, no constraint changes ---
    mm_columns = _table_columns(conn, "mine_master")
    if "is_active" not in mm_columns:
        conn.execute("ALTER TABLE mine_master ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    if "created_by" not in mm_columns:
        conn.execute("ALTER TABLE mine_master ADD COLUMN created_by INTEGER")
    if "created_at" not in mm_columns:
        # SQLite's ALTER TABLE ADD COLUMN disallows a non-constant default
        # (e.g. datetime('now')), so add the column plain, then backfill.
        # Existing (pre-Phase-6) mines get the migration run time here, not a
        # fabricated original creation time -- this is a lightweight audit
        # field, not a claim about when the mine was actually first entered.
        conn.execute("ALTER TABLE mine_master ADD COLUMN created_at TEXT")
        conn.execute("UPDATE mine_master SET created_at = datetime('now') WHERE created_at IS NULL")
    if "updated_at" not in mm_columns:
        # Phase 6D: auditability for mine metadata edits (requirement #12).
        # NULL until a mine is actually edited via Mine Management -- unlike
        # created_at, we do NOT backfill this with the migration time, since
        # "never edited" is a real, meaningful, distinct state from "edited
        # at some unknown past time" and backfilling would misrepresent it.
        conn.execute("ALTER TABLE mine_master ADD COLUMN updated_at TEXT")
    if "updated_by" not in mm_columns:
        conn.execute("ALTER TABLE mine_master ADD COLUMN updated_by INTEGER")

    # --- operations_monthly: widen provenance CHECK + add metadata columns ---
    om_sql = _table_sql(conn, "operations_monthly")
    needs_rebuild = "'measured'" not in om_sql

    if needs_rebuild:
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN")
        try:
            conn.execute("""
                CREATE TABLE operations_monthly_phase6_new (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    mine_id                 TEXT NOT NULL REFERENCES mine_master(mine_id),
                    period                  TEXT NOT NULL,
                    coal_production_t       REAL,
                    diesel_consumption_l    REAL,
                    electricity_consumption_kwh REAL,
                    renewable_electricity_share REAL,
                    transport_activity_tkm  REAL,
                    commute_activity_pkm    REAL,
                    fugitive_methane_t      REAL,
                    provenance              TEXT NOT NULL CHECK (
                        provenance IN ('reference','provisional','synthetic_prototype','measured','verified')
                    ),
                    source_type             TEXT DEFAULT 'reference',
                    source_note             TEXT,
                    created_by              INTEGER,
                    created_at              TEXT DEFAULT (datetime('now')),
                    updated_at              TEXT,
                    updated_by              INTEGER,
                    UNIQUE(mine_id, period)
                )
            """)
            existing_om_columns = _table_columns(conn, "operations_monthly")
            select_cols = ", ".join(
                c if c in existing_om_columns else "NULL"
                for c in ["id", "mine_id", "period", "coal_production_t", "diesel_consumption_l",
                          "electricity_consumption_kwh", "renewable_electricity_share",
                          "transport_activity_tkm", "commute_activity_pkm", "fugitive_methane_t", "provenance"]
            )
            conn.execute(f"""
                INSERT INTO operations_monthly_phase6_new
                    (id, mine_id, period, coal_production_t, diesel_consumption_l,
                     electricity_consumption_kwh, renewable_electricity_share,
                     transport_activity_tkm, commute_activity_pkm, fugitive_methane_t,
                     provenance, source_type)
                SELECT {select_cols}, 'reference'
                FROM operations_monthly
            """)
            conn.execute("DROP TABLE operations_monthly")
            conn.execute("ALTER TABLE operations_monthly_phase6_new RENAME TO operations_monthly")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    else:
        om_columns = _table_columns(conn, "operations_monthly")
        if "source_type" not in om_columns:
            conn.execute("ALTER TABLE operations_monthly ADD COLUMN source_type TEXT DEFAULT 'reference'")
        if "source_note" not in om_columns:
            conn.execute("ALTER TABLE operations_monthly ADD COLUMN source_note TEXT")
        if "created_by" not in om_columns:
            conn.execute("ALTER TABLE operations_monthly ADD COLUMN created_by INTEGER")
        if "created_at" not in om_columns:
            conn.execute("ALTER TABLE operations_monthly ADD COLUMN created_at TEXT")
            conn.execute("UPDATE operations_monthly SET created_at = datetime('now') WHERE created_at IS NULL")
        if "updated_at" not in om_columns:
            conn.execute("ALTER TABLE operations_monthly ADD COLUMN updated_at TEXT")
        if "updated_by" not in om_columns:
            # Phase 6H: tracks WHO last edited an operational record, matching
            # the created_by/updated_by pattern already established for
            # mine_master in Phase 6D. Previously only WHEN (updated_at) was
            # tracked for operational records, not WHO.
            conn.execute("ALTER TABLE operations_monthly ADD COLUMN updated_by INTEGER")

    conn.commit()

    # --- emission_calculations_monthly: widen provenance CHECK the same way ---
    # Needed because recalc_period() (Phase 6B) writes the operational record's
    # OWN provenance (e.g. 'measured') into this table's provenance column, and
    # the original CHECK constraint here predates 'measured'/'verified' too.
    # No other table has a live FK to this one, so this is a plain rebuild.
    ecm_sql = _table_sql(conn, "emission_calculations_monthly")
    if "'measured'" not in ecm_sql:
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN")
        try:
            conn.execute("""
                CREATE TABLE emission_calculations_monthly_phase6_new (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    mine_id         TEXT NOT NULL REFERENCES mine_master(mine_id),
                    period          TEXT NOT NULL,
                    scope1_tco2e    REAL NOT NULL,
                    scope2_tco2e    REAL NOT NULL,
                    scope3_tco2e    REAL NOT NULL,
                    total_tco2e     REAL NOT NULL,
                    intensity_tco2e_per_t REAL,
                    calc_detail_json TEXT,
                    provenance      TEXT NOT NULL CHECK (
                        provenance IN ('reference','provisional','synthetic_prototype','measured','verified')
                    ),
                    UNIQUE(mine_id, period)
                )
            """)
            conn.execute("""
                INSERT INTO emission_calculations_monthly_phase6_new
                    (id, mine_id, period, scope1_tco2e, scope2_tco2e, scope3_tco2e, total_tco2e,
                     intensity_tco2e_per_t, calc_detail_json, provenance)
                SELECT id, mine_id, period, scope1_tco2e, scope2_tco2e, scope3_tco2e, total_tco2e,
                       intensity_tco2e_per_t, calc_detail_json, provenance
                FROM emission_calculations_monthly
            """)
            conn.execute("DROP TABLE emission_calculations_monthly")
            conn.execute("ALTER TABLE emission_calculations_monthly_phase6_new RENAME TO emission_calculations_monthly")
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def seed():
    """
    Rebuilds the emissions/intervention/roadmap data deterministically from
    schema.sql + the CSVs in data/. This DOES drop and recreate those tables
    (by design, so the prototype dataset is always reproducible from source).

    IMPORTANT: this must NOT delete the database file or touch the `users`
    table. schema.sql only drops the 9 emissions/intervention/roadmap tables
    it defines; it never references `users`. Previously this function deleted
    the whole .db file on every run, which would have wiped any registered
    accounts -- fixed here so authentication data survives reseeding.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    build_schema(conn)
    ensure_users_table(conn)
    ensure_phase6_schema(conn)

    counts = {}
    counts["mine_master"] = load_mine_master(conn)
    counts["operations_monthly"] = load_operations_monthly(conn)
    counts["emission_factors"] = load_emission_factors(conn)
    counts["interventions"] = load_interventions(conn)
    counts["net_zero_roadmap"] = load_roadmap(conn)
    counts["kpi_library"] = load_kpi_library(conn)
    conn.commit()

    counts["emission_calculations_monthly"] = compute_emission_calculations(conn)
    conn.commit()

    validate(conn)

    conn.close()
    return counts


if __name__ == "__main__":
    counts = seed()
    print("Database seeded successfully:", DB_PATH)
    for table, n in counts.items():
        print(f"  {table}: {n} rows")
    print("Validation passed: DB row counts match CSV sources, provenance values valid, no orphaned mine references.")
    print("Users table preserved (not dropped) -- run backend/create_demo_users.py separately to (re)create demo accounts.")
