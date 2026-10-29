"""Compact rural hospital lists without demographics or distance analysis."""

import re

from app.services import financial_store
from app.services.cms_service import get_hospitals_by_state, normalize_county
from app.services.cost_report_service import (
    get_financial_data_by_hospital,
    get_latest_report_year,
    select_primary_row,
)
from app.utils.state_utils import normalize_state


def _state_reports(state, year):
    """Read one complete financial snapshot in one query; None means uncovered."""
    rows = financial_store._read(
        """SELECT r.raw_record FROM hospital_data.financial_coverage c
        JOIN hospital_data.financial_import_runs i ON i.id=c.active_run_id
          AND i.state=c.state AND i.dataset_year=c.dataset_year
        LEFT JOIN hospital_data.financial_report_rows r ON r.run_id=i.id
        WHERE c.state=%s AND c.dataset_year=%s AND i.status='complete'
        ORDER BY r.source_row_number""",
        (state, year),
    )
    if not rows:
        return None
    grouped = {}
    for (raw,) in rows:
        if raw is None:
            continue
        facility_id = raw.get("Provider CCN")
        if facility_id not in grouped:
            grouped[facility_id] = []
        grouped[facility_id].append(raw)
    return grouped


def list_rural_hospitals(state, county=None, zip_code=None, limit=5, year=None):
    """Filter directory locations and apply the existing CMS report rural rule."""
    # Validate filters before accessing data. County and ZIP intersect.
    state_code = normalize_state(state)
    county_key = None
    if county is not None:
        county_key = normalize_county(county)
    if zip_code is not None:
        if not isinstance(zip_code, str) or not re.fullmatch(
            r"[0-9]{5}", zip_code.strip()
        ):
            raise ValueError("zip_code must be a five-digit string.")
        zip_code = zip_code.strip()
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be an integer between 1 and 50.")
    if year is not None:
        if (
            isinstance(year, bool)
            or not isinstance(year, int)
            or not 2011 <= year <= 2100
        ):
            raise ValueError("year must be an integer between 2011 and 2100.")

    # Load the directory and one state snapshot instead of querying every CCN.
    directory = get_hospitals_by_state(state_code)
    if year is None:
        year = get_latest_report_year()
    grouped = None
    mode = financial_store.data_mode()
    if mode != "live":
        try:
            grouped = _state_reports(state_code, year)
        except financial_store.FinancialStoreUnavailable:
            if mode == "database_only":
                raise
        if grouped is None and mode == "database_only":
            raise financial_store.FinancialStoreUnavailable(
                f"Financial snapshot for {state_code}, {year} has not been imported."
            )

    # Select a deterministic alphabetical sample, preserving unknown classifications.
    directory.sort(key=lambda row: (row.get("facility_name") or "", row["facility_id"]))
    hospitals = []
    unknown_count = 0
    matched_count = 0
    seen = set()
    for row in directory:
        facility_id = row["facility_id"]
        if facility_id in seen or row.get("state", "").upper() != state_code:
            continue
        seen.add(facility_id)
        county_label = row.get("countyparish")
        if county_key is not None:
            if not county_label or normalize_county(county_label) != county_key:
                continue
        if zip_code is not None:
            stored_zip = str(row.get("zip_code") or "").strip()
            if not re.fullmatch(r"[0-9]{5}(?:-[0-9]{4})?", stored_zip):
                continue
            if stored_zip[:5] != zip_code:
                continue
        matched_count += 1
        code = None
        if grouped is not None:
            primary = select_primary_row(grouped.get(facility_id, []))
            if primary is not None:
                code = primary.get("Rural Versus Urban")
        else:
            record = get_financial_data_by_hospital(facility_id, year=year)
            if record is not None:
                code = record.rural_versus_urban
        code = str(code or "").strip().upper()
        if code not in ("R", "U"):
            unknown_count += 1
            continue
        if code == "R":
            hospitals.append(
                {
                    "facility_id": facility_id,
                    "facility_name": row["facility_name"],
                    "city": row.get("citytown"),
                    "county": county_label,
                    "state": state_code,
                    "zip_code": row.get("zip_code"),
                }
            )

    # Return compact results with dated classification and explicit coverage.
    storage = "live"
    if grouped is not None:
        storage = "postgresql_snapshot"
    return {
        "report_kind": "rural_hospital_list",
        "state": state_code,
        "county": county_key,
        "zip_code": zip_code,
        "classification_year": year,
        "classification_source": "CMS Hospital Provider Cost Report: Rural Versus Urban",
        "classification_rule": "R = rural; U = urban; missing/unrecognized = unknown",
        "storage": storage,
        "matched_directory_count": matched_count,
        "confirmed_rural_count": len(hospitals),
        "unknown_classification_count": unknown_count,
        "limit": limit,
        "returned_count": len(hospitals[:limit]),
        "hospitals": hospitals[:limit],
        "snapshot_note": "Classification describes the selected dataset year, not a live rural status check.",
    }
