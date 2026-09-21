"""
app.py

Flask REST API for the Mine Carbon Intelligence & Decarbonization Platform.

ARCHITECTURE RULE: this file contains NO carbon-calculation or optimization
logic. It validates requests, queries the database, calls carbon_engine.py
and optimizer.py (both independently unit-tested), and shapes JSON
responses. All business logic lives in those modules, not here or in the
frontend.
"""

import os
import sys
import json
import secrets
import traceback
from datetime import timedelta

from flask import Flask, jsonify, request, render_template, redirect, url_for, g, session

sys.path.insert(0, os.path.dirname(__file__))
import carbon_engine as ce
import optimizer as opt
import auth
import mine_management as mm
import operational_data as od
import csv_import as ci
from database import get_connection, DB_PATH

# ---------------------------------------------------------------------------
# Startup migration: apply the non-destructive Phase 5 (users table) and
# Phase 6 (mine-management/provenance metadata) schema additions automatically
# on every app start, so upgrading an existing database just means restarting
# the app -- no manual seed_data.py re-run required. Both migration functions
# are idempotent and additive-only (see seed_data.py docstrings); if the
# database file doesn't exist yet at all, this is skipped and the normal
# "run seed_data.py first" setup path still applies.
# ---------------------------------------------------------------------------
if os.path.exists(DB_PATH):
    try:
        import seed_data as _seed_data
        _migration_conn = get_connection()
        _seed_data.ensure_users_table(_migration_conn)
        _seed_data.ensure_phase6_schema(_migration_conn)
        _migration_conn.close()
    except Exception as _migration_err:
        # Don't crash app startup over a migration issue on an unusual DB
        # state; surface it in the server log so it's not silently missed.
        print(f"WARNING: startup schema migration check failed: {_migration_err}", file=sys.stderr)

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "..", "frontend", "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "..", "frontend", "static"),
)

# ---------------------------------------------------------------------------
# Secret key configuration
#
# Never hardcode a production secret in source. Preferred: set the
# FLASK_SECRET_KEY environment variable before running the app. As a
# documented DEVELOPMENT-ONLY fallback (so the prototype still runs out of
# the box), a random key is generated on first run and persisted to
# data/.flask_secret_key (gitignored / instance-local, not committed
# application source) so sessions survive server restarts. This fallback is
# NOT suitable for production -- see README "Security Limitations".
# ---------------------------------------------------------------------------
_SECRET_KEY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", ".flask_secret_key")


def _resolve_secret_key():
    env_key = os.environ.get("FLASK_SECRET_KEY")
    if env_key:
        return env_key
    if os.path.exists(_SECRET_KEY_PATH):
        with open(_SECRET_KEY_PATH, "r") as f:
            existing = f.read().strip()
            if existing:
                return existing
    generated = secrets.token_hex(32)
    os.makedirs(os.path.dirname(_SECRET_KEY_PATH), exist_ok=True)
    with open(_SECRET_KEY_PATH, "w") as f:
        f.write(generated)
    return generated


app.secret_key = _resolve_secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

ALLOWED_PROVENANCE = {"reference", "provisional", "synthetic_prototype"}


# ---------------------------------------------------------------------------
# Error helpers -- never leak stack traces to the client
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, message, status_code=400, details=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {"error": err.message}
    if err.details:
        body["details"] = err.details
    return jsonify(body), err.status_code


@app.errorhandler(404)
def handle_404(err):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(Exception)
def handle_unexpected(err):
    # Werkzeug's own HTTP exceptions (404, 405, etc.) are legitimate,
    # correctly-coded responses -- pass them through unchanged rather than
    # masking them as a generic 500. Only genuinely unexpected exceptions
    # (bugs) should be caught, logged server-side, and hidden from the client.
    from werkzeug.exceptions import HTTPException
    if isinstance(err, HTTPException):
        return err
    # Log full traceback server-side only; never return it to the client.
    app.logger.error("Unhandled exception: %s\n%s", err, traceback.format_exc())
    return jsonify({"error": "Internal server error"}), 500


@app.errorhandler(auth.AuthError)
def handle_auth_error(err):
    return jsonify({"error": err.message}), err.status_code


@app.errorhandler(mm.ValidationError)
def handle_mine_management_validation_error(err):
    return jsonify({"error": err.message}), err.status_code


@app.errorhandler(od.ValidationError)
def handle_operational_data_validation_error(err):
    body = {"error": err.message}
    if err.field_errors:
        body["field_errors"] = err.field_errors
    return jsonify(body), err.status_code


@app.errorhandler(ci.CsvImportError)
def handle_csv_import_error(err):
    return jsonify({"error": err.message}), err.status_code


@app.context_processor
def inject_current_user():
    """Makes the logged-in user's public info available to every template
    (sidebar Account section) without every route having to pass it in."""
    conn = get_connection()
    user_row = auth.current_user(conn)
    conn.close()
    return {"current_user": auth._row_to_public_user(user_row) if user_row else None}


_NAV_ENDPOINT_MAP = {
    "page_dashboard": "dashboard",
    "page_footprint": "footprint",
    "page_hotspots": "hotspots",
    "page_optimizer": "optimizer",
    "page_simulator": "simulator",
    "page_roadmap": "roadmap",
    "page_methodology": "methodology",
    "page_mine_management": "mines",
}


@app.context_processor
def inject_active_nav():
    """
    Computes which sidebar item is active from the current request's Flask
    endpoint, so nav highlighting works automatically without every page
    route needing to pass active=... into render_template. (Previously the
    templates referenced an `active` variable that was never actually set by
    any route, so highlighting silently never worked.)
    """
    from flask import request as _request
    return {"active": _NAV_ENDPOINT_MAP.get(_request.endpoint, "")}


# ---------------------------------------------------------------------------
# Shared data-access helpers
# ---------------------------------------------------------------------------

def _get_mine_or_404(conn, mine_id):
    mine = conn.execute("SELECT * FROM mine_master WHERE mine_id = ?", (mine_id,)).fetchone()
    if mine is None:
        raise ApiError(f"Unknown mine_id '{mine_id}'", status_code=404)
    return mine


def _get_baseline(conn, mine_id):
    """
    Returns (mine_row, baseline_dict, provenance_summary) for the most recent
    12 months of emission_calculations_monthly available for this mine.
    """
    mine = _get_mine_or_404(conn, mine_id)
    calc_rows = conn.execute(
        "SELECT * FROM emission_calculations_monthly WHERE mine_id = ? ORDER BY period",
        (mine_id,),
    ).fetchall()
    if not calc_rows:
        raise ApiError(f"No emission calculations available for mine_id '{mine_id}'", status_code=404)

    monthly = [dict(r) for r in calc_rows]
    annual = ce.aggregate_annual(monthly)

    production_row = conn.execute(
        "SELECT SUM(coal_production_t) AS total_prod FROM operations_monthly WHERE mine_id = ?",
        (mine_id,),
    ).fetchone()
    total_production = production_row["total_prod"] or 0
    annual["intensity_tco2e_per_t"] = ce.calculate_intensity(annual["total_tco2e"], total_production)
    annual["coal_production_t"] = round(total_production, 1)

    provenance_values = {r["provenance"] for r in calc_rows}
    return mine, annual, monthly, provenance_values


def _get_interventions(conn):
    rows = conn.execute("SELECT * FROM interventions").fetchall()
    return [dict(r) for r in rows]


def _validate_mine_id(mine_id):
    if not mine_id or not isinstance(mine_id, str) or len(mine_id) > 32:
        raise ApiError("Invalid mine_id", status_code=400)


def _validate_budget(budget):
    try:
        budget = float(budget)
    except (TypeError, ValueError):
        raise ApiError("budget_inr must be a number", status_code=400)
    if budget < 0:
        raise ApiError("budget_inr must not be negative", status_code=400)
    if budget > 1e13:
        raise ApiError("budget_inr is unrealistically large", status_code=400)
    return budget


def _validate_target(target):
    try:
        target = float(target)
    except (TypeError, ValueError):
        raise ApiError("target_reduction_pct must be a number", status_code=400)
    if target < 0 or target > 100:
        raise ApiError("target_reduction_pct must be between 0 and 100", status_code=400)
    return target


# ---------------------------------------------------------------------------
# Routes -- authentication pages
# ---------------------------------------------------------------------------

@app.route("/login")
def page_login():
    conn = get_connection()
    already = auth.current_user(conn)
    conn.close()
    if already:
        return redirect(url_for("page_dashboard"))
    return render_template("login.html", next_url=request.args.get("next", ""))


@app.route("/register")
def page_register():
    conn = get_connection()
    already = auth.current_user(conn)
    if already:
        conn.close()
        return redirect(url_for("page_dashboard"))
    mines = conn.execute("SELECT mine_id, mine_name FROM mine_master ORDER BY mine_id").fetchall()
    conn.close()
    return render_template("register.html", mines=[dict(m) for m in mines])


# ---------------------------------------------------------------------------
# Routes -- frontend pages (server-rendered, login required)
# ---------------------------------------------------------------------------

@app.route("/")
@auth.login_required_page
def page_dashboard():
    return render_template("dashboard.html")


@app.route("/footprint")
@auth.login_required_page
def page_footprint():
    return render_template("footprint.html")


@app.route("/hotspots")
@auth.login_required_page
def page_hotspots():
    return render_template("hotspots.html")


@app.route("/optimizer")
@auth.login_required_page
def page_optimizer():
    return render_template("optimizer.html")


@app.route("/simulator")
@auth.login_required_page
def page_simulator():
    return render_template("simulator.html")


@app.route("/roadmap")
@auth.login_required_page
def page_roadmap():
    return render_template("roadmap.html")


@app.route("/methodology")
@auth.login_required_page
def page_methodology():
    return render_template("methodology.html")


@app.route("/mines")
@auth.login_required_page
def page_mine_management():
    return render_template("mine_management.html")


@app.route("/mine/<mine_id>/data")
@auth.login_required_page
def page_operational_data(mine_id):
    conn = get_connection()
    try:
        auth.require_mine_access(g.user, mine_id)
        _get_mine_or_404(conn, mine_id)
    finally:
        conn.close()
    return render_template("operational_data.html", mine_id=mine_id)


@app.route("/mine/<mine_id>/data/import")
@auth.login_required_page
def page_csv_import(mine_id):
    conn = get_connection()
    try:
        auth.require_mine_access(g.user, mine_id)
        _get_mine_or_404(conn, mine_id)
    finally:
        conn.close()
    return render_template("csv_import.html", mine_id=mine_id)


# ---------------------------------------------------------------------------
# Routes -- API
# ---------------------------------------------------------------------------

@app.route("/api/health")
def api_health():
    try:
        conn = get_connection()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False
    return jsonify({"status": "ok" if db_ok else "degraded", "database_connected": db_ok})


# ---------------------------------------------------------------------------
# Routes -- authentication API
# ---------------------------------------------------------------------------

@app.route("/api/auth/register", methods=["POST"])
def api_auth_register():
    payload = request.get_json(silent=True) or {}
    # SECURITY: role is only ever taken from a fixed, non-ADMIN allowlist for
    # self-registration. Ordinary users can never grant themselves ADMIN via
    # this endpoint -- an unsafe role selection would let anyone escalate
    # privileges just by editing the request body.
    requested_role = payload.get("role")
    role = requested_role if requested_role in ("MINE_MANAGER", "ANALYST") else "ANALYST"

    conn = get_connection()
    try:
        user = auth.register_user(
            conn,
            name=payload.get("name"),
            email=payload.get("email"),
            password=payload.get("password"),
            confirm_password=payload.get("confirm_password"),
            role=role,
            mine_id=payload.get("mine_id"),
        )
    finally:
        conn.close()

    return jsonify({"user": user, "message": "Account created. You can now log in."}), 201


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    payload = request.get_json(silent=True) or {}
    conn = get_connection()
    try:
        user_row = auth.authenticate(conn, payload.get("email"), payload.get("password"))
        auth.log_in_user(user_row)
        public_user = auth._row_to_public_user(user_row)
    finally:
        conn.close()
    return jsonify({"user": public_user})


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    auth.log_out_user()
    return jsonify({"message": "Logged out."})


@app.route("/api/auth/me")
def api_auth_me():
    conn = get_connection()
    user_row = auth.current_user(conn)
    conn.close()
    if user_row is None:
        return jsonify({"user": None}), 200
    return jsonify({"user": auth._row_to_public_user(user_row)})


# ---------------------------------------------------------------------------
# Routes -- API (mine reference data; public/read-only, no user-sensitive info)
# ---------------------------------------------------------------------------

@app.route("/api/mines", methods=["GET", "POST"])
def api_mines():
    if request.method == "POST":
        conn = get_connection()
        user_row = auth.current_user(conn)
        if user_row is None:
            conn.close()
            return jsonify({"error": "Authentication required."}), 401
        try:
            auth.require_admin(user_row)
            payload = request.get_json(silent=True) or {}
            mine = mm.create_mine(conn, payload, created_by_user_id=user_row["id"])
        finally:
            conn.close()
        return jsonify({"mine": mine}), 201

    # GET: public reference list (needed for the registration form pre-login).
    # Only active mines are surfaced here -- deactivated mines are still
    # visible to authorized users via /api/mine-management.
    conn = get_connection()
    rows = conn.execute(
        """SELECT mine_id, mine_name, company, state, mine_type, annual_production_t, provenance
           FROM mine_master WHERE is_active = 1 ORDER BY mine_id"""
    ).fetchall()
    conn.close()
    return jsonify({"mines": [dict(r) for r in rows]})


@app.route("/api/mine-management")
@auth.login_required_api
def api_mine_management():
    conn = get_connection()
    mines = mm.list_mines_for_management(conn, g.user)
    conn.close()
    return jsonify({"mines": mines, "role": g.user["role"]})


@app.route("/api/mine/<mine_id>", methods=["GET", "PUT"])
@auth.login_required_api
def api_mine_detail(mine_id):
    _validate_mine_id(mine_id)
    auth.require_mine_access(g.user, mine_id)  # read access is enough for GET; write checked below for PUT
    conn = get_connection()
    try:
        if request.method == "PUT":
            auth.require_mine_write_access(g.user, mine_id)
            payload = request.get_json(silent=True) or {}
            mine = mm.update_mine(conn, mine_id, payload, updated_by_user_id=g.user["id"])
        else:
            mine = mm.get_mine_detail(conn, mine_id)
            if mine is None:
                raise ApiError(f"Unknown mine_id '{mine_id}'.", status_code=404)
    finally:
        conn.close()
    return jsonify({"mine": mine})


# ---------------------------------------------------------------------------
# Routes -- Phase 6B: operational data entry
# ---------------------------------------------------------------------------

@app.route("/api/mine/<mine_id>/data", methods=["GET", "POST"])
@auth.login_required_api
def api_mine_data(mine_id):
    _validate_mine_id(mine_id)
    if request.method == "POST":
        auth.require_mine_write_access(g.user, mine_id)
        conn = get_connection()
        try:
            _get_mine_or_404(conn, mine_id)  # clean 404 instead of a raw FK IntegrityError on insert
            payload = request.get_json(silent=True) or {}
            record = od.create_record(conn, mine_id, payload, user_id=g.user["id"])
        finally:
            conn.close()
        return jsonify({"record": record}), 201

    auth.require_mine_access(g.user, mine_id)  # read access is enough for GET
    conn = get_connection()
    try:
        _get_mine_or_404(conn, mine_id)  # clean 404 instead of silently returning an empty record list
        records = od.list_records(conn, mine_id)
    finally:
        conn.close()
    return jsonify({
        "mine_id": mine_id,
        "records": records,
        "field_meta": od.FIELD_META,
    })


@app.route("/api/mine/<mine_id>/data/<int:record_id>", methods=["PUT"])
@auth.login_required_api
def api_mine_data_update(mine_id, record_id):
    _validate_mine_id(mine_id)
    auth.require_mine_write_access(g.user, mine_id)
    conn = get_connection()
    try:
        _get_mine_or_404(conn, mine_id)
        payload = request.get_json(silent=True) or {}
        record = od.update_record(conn, mine_id, record_id, payload, user_id=g.user["id"])
    finally:
        conn.close()
    return jsonify({"record": record})


# ---------------------------------------------------------------------------
# Routes -- Phase 6C: CSV import
# ---------------------------------------------------------------------------

@app.route("/api/mine/<mine_id>/data/template")
@auth.login_required_api
def api_mine_data_template(mine_id):
    _validate_mine_id(mine_id)
    auth.require_mine_access(g.user, mine_id)
    csv_text = ci.generate_template_csv()
    return app.response_class(
        csv_text, mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={mine_id}_operational_data_template.csv"},
    )


def _read_uploaded_csv():
    if "file" not in request.files:
        raise ci.CsvImportError("No file was uploaded. Select a CSV file first.")
    upload = request.files["file"]
    if not upload or upload.filename == "":
        raise ci.CsvImportError("No file was uploaded. Select a CSV file first.")
    if not upload.filename.lower().endswith(".csv"):
        raise ci.CsvImportError("Only .csv files are accepted.")
    return upload.read()


@app.route("/api/mine/<mine_id>/data/import/preview", methods=["POST"])
@auth.login_required_api
def api_mine_data_import_preview(mine_id):
    _validate_mine_id(mine_id)
    auth.require_mine_write_access(g.user, mine_id)
    file_bytes = _read_uploaded_csv()
    conn = get_connection()
    try:
        report = ci.validate_csv(conn, mine_id, file_bytes)
    finally:
        conn.close()
    report["mine_id"] = mine_id
    return jsonify(report)


@app.route("/api/mine/<mine_id>/data/import/confirm", methods=["POST"])
@auth.login_required_api
def api_mine_data_import_confirm(mine_id):
    _validate_mine_id(mine_id)
    auth.require_mine_write_access(g.user, mine_id)
    file_bytes = _read_uploaded_csv()
    conn = get_connection()
    try:
        result = ci.import_csv(conn, mine_id, file_bytes, user_id=g.user["id"])
    finally:
        conn.close()
    result["mine_id"] = mine_id
    return jsonify(result)


@app.route("/api/mine/<mine_id>/baseline")
@auth.login_required_api
def api_mine_baseline(mine_id):
    _validate_mine_id(mine_id)
    auth.require_mine_access(g.user, mine_id)
    conn = get_connection()
    mine, annual, monthly, provenance_values = _get_baseline(conn, mine_id)
    conn.close()

    return jsonify({
        "mine": dict(mine),
        "baseline_annual": annual,
        "monthly_trend": [
            {
                "period": m["period"],
                "scope1_tco2e": m["scope1_tco2e"],
                "scope2_tco2e": m["scope2_tco2e"],
                "scope3_tco2e": m["scope3_tco2e"],
                "total_tco2e": m["total_tco2e"],
                "intensity_tco2e_per_t": m["intensity_tco2e_per_t"],
            }
            for m in monthly
        ],
        "data_provenance": sorted(provenance_values),
    })


@app.route("/api/mine/<mine_id>/hotspots")
@auth.login_required_api
def api_mine_hotspots(mine_id):
    _validate_mine_id(mine_id)
    auth.require_mine_access(g.user, mine_id)
    conn = get_connection()
    mine = _get_mine_or_404(conn, mine_id)

    # Aggregate activity across the year, then attribute tCO2e by source using
    # the same factors as the carbon engine, so hotspot shares are traceable
    # to the identical calculation used elsewhere (no separate/divergent logic).
    ops_rows = conn.execute("SELECT * FROM operations_monthly WHERE mine_id = ?", (mine_id,)).fetchall()
    if not ops_rows:
        conn.close()
        raise ApiError(f"No operational data available for mine_id '{mine_id}'", status_code=404)

    factors = {row["factor_id"]: row["factor_value"] for row in conn.execute(
        "SELECT factor_id, factor_value FROM emission_factors")}
    conn.close()

    # NULL-safe: Phase 6E's manual/CSV-entered records may legitimately omit
    # optional fields (fugitive methane, transport, commuting), stored as
    # NULL. This aggregation must treat a missing value as 0, exactly like
    # carbon_engine.calculate_period_footprint already does via .get(key, 0.0)
    # -- otherwise a single partially-entered month crashes this endpoint for
    # the whole mine. This is a null-handling fix only; no calculation
    # formula is changed.
    diesel_l = sum(r["diesel_consumption_l"] or 0.0 for r in ops_rows)
    methane_t = sum(r["fugitive_methane_t"] or 0.0 for r in ops_rows)
    elec_kwh = sum(r["electricity_consumption_kwh"] or 0.0 for r in ops_rows)
    renew_share = ops_rows[0]["renewable_electricity_share"] or 0.0
    transport_tkm = sum(r["transport_activity_tkm"] or 0.0 for r in ops_rows)
    commute_pkm = sum(r["commute_activity_pkm"] or 0.0 for r in ops_rows)

    diesel_tco2e = (diesel_l * factors["EF_DIESEL_COMB"]) / 1000.0
    methane_tco2e = (methane_t * 1000.0 * factors["EF_CH4_FUGITIVE"]) / 1000.0
    grid_kwh = elec_kwh * (1 - renew_share)
    elec_tco2e = (grid_kwh * factors["EF_GRID_ELEC"]) / 1000.0
    transport_tco2e = (transport_tkm * factors["EF_ROAD_TRANSPORT"]) / 1000.0
    commute_tco2e = (commute_pkm * factors["EF_EMPLOYEE_COMMUTE"]) / 1000.0

    sources = [
        {"source": "Diesel / Mobile Equipment", "scope": "1", "tco2e": round(diesel_tco2e, 1)},
        {"source": "Fugitive Methane", "scope": "1", "tco2e": round(methane_tco2e, 1)},
        {"source": "Purchased Electricity", "scope": "2", "tco2e": round(elec_tco2e, 1)},
        {"source": "Outbound Road Transport", "scope": "3", "tco2e": round(transport_tco2e, 1)},
        {"source": "Employee Commuting", "scope": "3", "tco2e": round(commute_tco2e, 1)},
    ]
    total = sum(s["tco2e"] for s in sources)
    for s in sources:
        s["pct_of_total"] = round((s["tco2e"] / total * 100.0), 1) if total else 0.0
    sources.sort(key=lambda s: s["tco2e"], reverse=True)
    for i, s in enumerate(sources, start=1):
        s["rank"] = i

    return jsonify({"mine_id": mine_id, "total_tco2e": round(total, 1), "hotspots": sources})


@app.route("/api/interventions")
def api_interventions():
    conn = get_connection()
    interventions = _get_interventions(conn)
    conn.close()
    return jsonify({"interventions": interventions})


@app.route("/api/optimize", methods=["POST"])
@auth.login_required_api
def api_optimize():
    payload = request.get_json(silent=True) or {}
    mine_id = payload.get("mine_id")
    budget_inr = payload.get("budget_inr")
    target_reduction_pct = payload.get("target_reduction_pct")

    _validate_mine_id(mine_id)
    auth.require_mine_access(g.user, mine_id)
    budget_inr = _validate_budget(budget_inr)
    target_reduction_pct = _validate_target(target_reduction_pct)

    conn = get_connection()
    mine, annual, _monthly, provenance_values = _get_baseline(conn, mine_id)
    interventions = _get_interventions(conn)

    result = opt.optimize(annual, interventions, budget_inr, target_reduction_pct)

    # Persist the run for auditability (optimizer_runs / optimizer_selected_interventions)
    cur = conn.execute(
        """INSERT INTO optimizer_runs
           (mine_id, budget_inr, target_reduction_pct, status, recommended_investment_inr,
            achieved_reduction_pct, co2e_avoided_t, residual_emissions_t, cost_per_tco2e_inr,
            baseline_scope1_t, baseline_scope2_t, baseline_scope3_t,
            optimized_scope1_t, optimized_scope2_t, optimized_scope3_t)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            mine_id, budget_inr, target_reduction_pct, result.get("status"),
            result.get("recommended_investment_inr"), result.get("achieved_reduction_pct"),
            result.get("co2e_avoided_t"), result.get("residual_emissions_t"), result.get("cost_per_tco2e_inr"),
            annual["scope1_tco2e"], annual["scope2_tco2e"], annual["scope3_tco2e"],
            result.get("optimized_scopes", {}).get("scope1_tco2e"),
            result.get("optimized_scopes", {}).get("scope2_tco2e"),
            result.get("optimized_scopes", {}).get("scope3_tco2e"),
        ),
    )
    run_id = cur.lastrowid
    for s in result.get("selected_interventions", []):
        conn.execute(
            """INSERT INTO optimizer_selected_interventions
               (run_id, intervention_id, deployment_level, investment_inr, scope1_effect_t, scope2_effect_t, scope3_effect_t, reason)
               VALUES (?,?,?,?,?,?,?,?)""",
            (run_id, s["intervention_id"], s["deployment_level"], s["investment_inr"],
             s["scope1_effect_t"], s["scope2_effect_t"], s["scope3_effect_t"], None),
        )
    conn.commit()
    conn.close()

    result["run_id"] = run_id
    result["mine_id"] = mine_id
    result["mine_name"] = mine["mine_name"]
    result["data_provenance"] = sorted(provenance_values)
    return jsonify(result)


@app.route("/api/simulate", methods=["POST"])
@auth.login_required_api
def api_simulate():
    """
    Manual scenario simulation: the user supplies specific deployment levels
    per intervention (rather than letting the optimizer search for the
    minimum-cost combination). Uses the SAME effect-application logic as the
    optimizer (optimizer._apply_combination) so simulated results are never
    computed by a separate, potentially divergent code path.
    """
    payload = request.get_json(silent=True) or {}
    mine_id = payload.get("mine_id")
    deployments = payload.get("deployments")  # {intervention_id: level}

    _validate_mine_id(mine_id)
    auth.require_mine_access(g.user, mine_id)
    if not isinstance(deployments, dict):
        raise ApiError("deployments must be an object of {intervention_id: level}", status_code=400)

    conn = get_connection()
    mine, annual, _monthly, provenance_values = _get_baseline(conn, mine_id)
    all_interventions = _get_interventions(conn)
    conn.close()

    by_id = {i["intervention_id"]: i for i in all_interventions}
    ordered_interventions = []
    levels = []
    for interv_id, level in deployments.items():
        if interv_id not in by_id:
            raise ApiError(f"Unknown intervention_id '{interv_id}'", status_code=400)
        try:
            level = float(level)
        except (TypeError, ValueError):
            raise ApiError(f"Deployment level for '{interv_id}' must be a number", status_code=400)
        interv = by_id[interv_id]
        if level < 0 or level > interv["max_deployment"] + 1e-9:
            raise ApiError(
                f"Deployment level for '{interv_id}' must be between 0 and {interv['max_deployment']}",
                status_code=400,
            )
        ordered_interventions.append(interv)
        levels.append(level)

    optimized, cost, effects = opt._apply_combination(annual, ordered_interventions, levels)
    reduction_t = round(annual["total_tco2e"] - optimized["total_tco2e"], 3)
    reduction_pct = round((reduction_t / annual["total_tco2e"] * 100.0), 2) if annual["total_tco2e"] else 0.0

    return jsonify({
        "mine_id": mine_id,
        "mode": "SCENARIO_SIMULATION",
        "baseline_scopes": annual,
        "simulated_scopes": optimized,
        "investment_inr": cost,
        "co2e_avoided_t": reduction_t,
        "reduction_pct": reduction_pct,
        "residual_emissions_t": optimized["total_tco2e"],
        "intervention_effects": effects,
        "data_provenance": sorted(provenance_values),
        "disclaimer": "Simulated values under prototype assumptions; not a measurement of actual mine performance.",
    })


@app.route("/api/mine/<mine_id>/roadmap")
@auth.login_required_api
def api_mine_roadmap(mine_id):
    _validate_mine_id(mine_id)
    auth.require_mine_access(g.user, mine_id)
    conn = get_connection()
    _get_mine_or_404(conn, mine_id)
    rows = conn.execute(
        "SELECT * FROM net_zero_roadmap WHERE mine_id = ? ORDER BY year", (mine_id,)
    ).fetchall()
    conn.close()
    if not rows:
        raise ApiError(f"No roadmap available for mine_id '{mine_id}'", status_code=404)
    return jsonify({"mine_id": mine_id, "roadmap": [dict(r) for r in rows]})


@app.route("/api/emission-factors")
def api_emission_factors():
    """Read-only exposure of the reference emission-factor table for the Data & Methodology page."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM emission_factors").fetchall()
    conn.close()
    return jsonify({"emission_factors": [dict(r) for r in rows]})


@app.route("/api/mine/<mine_id>/calculation-sample")
@auth.login_required_api
def api_calculation_sample(mine_id):
    """
    Returns one period's full activity -> emission-factor -> CO2e breakdown for
    the Data & Methodology page, so the traceability claim (activity x factor =
    calculation) can be shown with real numbers rather than described only in prose.
    """
    _validate_mine_id(mine_id)
    auth.require_mine_access(g.user, mine_id)
    conn = get_connection()
    _get_mine_or_404(conn, mine_id)
    calc = conn.execute(
        "SELECT * FROM emission_calculations_monthly WHERE mine_id = ? ORDER BY period LIMIT 1",
        (mine_id,),
    ).fetchone()
    if calc is None:
        conn.close()
        raise ApiError(f"No calculation available for mine_id '{mine_id}'", status_code=404)
    activity = conn.execute(
        "SELECT * FROM operations_monthly WHERE mine_id = ? AND period = ?",
        (mine_id, calc["period"]),
    ).fetchone()
    conn.close()

    try:
        detail = json.loads(calc["calc_detail_json"]) if calc["calc_detail_json"] else None
    except (ValueError, TypeError):
        detail = None

    return jsonify({
        "mine_id": mine_id,
        "period": calc["period"],
        "activity": dict(activity) if activity else None,
        "calculation_detail": detail,
        "result": {
            "scope1_tco2e": calc["scope1_tco2e"],
            "scope2_tco2e": calc["scope2_tco2e"],
            "scope3_tco2e": calc["scope3_tco2e"],
            "total_tco2e": calc["total_tco2e"],
            "intensity_tco2e_per_t": calc["intensity_tco2e_per_t"],
        },
        "provenance": calc["provenance"],
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5055, debug=False)
