"""
csv_import.py

Phase 6C: CSV import for monthly operational data. Reuses
operational_data.validate_payload() and .recalc_period() directly for every
row -- validation and carbon-engine recalculation are never duplicated here.

WORKFLOW: upload -> parse -> validate -> preview (no DB writes) -> explicit
confirm -> re-parse + re-validate (never trust a client-echoed "already
validated" payload) -> if all rows valid, import atomically -> recalculate.
If any row is invalid at confirm time, ZERO rows are imported.

SECURITY: the mine a file is imported into is always the mine_id in the
URL/route, authorized via auth.require_mine_write_access before this module
is ever called. The CSV format deliberately has NO mine_id column, so an
uploaded file can never claim a different mine than the one the URL and
the caller's authorization already scoped the request to.
"""

import csv
import io

import operational_data as od

TEMPLATE_COLUMNS = [
    "period", "coal_production_t", "diesel_consumption_l", "electricity_consumption_kwh",
    "renewable_electricity_share_pct", "fugitive_methane_t", "transport_activity_tkm",
    "commute_activity_pkm", "provenance", "source_note",
]

REQUIRED_CSV_COLUMNS = {
    "period", "coal_production_t", "diesel_consumption_l",
    "electricity_consumption_kwh", "renewable_electricity_share_pct",
}


class CsvImportError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def generate_template_csv():
    """
    Downloadable CSV template built directly from the operational-data field
    contract (operational_data.FIELD_META) -- not a disconnected, hand-typed
    example. The single example row is explicitly synthetic/for-format-
    illustration only.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(TEMPLATE_COLUMNS)
    writer.writerow([
        "2025-01", "95000", "620000", "1150000", "6.0", "2.5", "400000", "160000",
        "measured", "EXAMPLE ROW - replace with real data, do not import as-is",
    ])
    return buf.getvalue()


def _parse_csv_bytes(file_bytes):
    if not file_bytes or not file_bytes.strip():
        raise CsvImportError("The uploaded file is empty.")
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CsvImportError("The file could not be read as text. Please upload a UTF-8 encoded CSV file.")

    try:
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise CsvImportError("No header row could be found in the file.")
        rows = list(reader)
    except csv.Error as e:
        raise CsvImportError(f"The file could not be parsed as CSV: {e}")

    fieldnames_clean = {f.strip() for f in fieldnames if f}
    missing = REQUIRED_CSV_COLUMNS - fieldnames_clean
    if missing:
        raise CsvImportError(
            f"Missing required column(s): {', '.join(sorted(missing))}. "
            f"Download the template for the exact expected columns."
        )

    unexpected = fieldnames_clean - set(TEMPLATE_COLUMNS)
    if unexpected:
        raise CsvImportError(
            f"Unrecognized column(s): {', '.join(sorted(unexpected))}. "
            f"Download the template for the exact expected column names -- only those columns are accepted."
        )

    if not rows:
        raise CsvImportError("The file has a header row but no data rows.")

    return rows


def _row_to_payload(raw_row):
    """Maps a raw CSV row dict to the payload shape operational_data.validate_payload expects."""

    def clean(key):
        v = raw_row.get(key)
        return v.strip() if isinstance(v, str) else v

    payload = {
        "period": clean("period"),
        "coal_production_t": clean("coal_production_t") or None,
        "diesel_consumption_l": clean("diesel_consumption_l") or None,
        "electricity_consumption_kwh": clean("electricity_consumption_kwh") or None,
        "renewable_electricity_share": clean("renewable_electricity_share_pct") or None,
        "fugitive_methane_t": clean("fugitive_methane_t") or None,
        "transport_activity_tkm": clean("transport_activity_tkm") or None,
        "commute_activity_pkm": clean("commute_activity_pkm") or None,
        "provenance": clean("provenance") or "measured",
        "source_type": "csv_import",
        "source_note": clean("source_note") or None,
    }
    return payload


def validate_csv(conn, mine_id, file_bytes):
    """
    Parses and validates the uploaded file WITHOUT writing anything to the
    database. Returns a structured report used for both the preview response
    and, at confirm time, re-validated fresh before any write happens.
    """
    raw_rows = _parse_csv_bytes(file_bytes)

    existing_periods = {
        r["period"] for r in conn.execute(
            "SELECT period FROM operations_monthly WHERE mine_id = ?", (mine_id,)
        ).fetchall()
    }

    seen_periods_in_file = {}
    results = []
    valid_count = 0
    error_count = 0
    warning_count = 0

    for idx, raw_row in enumerate(raw_rows):
        row_num = idx + 2  # 1-indexed rows, +1 for the header line
        payload = _row_to_payload(raw_row)
        period = payload.get("period")

        row_result = {"row": row_num, "period": period, "status": "valid", "error": None, "warnings": []}

        # Duplicate within the same file
        if period and period in seen_periods_in_file:
            row_result["status"] = "error"
            row_result["error"] = f"Duplicate period '{period}' also appears at row {seen_periods_in_file[period]} in this file."
            results.append(row_result)
            error_count += 1
            continue

        # Duplicate of an existing DB record -- insert-only policy, never silently overwritten
        if period and period in existing_periods:
            row_result["status"] = "error"
            row_result["error"] = (
                f"A record for {mine_id} / {period} already exists. "
                f"CSV import does not overwrite existing records -- edit it on the Operational Data page instead."
            )
            results.append(row_result)
            error_count += 1
            if period:
                seen_periods_in_file[period] = row_num
            continue

        try:
            cleaned = od.validate_payload(payload, existing=None)
            row_result["data"] = cleaned
            if period:
                seen_periods_in_file[period] = row_num
            status, reasons = od.compute_data_quality(cleaned)
            if reasons:
                row_result["warnings"] = reasons
                warning_count += 1
            valid_count += 1
        except od.ValidationError as e:
            row_result["status"] = "error"
            row_result["error"] = e.message
            error_count += 1

        results.append(row_result)

    return {
        "total_rows": len(raw_rows),
        "valid_rows": valid_count,
        "invalid_rows": error_count,
        "warning_rows": warning_count,
        "rows": results,
        "can_import": error_count == 0 and valid_count > 0,
    }


def import_csv(conn, mine_id, file_bytes, user_id):
    """
    Re-parses and re-validates the file (never trusts a prior preview blindly),
    then performs the import as a single atomic transaction: if validation
    finds ANY error, zero rows are written. If an unexpected DB error occurs
    mid-import, the whole transaction is rolled back -- never a partial import.
    """
    report = validate_csv(conn, mine_id, file_bytes)

    if not report["can_import"]:
        raise CsvImportError(
            f"Import rejected: {report['invalid_rows']} row(s) failed validation. "
            f"Zero rows were imported. Fix the errors and re-upload.",
        )

    valid_rows = [r for r in report["rows"] if r["status"] == "valid"]

    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN")
    try:
        for row in valid_rows:
            cleaned = row["data"]
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
    except Exception:
        conn.rollback()
        raise CsvImportError("Import failed due to an unexpected database error. No rows were saved.", status_code=500)

    recalculated_periods = []
    calculations = []
    for row in valid_rows:
        period = row["data"]["period"]
        od.recalc_period(conn, mine_id, period)
        recalculated_periods.append(period)
        calc_row = conn.execute(
            "SELECT scope1_tco2e, scope2_tco2e, scope3_tco2e, total_tco2e, intensity_tco2e_per_t "
            "FROM emission_calculations_monthly WHERE mine_id = ? AND period = ?",
            (mine_id, period),
        ).fetchone()
        calculations.append({"period": period, **(dict(calc_row) if calc_row else {})})

    return {
        "rows_imported": len(valid_rows),
        "periods_imported": [r["data"]["period"] for r in valid_rows],
        "calculations_updated": len(recalculated_periods),
        "calculations": calculations,  # per-period Scope 1/2/3/Total/Intensity, for the import-result confirmation
    }
