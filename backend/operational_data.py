"""
operational_data.py

Phase 6B: monthly operational data entry for a mine, using EXACTLY the
fields carbon_engine.calculate_period_footprint() already consumes -- no
new calculation inputs are invented here. After any create/edit, the
affected period is recalculated through the existing, already-tested
carbon engine (never duplicated in this module or in JavaScript), and the
result is written to emission_calculations_monthly so the dashboard,
hotspots, simulator, and optimizer immediately see the new baseline.
"""

import re
import json

import carbon_engine as ce

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Every one of these keys is consumed directly by carbon_engine.calculate_period_footprint.
REQUIRED_FIELDS = ["coal_production_t", "diesel_consumption_l", "electricity_consumption_kwh",
                   "renewable_electricity_share"]
OPTIONAL_FIELDS = ["fugitive_methane_t", "transport_activity_tkm", "commute_activity_pkm"]
ALL_ACTIVITY_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

FIELD_META = {
    "coal_production_t":            {"label": "Coal Production", "unit": "tonnes", "required": True},
    "diesel_consumption_l":         {"label": "Diesel Consumption", "unit": "litres", "required": True},
    "electricity_consumption_kwh":  {"label": "Electricity Consumption", "unit": "kWh", "required": True},
    "renewable_electricity_share":  {"label": "Renewable Electricity Share", "unit": "% of electricity", "required": True},
    "fugitive_methane_t":           {"label": "Fugitive Methane", "unit": "tonnes CH4", "required": False},
    "transport_activity_tkm":       {"label": "Road Transport Activity", "unit": "tonne-km", "required": False},
    "commute_activity_pkm":         {"label": "Employee Commuting Activity", "unit": "passenger-km", "required": False},
}

# 'reference' and 'synthetic_prototype' are reserved for the platform's own
# seed/reference data; 'verified' is reserved for a genuinely validated
# workflow this phase does not implement. Manual entry may only claim
# 'measured' (an operator's actual reading) or 'provisional' (an estimate).
ALLOWED_MANUAL_PROVENANCE = {"measured", "provisional"}
ALLOWED_SOURCE_TYPES = {"manual_entry", "csv_import", "api", "sensor", "reference"}


class ValidationError(Exception):
    def __init__(self, message, status_code=400, field_errors=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.field_errors = field_errors or {}


def _validate_period(period):
    if not period or not PERIOD_RE.match(str(period)):
        raise ValidationError("Period must be in YYYY-MM format (e.g. 2025-04).",
                               field_errors={"period": "Invalid or missing period (expected YYYY-MM)."})
    return period


def _validate_numeric(value, field, required, min_val=None, max_val=None):
    if value in (None, ""):
        if required:
            raise ValidationError(
                f"{FIELD_META[field]['label']} is required.",
                field_errors={field: "This field is required."},
            )
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValidationError(
            f"{FIELD_META[field]['label']} must be a number.",
            field_errors={field: "Expected a numeric value."},
        )
    if value < 0:
        raise ValidationError(
            f"{FIELD_META[field]['label']} cannot be negative.",
            field_errors={field: "Value cannot be negative."},
        )
    if min_val is not None and value < min_val:
        raise ValidationError(f"{FIELD_META[field]['label']} is below the allowed minimum.",
                               field_errors={field: f"Must be >= {min_val}."})
    if max_val is not None and value > max_val:
        raise ValidationError(f"{FIELD_META[field]['label']} is above the allowed maximum.",
                               field_errors={field: f"Must be <= {max_val}."})
    return value


def _validate_renewable_share_pct(value, required):
    """UI sends a 0-100 percentage; stored internally as a 0-1 fraction (matching
    the existing schema/carbon_engine convention already used by the seed data)."""
    pct = _validate_numeric(value, "renewable_electricity_share", required, min_val=0, max_val=100)
    if pct is None:
        return None
    return round(pct / 100.0, 6)


def _validate_provenance(value):
    value = (value or "measured").strip().lower()
    if value not in ALLOWED_MANUAL_PROVENANCE:
        raise ValidationError(
            f"Provenance for manually entered data must be one of: {', '.join(sorted(ALLOWED_MANUAL_PROVENANCE))}.",
            field_errors={"provenance": "Invalid provenance for manual entry."},
        )
    return value


def _validate_source_type(value):
    value = (value or "manual_entry").strip().lower()
    if value not in ALLOWED_SOURCE_TYPES:
        raise ValidationError("Invalid source type.", field_errors={"source_type": "Invalid source type."})
    return value


def validate_payload(payload, existing=None):
    """
    Validates a create/edit payload. `existing` is the current DB row (as a
    dict) when editing, used to fall back to current values for any field
    the payload omits (partial update support), and to preserve mine_id/period.
    """
    period = payload.get("period", existing["period"] if existing else None)
    period = _validate_period(period)

    cleaned = {"period": period}

    for field in REQUIRED_FIELDS:
        if field in payload:
            raw = payload.get(field)
        elif existing is not None:
            raw = existing.get(field)
        else:
            raw = None
        if field == "renewable_electricity_share":
            # existing DB value is stored as a fraction; incoming payload value is a percentage
            if field in payload:
                cleaned[field] = _validate_renewable_share_pct(raw, required=True)
            else:
                cleaned[field] = _validate_numeric(raw, field, required=True, min_val=0, max_val=1)
        else:
            cleaned[field] = _validate_numeric(raw, field, required=True)

    for field in OPTIONAL_FIELDS:
        if field in payload:
            raw = payload.get(field)
        elif existing is not None:
            raw = existing.get(field)
        else:
            raw = None
        cleaned[field] = _validate_numeric(raw, field, required=False)

    provenance_input = payload.get("provenance") if "provenance" in payload else (existing["provenance"] if existing else None)
    cleaned["provenance"] = _validate_provenance(provenance_input)

    source_type_input = payload.get("source_type") if "source_type" in payload else (existing["source_type"] if existing else None)
    cleaned["source_type"] = _validate_source_type(source_type_input)

    cleaned["source_note"] = (payload.get("source_note") if "source_note" in payload
                               else (existing["source_note"] if existing else None))
    if cleaned["source_note"]:
        cleaned["source_note"] = str(cleaned["source_note"]).strip()[:1000] or None

    return cleaned


def compute_data_quality(record):
    """
    Backend-driven, formula-free quality status: GOOD / WARNING / INCOMPLETE.
    No fabricated percentage score -- just the actual completeness/validity
    picture, with reasons for anything short of GOOD.
    """
    missing_required = [f for f in REQUIRED_FIELDS if record.get(f) is None]
    if missing_required:
        return "INCOMPLETE", [f"Missing required field: {FIELD_META[f]['label']}" for f in missing_required]

    reasons = []
    for f in OPTIONAL_FIELDS:
        if record.get(f) is None:
            reasons.append(f"{FIELD_META[f]['label']} not recorded")
    if record.get("provenance") == "provisional":
        reasons.append("Marked provisional -- not yet confirmed as an actual measured reading")

    if reasons:
        return "WARNING", reasons
    return "GOOD", []


def _period_to_ordinal(period):
    """'YYYY-MM' -> a monotonic integer (year*12+month) for gap arithmetic."""
    year, month = period.split("-")
    return int(year) * 12 + int(month)


def _find_reporting_gaps(periods):
    """
    Given a list of 'YYYY-MM' period strings, returns the sorted list of
    months missing between the earliest and latest reported period
    (inclusive range), e.g. ['2025-01','2025-02','2025-04'] -> ['2025-03'].
    An empty or single-period list has no possible gap.
    """
    if len(periods) < 2:
        return []
    ordinals = sorted(_period_to_ordinal(p) for p in periods)
    present = set(ordinals)
    gaps = []
    for o in range(ordinals[0], ordinals[-1] + 1):
        if o not in present:
            year, month = divmod(o, 12)
            if month == 0:
                year, month = year - 1, 12
            gaps.append(f"{year:04d}-{month:02d}")
    return gaps


def compute_mine_data_quality(records):
    """
    Mine-level data-quality summary, distinct from (and built on top of) the
    existing per-record compute_data_quality(). This is the genuinely new
    Phase 6G piece: it looks across ALL of a mine's recorded months for
    reporting continuity/gaps and overall completeness -- something no
    single record's status can express on its own.

    Returns (status, reasons) with status in GOOD / WARNING / INCOMPLETE.
    No fabricated percentage score -- only real, checkable conditions.
    """
    if not records:
        return "INCOMPLETE", ["No operational data recorded for this mine yet."]

    reasons = []
    incomplete = [r for r in records if r.get("data_quality_status") == "INCOMPLETE"]
    warning = [r for r in records if r.get("data_quality_status") == "WARNING"]

    if incomplete:
        reasons.append(f"{len(incomplete)} month(s) have missing required fields.")

    periods = [r["period"] for r in records]
    gaps = _find_reporting_gaps(periods)
    if gaps:
        reasons.append(
            f"{len(gaps)} reporting month(s) missing between {min(periods)} and {max(periods)}: "
            f"{', '.join(gaps[:6])}{'...' if len(gaps) > 6 else ''}"
        )

    if warning and not incomplete:
        reasons.append(f"{len(warning)} month(s) flagged with data warnings (see monthly detail).")

    all_synthetic = all(r.get("provenance") == "synthetic_prototype" for r in records)
    if all_synthetic:
        reasons.append("All recorded data is synthetic prototype (demonstration dataset) -- not measured mine data.")

    if incomplete:
        return "INCOMPLETE", reasons
    if reasons:
        return "WARNING", reasons
    return "GOOD", []


def recalc_period(conn, mine_id, period):
    """
    Recomputes Scope 1/2/3 for exactly one (mine_id, period) using the
    EXISTING carbon_engine, and upserts the result into
    emission_calculations_monthly. This is the only place operational data
    changes translate into emission figures -- dashboard, hotspots,
    simulator and optimizer all read emission_calculations_monthly, so they
    automatically reflect the new baseline without any separate wiring.
    """
    op_row = conn.execute(
        "SELECT * FROM operations_monthly WHERE mine_id = ? AND period = ?", (mine_id, period)
    ).fetchone()
    if op_row is None:
        return None

    factors = {r["factor_id"]: r["factor_value"] for r in conn.execute(
        "SELECT factor_id, factor_value FROM emission_factors")}

    activity = {f: (op_row[f] if op_row[f] is not None else 0.0) for f in ALL_ACTIVITY_FIELDS}
    activity["coal_production_t"] = op_row["coal_production_t"]  # keep raw (may be None) for intensity guard

    result = ce.calculate_period_footprint(activity, factors)

    conn.execute(
        """INSERT INTO emission_calculations_monthly
           (mine_id, period, scope1_tco2e, scope2_tco2e, scope3_tco2e, total_tco2e,
            intensity_tco2e_per_t, calc_detail_json, provenance)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(mine_id, period) DO UPDATE SET
               scope1_tco2e=excluded.scope1_tco2e, scope2_tco2e=excluded.scope2_tco2e,
               scope3_tco2e=excluded.scope3_tco2e, total_tco2e=excluded.total_tco2e,
               intensity_tco2e_per_t=excluded.intensity_tco2e_per_t,
               calc_detail_json=excluded.calc_detail_json, provenance=excluded.provenance""",
        (mine_id, period, result["scope1_tco2e"], result["scope2_tco2e"], result["scope3_tco2e"],
         result["total_tco2e"], result["intensity_tco2e_per_t"], json.dumps(result["calc_detail"]),
         op_row["provenance"]),
    )
    conn.commit()
    return result


def _resolve_user_name(conn, user_id):
    if not user_id:
        return None
    row = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["name"] if row else None


def _row_with_quality(conn, row):
    """
    Phase 6H: resolves created_by/updated_by (raw user ids) into human-
    readable names, matching the exact created_by_name/updated_by_name
    pattern already established for mines in mine_management.py -- this is
    the same auditability convention, extended to operational records.
    """
    record = dict(row)
    status, reasons = compute_data_quality(record)
    record["data_quality_status"] = status
    record["data_quality_reasons"] = reasons
    if record.get("renewable_electricity_share") is not None:
        record["renewable_electricity_share_pct"] = round(record["renewable_electricity_share"] * 100.0, 3)
    else:
        record["renewable_electricity_share_pct"] = None
    record["created_by_name"] = _resolve_user_name(conn, record.get("created_by"))
    record["updated_by_name"] = _resolve_user_name(conn, record.get("updated_by"))
    return record


def list_records(conn, mine_id):
    rows = conn.execute(
        "SELECT * FROM operations_monthly WHERE mine_id = ? ORDER BY period", (mine_id,)
    ).fetchall()
    return [_row_with_quality(conn, r) for r in rows]


def get_record(conn, mine_id, record_id):
    row = conn.execute(
        "SELECT * FROM operations_monthly WHERE mine_id = ? AND id = ?", (mine_id, record_id)
    ).fetchone()
    return _row_with_quality(conn, row) if row else None


def create_record(conn, mine_id, payload, user_id):
    cleaned = validate_payload(payload, existing=None)

    dup = conn.execute(
        "SELECT id FROM operations_monthly WHERE mine_id = ? AND period = ?", (mine_id, cleaned["period"])
    ).fetchone()
    if dup is not None:
        raise ValidationError(
            f"A record for {mine_id} / {cleaned['period']} already exists. Edit the existing record instead.",
            status_code=409, field_errors={"period": "A record for this month already exists."},
        )

    conn.execute(
        """INSERT INTO operations_monthly
           (mine_id, period, coal_production_t, diesel_consumption_l, electricity_consumption_kwh,
            renewable_electricity_share, transport_activity_tkm, commute_activity_pkm, fugitive_methane_t,
            provenance, source_type, source_note, created_by, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
        (mine_id, cleaned["period"], cleaned["coal_production_t"], cleaned["diesel_consumption_l"],
         cleaned["electricity_consumption_kwh"], cleaned["renewable_electricity_share"],
         cleaned["transport_activity_tkm"], cleaned["commute_activity_pkm"], cleaned["fugitive_methane_t"],
         cleaned["provenance"], cleaned["source_type"], cleaned["source_note"], user_id),
    )
    conn.commit()

    recalc_period(conn, mine_id, cleaned["period"])

    row = conn.execute(
        "SELECT * FROM operations_monthly WHERE mine_id = ? AND period = ?", (mine_id, cleaned["period"])
    ).fetchone()
    result = _row_with_quality(conn, row)
    calc_row = conn.execute(
        "SELECT scope1_tco2e, scope2_tco2e, scope3_tco2e, total_tco2e, intensity_tco2e_per_t "
        "FROM emission_calculations_monthly WHERE mine_id = ? AND period = ?",
        (mine_id, cleaned["period"]),
    ).fetchone()
    result["calculation"] = dict(calc_row) if calc_row else None  # additive: surfaces the calculated emissions
    return result


def update_record(conn, mine_id, record_id, payload, user_id):
    existing = conn.execute(
        "SELECT * FROM operations_monthly WHERE mine_id = ? AND id = ?", (mine_id, record_id)
    ).fetchone()
    if existing is None:
        raise ValidationError(f"No operational record #{record_id} found for mine '{mine_id}'.", status_code=404)
    existing = dict(existing)

    cleaned = validate_payload(payload, existing=existing)

    if cleaned["period"] != existing["period"]:
        dup = conn.execute(
            "SELECT id FROM operations_monthly WHERE mine_id = ? AND period = ? AND id != ?",
            (mine_id, cleaned["period"], record_id),
        ).fetchone()
        if dup is not None:
            raise ValidationError(
                f"A record for {mine_id} / {cleaned['period']} already exists.",
                status_code=409, field_errors={"period": "A record for this month already exists."},
            )

    conn.execute(
        """UPDATE operations_monthly
           SET period=?, coal_production_t=?, diesel_consumption_l=?, electricity_consumption_kwh=?,
               renewable_electricity_share=?, transport_activity_tkm=?, commute_activity_pkm=?,
               fugitive_methane_t=?, provenance=?, source_type=?, source_note=?,
               updated_at=datetime('now'), updated_by=?
           WHERE mine_id = ? AND id = ?""",
        (cleaned["period"], cleaned["coal_production_t"], cleaned["diesel_consumption_l"],
         cleaned["electricity_consumption_kwh"], cleaned["renewable_electricity_share"],
         cleaned["transport_activity_tkm"], cleaned["commute_activity_pkm"], cleaned["fugitive_methane_t"],
         cleaned["provenance"], cleaned["source_type"], cleaned["source_note"], user_id, mine_id, record_id),
    )
    conn.commit()

    # If the period itself changed, the OLD emission_calculations_monthly row
    # for the old period is now stale (no operational data backs it anymore);
    # remove it so the mine's aggregated baseline doesn't double-count.
    if cleaned["period"] != existing["period"]:
        conn.execute(
            "DELETE FROM emission_calculations_monthly WHERE mine_id = ? AND period = ?",
            (mine_id, existing["period"]),
        )
        conn.commit()

    recalc_period(conn, mine_id, cleaned["period"])

    row = conn.execute("SELECT * FROM operations_monthly WHERE mine_id = ? AND id = ?", (mine_id, record_id)).fetchone()
    result = _row_with_quality(conn, row)
    calc_row = conn.execute(
        "SELECT scope1_tco2e, scope2_tco2e, scope3_tco2e, total_tco2e, intensity_tco2e_per_t "
        "FROM emission_calculations_monthly WHERE mine_id = ? AND period = ?",
        (mine_id, cleaned["period"]),
    ).fetchone()
    result["calculation"] = dict(calc_row) if calc_row else None
    return result
