"""
Access to the CMS Hospital Provider Cost Report datasets.

CMS publishes one dataset per cost-report year (2011 onward) and
re-issues dataset UUIDs without notice: every ID changed on
2026-09-30 and three more changed again on 2026-10-05. Dataset IDs
are therefore discovered at runtime from the CMS catalog
(https://data.cms.gov/data.json) and refreshed automatically when a
cached ID starts returning 404. A snapshot of the catalog is kept
as a fallback for when the catalog itself cannot be reached.
"""

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests
from cachetools import TTLCache

from app.models.financial import HospitalFinancialRecord


logger = logging.getLogger(__name__)


CMS_CATALOG_URL = "https://data.cms.gov/data.json"

CMS_DATASET_DATA_URL = (
    "https://data.cms.gov/data-api/v1/dataset/{dataset_id}/data"
)

COST_REPORT_TITLE_PATTERN = re.compile(
    r"^Hospital Provider Cost Report : (\d{4})-"
)

DATASET_ID_PATTERN = re.compile(
    r"dataset/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}"
    r"-[0-9a-f]{4}-[0-9a-f]{12})"
)

# Snapshot of the CMS catalog taken on 2026-10-05. Used only when
# the live catalog cannot be downloaded. The live catalog always
# takes precedence because CMS rotates these IDs.
FALLBACK_COST_REPORT_DATASETS: dict[int, str] = {
    2011: "0a31449d-f83f-4873-ba85-22accb8092ec",
    2012: "03e9562b-7424-430b-87d8-1901959b84d0",
    2013: "e4d392f3-f91d-4e04-8308-33adc098cae1",
    2014: "fa5caf84-7fef-453b-845f-d4e28e80d98e",
    2015: "56c94ab5-aafe-41d8-adc3-1c02269970c6",
    2016: "b2af4307-65aa-40fb-a6ff-88d05a919fd2",
    2017: "62b6b160-3f7f-4a31-898e-996a410fc9a1",
    2018: "2caad1a6-e674-47ce-84e7-d14a945e38c9",
    2019: "90a10951-7457-4dc8-849d-4b344840f9c8",
    2020: "4ebc26db-f8f2-4f7e-89cd-a5bc84dcbfbd",
    2021: "98b7383e-ad67-44d5-a7d8-0a80a92a72c1",
    2022: "8457c184-a531-40db-8597-2497fec80c7a",
    2023: "f08d4c46-c0e4-4bcb-a54a-c62c87d59251",
    2024: "44060663-47d8-4ced-a115-b53b4c270acb",
}

CATALOG_TTL_SECONDS = 6 * 60 * 60
CATALOG_REFRESH_COOLDOWN_SECONDS = 5 * 60
CATALOG_TIMEOUT_SECONDS = 120

REQUEST_TIMEOUT_SECONDS = 30
MAX_ROWS_PER_YEAR = 10
MAX_PARALLEL_YEAR_REQUESTS = 4
MAX_TREND_SPAN_YEARS = 30
DEFAULT_TREND_SPAN_YEARS = 5

# Columns used to decide which row is the "primary" report when a
# hospital has more than one cost report in the same dataset year
# (for example after a change of ownership).
COMPLETENESS_COLUMNS = (
    "Net Patient Revenue",
    "Net Income from Service to Patients",
    "Total Assets",
    "Total Liabilities",
    "Total Days (V + XVIII + XIX + Unknown)",
    "Total Bed Days Available",
    "Cost To Charge Ratio",
)


class CostReportUnavailableError(Exception):
    """Raised when a year's cost-report dataset cannot be retrieved."""

    def __init__(self, year: int, reason: str):
        super().__init__(
            f"Cost report dataset for {year} is unavailable: {reason}"
        )
        self.year = year
        self.reason = reason


@dataclass
class FinancialHistoryResult:
    facility_id: str
    years_requested: list[int]
    records: list[HospitalFinancialRecord]
    years_without_report: list[int] = field(default_factory=list)
    years_unavailable: dict[int, str] = field(default_factory=dict)

    @property
    def years_with_data(self) -> list[int]:
        return [
            record.report_year
            for record in self.records
            if record.report_year is not None
        ]


# region Dataset discovery

_catalog_cache: TTLCache = TTLCache(maxsize=1, ttl=CATALOG_TTL_SECONDS)
_catalog_lock = threading.Lock()
_last_catalog_refresh = 0.0

_rows_cache: TTLCache = TTLCache(maxsize=2000, ttl=60 * 60)
_rows_lock = threading.Lock()


def discover_cost_report_datasets() -> dict[int, str]:
    """
    Download the CMS catalog and return {report_year: dataset_id}
    for every Hospital Provider Cost Report dataset it lists.
    """
    response = requests.get(
        CMS_CATALOG_URL,
        timeout=CATALOG_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    datasets: dict[int, str] = {}

    for entry in response.json().get("dataset", []):
        title_match = COST_REPORT_TITLE_PATTERN.match(
            entry.get("title", "")
        )
        if not title_match:
            continue

        id_match = DATASET_ID_PATTERN.search(
            entry.get("identifier", "")
        )
        if not id_match:
            continue

        datasets[int(title_match.group(1))] = id_match.group(1)

    return datasets


def get_cost_report_datasets(
    force_refresh: bool = False,
) -> dict[int, str]:
    """
    Return {report_year: dataset_id}, cached for CATALOG_TTL_SECONDS.

    force_refresh re-downloads the catalog (subject to a cooldown so
    a burst of 404s cannot hammer CMS). Falls back to the bundled
    snapshot when the catalog cannot be reached.
    """
    global _last_catalog_refresh

    with _catalog_lock:
        cached = _catalog_cache.get("datasets")
        now = time.monotonic()

        if cached is not None:
            if not force_refresh:
                return cached

            within_cooldown = (
                now - _last_catalog_refresh
                < CATALOG_REFRESH_COOLDOWN_SECONDS
            )
            if within_cooldown:
                return cached

        try:
            discovered = discover_cost_report_datasets()
            _last_catalog_refresh = now
            logger.info(
                "CMS cost report catalog loaded: %d datasets (%s-%s)",
                len(discovered),
                min(discovered, default="?"),
                max(discovered, default="?"),
            )
        except (requests.RequestException, ValueError) as error:
            logger.warning(
                "Could not download CMS catalog (%s); "
                "using bundled dataset snapshot",
                error,
            )
            discovered = {}

        datasets = {**FALLBACK_COST_REPORT_DATASETS, **discovered}
        _catalog_cache["datasets"] = datasets

        return datasets


def get_available_report_years() -> list[int]:
    return sorted(get_cost_report_datasets())


def get_latest_report_year() -> int:
    return get_available_report_years()[-1]

# endregion


# region Row retrieval

def _request_rows(
    dataset_id: str,
    facility_id: str,
) -> requests.Response:
    return requests.get(
        CMS_DATASET_DATA_URL.format(dataset_id=dataset_id),
        params={
            "filter[Provider CCN]": facility_id,
            "size": MAX_ROWS_PER_YEAR,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def fetch_cost_report_rows(
    facility_id: str,
    year: int,
) -> list[dict]:
    """
    Raw cost-report rows for one hospital in one dataset year.

    Returns [] when the dataset is reachable but the hospital filed
    no report. Raises CostReportUnavailableError when the dataset
    itself cannot be retrieved, after refreshing the catalog once
    if the cached dataset ID has gone stale (HTTP 404).
    """
    facility_id = facility_id.strip()

    dataset_id = get_cost_report_datasets().get(year)

    if dataset_id is None:
        raise CostReportUnavailableError(
            year,
            "no dataset for this year in the CMS catalog",
        )

    cache_key = (dataset_id, facility_id)

    with _rows_lock:
        cached = _rows_cache.get(cache_key)

    if cached is not None:
        return cached

    try:
        response = _request_rows(dataset_id, facility_id)

        if response.status_code == 404:
            logger.warning(
                "Cost report dataset %s (%d) returned 404; "
                "refreshing CMS catalog",
                dataset_id,
                year,
            )

            refreshed_id = get_cost_report_datasets(
                force_refresh=True,
            ).get(year)

            if refreshed_id and refreshed_id != dataset_id:
                dataset_id = refreshed_id
                cache_key = (dataset_id, facility_id)
                response = _request_rows(dataset_id, facility_id)

        if response.status_code == 404:
            raise CostReportUnavailableError(
                year,
                "dataset ID no longer exists at CMS",
            )

        response.raise_for_status()
        rows = response.json()

    except requests.RequestException as error:
        raise CostReportUnavailableError(year, str(error)) from error

    if not isinstance(rows, list):
        raise CostReportUnavailableError(
            year,
            "unexpected response format from CMS",
        )

    with _rows_lock:
        _rows_cache[cache_key] = rows

    return rows


def select_primary_row(rows: list[dict]) -> dict | None:
    """
    Pick the most complete row, breaking ties by the latest fiscal
    year end date.
    """
    if not rows:
        return None

    def score(row: dict) -> tuple[int, str]:
        completeness = sum(
            1
            for column in COMPLETENESS_COLUMNS
            if str(row.get(column) or "").strip() != ""
        )
        return completeness, str(row.get("Fiscal Year End Date") or "")

    return max(rows, key=score)

# endregion


# region Parsing

def to_optional_float(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    value = str(value).strip()

    if value == "":
        return None

    value = value.replace(",", "")

    return float(value)


def parse_cost_report_row(
    row: dict,
    report_year: int | None = None,
) -> HospitalFinancialRecord:
    return HospitalFinancialRecord(
        facility_id=row["Provider CCN"],
        hospital_name=row["Hospital Name"],
        fiscal_year_begin=row["Fiscal Year Begin Date"],
        fiscal_year_end=row["Fiscal Year End Date"],
        report_year=report_year,

        net_patient_revenue=to_optional_float(
            row.get("Net Patient Revenue")
        ),

        total_operating_expense=to_optional_float(
            row.get("Less Total Operating Expense")
        ),

        net_income_from_service=to_optional_float(
            row.get("Net Income from Service to Patients")
        ),

        net_income=to_optional_float(
            row.get("Net Income")
        ),

        total_assets=to_optional_float(
            row.get("Total Assets")
        ),

        total_liabilities=to_optional_float(
            row.get("Total Liabilities")
        ),

        rural_versus_urban=row.get(
            "Rural Versus Urban"
        ),

        number_of_beds=to_optional_float(
            row.get("Number of Beds")
        ),

        total_days=to_optional_float(
            row.get(
                "Total Days (V + XVIII + XIX + Unknown)"
            )
        ),

        total_bed_days_available=to_optional_float(
            row.get("Total Bed Days Available")
        ),

        total_discharges=to_optional_float(
            row.get(
                "Total Discharges (V + XVIII + XIX + Unknown)"
            )
        ),

        total_costs=to_optional_float(
            row.get("Total Costs")
        ),

        cost_to_charge_ratio=to_optional_float(
            row.get("Cost To Charge Ratio")
        ),

        uncompensated_care=to_optional_float(
            row.get(
                "Total Unreimbursed and Uncompensated Care"
            )
        ),
    )

# endregion


# region Public API

def get_financial_data_by_hospital(
    facility_id: str,
    year: int | None = None,
) -> HospitalFinancialRecord | None:
    """
    One cost-report record for a hospital.

    With year=None, walks backwards from the newest dataset and
    returns the first year in which the hospital filed a report.
    Returns None when no report exists; raises
    CostReportUnavailableError when no dataset could be reached.
    """
    if year is not None:
        row = select_primary_row(
            fetch_cost_report_rows(facility_id, year)
        )
        return parse_cost_report_row(row, year) if row else None

    reached_any_dataset = False
    last_error: CostReportUnavailableError | None = None

    for candidate_year in reversed(get_available_report_years()):
        try:
            rows = fetch_cost_report_rows(facility_id, candidate_year)
        except CostReportUnavailableError as error:
            last_error = error
            continue

        reached_any_dataset = True
        row = select_primary_row(rows)

        if row is not None:
            return parse_cost_report_row(row, candidate_year)

    if not reached_any_dataset and last_error is not None:
        raise last_error

    return None


def get_raw_financial_data_by_hospital(
    facility_id: str,
    year: int | None = None,
) -> list[dict]:
    if year is not None:
        return fetch_cost_report_rows(facility_id, year)

    for candidate_year in reversed(get_available_report_years()):
        try:
            rows = fetch_cost_report_rows(facility_id, candidate_year)
        except CostReportUnavailableError:
            continue

        if rows:
            return rows

    return []


def resolve_report_years(
    start_year: int | None = None,
    end_year: int | None = None,
) -> list[int]:
    """
    Expand an optional [start_year, end_year] into the list of
    dataset years to query. Defaults to the most recent
    DEFAULT_TREND_SPAN_YEARS years.
    """
    latest = get_latest_report_year()

    if end_year is None:
        end_year = latest

    if start_year is None:
        start_year = end_year - DEFAULT_TREND_SPAN_YEARS + 1

    if start_year > end_year:
        raise ValueError("start_year must not be after end_year")

    if end_year - start_year + 1 > MAX_TREND_SPAN_YEARS:
        raise ValueError(
            f"Year range too large; request at most "
            f"{MAX_TREND_SPAN_YEARS} years"
        )

    return list(range(start_year, end_year + 1))


def get_financial_history_by_hospital(
    facility_id: str,
    start_year: int | None = None,
    end_year: int | None = None,
) -> FinancialHistoryResult:
    """
    Cost-report records for a hospital across several dataset years,
    fetched in parallel. Years are classified as having data, having
    no report, or being unavailable (dataset could not be fetched).
    """
    years = resolve_report_years(start_year, end_year)
    known_years = set(get_available_report_years())

    def fetch_year(year: int):
        if year not in known_years:
            available = sorted(known_years)
            return (
                year,
                None,
                f"outside CMS coverage "
                f"({available[0]}-{available[-1]})",
            )

        try:
            rows = fetch_cost_report_rows(facility_id, year)
        except CostReportUnavailableError as error:
            return year, None, error.reason

        row = select_primary_row(rows)

        if row is None:
            return year, None, None

        return year, parse_cost_report_row(row, year), None

    workers = max(1, min(MAX_PARALLEL_YEAR_REQUESTS, len(years)))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        outcomes = list(executor.map(fetch_year, years))

    result = FinancialHistoryResult(
        facility_id=facility_id.strip(),
        years_requested=years,
        records=[],
    )

    for year, record, reason in outcomes:
        if record is not None:
            result.records.append(record)
        elif reason is not None:
            result.years_unavailable[year] = reason
        else:
            result.years_without_report.append(year)

    result.records.sort(key=lambda record: record.report_year or 0)

    return result


def validate_financial_record(
    record: HospitalFinancialRecord,
) -> dict:
    missing_fields = []

    if record.net_patient_revenue is None:
        missing_fields.append("net_patient_revenue")

    if record.total_operating_expense is None:
        missing_fields.append("total_operating_expense")

    if record.total_assets is None:
        missing_fields.append("total_assets")

    if record.total_liabilities is None:
        missing_fields.append("total_liabilities")

    return {
        "is_complete": len(missing_fields) == 0,
        "missing_fields": missing_fields,
    }

# endregion
