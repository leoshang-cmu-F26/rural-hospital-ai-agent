from langchain_core.tools import tool
from app.common.constants import HOSPITAL_FIELDS
from app.services.cms_service import (
    get_hospital_by_id,
    search_hospitals_by_name,
)
from app.services.cost_report_service import (
    CostReportUnavailableError,
    get_financial_data_by_hospital,
)
from app.tools.financial_tools import (
    calculate_financial_indicators,
)
from app.tools.trend_tools import (
    analyze_financial_trend_for_hospital,
)
from app.services.access_service import (
    get_healthcare_access_analysis,
    compare_hospitals_in_area
)
from app.services.census_service import (
    get_hospital_demographics as get_hospital_demographics_service,
)

MAX_HOSPITALS_FOR_AGENT = 10

COST_REPORT_SOURCE = "CMS Hospital Provider Cost Report"


@tool
def analyze_hospital_financials(
    facility_id: str,
    year: int | None = None,
) -> dict:
    """
    Retrieve CMS cost-report data for a hospital and calculate
    financial and operational indicators for a single year.

    Use this tool when the user asks about a hospital's current
    financial condition, operating margin, occupancy rate,
    liability-to-asset ratio, cost-to-charge ratio, or whether
    CMS classifies it as rural.

    The facility_id must be a CMS Certification Number (CCN).
    year is an optional CMS cost-report dataset year; when omitted
    the most recent year with a report is used.

    For change over time, use analyze_financial_trend instead.
    """

    try:
        financial_record = get_financial_data_by_hospital(
            facility_id,
            year=year,
        )

    except CostReportUnavailableError as error:
        return {
            "error": (
                "CMS cost report data could not be retrieved: "
                f"{error.reason}"
            ),
            HOSPITAL_FIELDS.FACILITY_ID_FIELD: facility_id,
            "year": year,
        }

    if financial_record is None:
        return {
            "error": "Financial data not found",
            HOSPITAL_FIELDS.FACILITY_ID_FIELD: facility_id,
            "year": year,
        }

    indicators = calculate_financial_indicators(
        financial_record
    )

    return {
        "source": COST_REPORT_SOURCE,
        "report_year":
            financial_record.report_year,
        "fiscal_year_begin":
            financial_record.fiscal_year_begin,
        "fiscal_year_end":
            financial_record.fiscal_year_end,
        "indicators": indicators.model_dump(),
    }


@tool
def analyze_financial_trend(
    facility_id: str,
    start_year: int | None = None,
    end_year: int | None = None,
) -> dict:
    """
    Analyze how a hospital's financial and operational indicators
    changed across several CMS cost-report years.

    Use this tool when the user asks about trends, change over time,
    deterioration or improvement, consecutive years of losses, or
    any question that spans more than one year.

    The facility_id must be a CMS Certification Number (CCN).
    start_year and end_year are optional CMS cost-report dataset
    years (datasets exist from 2011 onward). When omitted, the most
    recent five years are analyzed.

    Trend directions and changes are calculated deterministically;
    do not recalculate them.
    """

    try:
        trend = analyze_financial_trend_for_hospital(
            facility_id=facility_id,
            start_year=start_year,
            end_year=end_year,
        )

    except ValueError as error:
        return {
            "error": str(error),
            HOSPITAL_FIELDS.FACILITY_ID_FIELD: facility_id,
        }

    except CostReportUnavailableError as error:
        return {
            "error": (
                "CMS cost report data could not be retrieved: "
                f"{error.reason}"
            ),
            HOSPITAL_FIELDS.FACILITY_ID_FIELD: facility_id,
        }

    if not trend.yearly_indicators:
        return {
            "error": (
                "No cost report data found for this hospital "
                "in the requested years"
            ),
            HOSPITAL_FIELDS.FACILITY_ID_FIELD: facility_id,
            "years_requested": trend.years_requested,
            "years_without_report": trend.years_without_report,
            "years_unavailable": trend.years_unavailable,
        }

    # Keep the ToolMessage compact: one row per year with only the
    # fields the LLM needs to explain the trend.
    yearly_rows = [
        {
            "report_year": item.report_year,
            "fiscal_year_begin": item.fiscal_year_begin,
            "fiscal_year_end": item.fiscal_year_end,
            "operating_margin": item.operating_margin,
            "occupancy_rate": item.occupancy_rate,
            "liability_to_asset_ratio": item.liability_to_asset_ratio,
            "cost_to_charge_ratio": item.cost_to_charge_ratio,
            "missing_fields": item.missing_fields,
        }
        for item in trend.yearly_indicators
    ]

    indicator_trends = {
        name: {
            "first_year": summary.first_year,
            "first_value": summary.first_value,
            "last_year": summary.last_year,
            "last_value": summary.last_value,
            "change": summary.change,
            "direction": summary.direction,
            "years_available": summary.years_available,
        }
        for name, summary in trend.indicator_trends.items()
    }

    return {
        "source": f"{COST_REPORT_SOURCE} (multi-year)",

        HOSPITAL_FIELDS.FACILITY_ID_FIELD: trend.facility_id,
        "hospital_name": trend.hospital_name,
        "rural_versus_urban": trend.rural_versus_urban,
        "is_rural": trend.is_rural,

        "years_requested": trend.years_requested,
        "years_with_data": trend.years_with_data,
        "years_without_report": trend.years_without_report,
        "years_unavailable": trend.years_unavailable,

        "yearly_indicators": yearly_rows,
        "indicator_trends": indicator_trends,

        "distress_signals": {
            "years_with_negative_operating_margin":
                trend.years_with_negative_operating_margin,
            "consecutive_negative_operating_margin_years":
                trend.consecutive_negative_operating_margin_years,
            "years_with_liabilities_exceeding_assets":
                trend.years_with_liabilities_exceeding_assets,
            "average_operating_margin":
                trend.average_operating_margin,
        },

        "notes": [
            "Years are CMS cost-report dataset years; a hospital's "
            "fiscal year may not match the calendar year.",
            "Trends describe reported history only and do not "
            "predict closure or recovery.",
        ],
    }


@tool
def search_hospital(name: str) -> dict:
    """
    Search CMS hospital data by hospital name.

    Use this tool when the user provides a hospital name
    but does not provide a CMS Certification Number (CCN).

    Returns matching hospitals with their facility IDs,
    names, city, state, ZIP code, and hospital type.
    """

    hospitals = search_hospitals_by_name(name)

    if not hospitals:
        return {
            "query": name,
            "count": 0,
            "hospitals": [],
        }

    return {
        "query": name,
        "count": len(hospitals),
        "hospitals": [
            hospital.model_dump()
            for hospital in hospitals[:5]
        ],
    }


@tool
def get_hospital_by_ccn(facility_id: str) -> dict:
    """
    Find a hospital using its CMS Certification Number (CCN).

    Use this tool when the user provides a CCN and wants
    to know which hospital it belongs to or wants basic
    hospital information.
    """

    hospital = get_hospital_by_id(facility_id)

    if hospital is None:
        return {
            "error": "Hospital not found",
            HOSPITAL_FIELDS.FACILITY_ID_FIELD: facility_id,
        }

    return hospital.model_dump()


@tool
def analyze_healthcare_access(
    facility_id: str,
) -> dict:
    """
    Analyze basic healthcare-access conditions around a hospital.

    Use this tool for broader healthcare-access questions,
    including questions about the possible access impact of
    hospital closure or service reduction.

    The current analysis combines:
    - other CMS-listed hospitals in the same county
    - county population
    - population age 65 and older
    - percentage of county residents age 65 and older

    This analysis does not yet include physical distance,
    travel time, HRSA shortage designations, hospital capacity,
    or service-line availability.
    """

    result = get_healthcare_access_analysis(
        facility_id
    )

    if result is None:
        return {
            "error": "Hospital not found",
            "facility_id": facility_id,
        }

    return result


@tool
def compare_hospitals_by_area(
    facility_id: str,
    scope: str,
    limit: int | None = None,
) -> dict:
    """
    Compare a hospital with other CMS-listed hospitals
    in the same county, ZIP code, or state.

    Parameters:
    - facility_id: CMS Certification Number (CCN)
    - scope: "county", "zip", or "state".
      See ../common/constants.py for valid values.
    - limit: optional maximum number of hospitals returned
      for state-level comparisons.

    County and ZIP comparisons return all matching hospitals.

    State comparisons return a limited number of hospitals
    by default to reduce the amount of data sent to the LLM.

    This is an administrative-area comparison.
    It does not calculate physical distance.
    """

    try:
        result = compare_hospitals_in_area(
            facility_id=facility_id,
            scope=scope,
        )

    except ValueError as error:
        return {
            "error": str(error),
            HOSPITAL_FIELDS.FACILITY_ID_FIELD: facility_id,
            "scope": scope,
        }

    if result is None:
        return {
            "error": "Hospital not found",
            HOSPITAL_FIELDS.FACILITY_ID_FIELD: facility_id,
        }

    # All hospitals returned by the service.
    comparison_hospitals = result["comparison_hospitals"]

    # County and ZIP comparisons are usually small,
    # so return all matching hospitals.
    if result["scope"] in {"county", "zip"}:
        selected_hospitals = comparison_hospitals

    # State comparisons may contain many hospitals.
    # Limit the records sent to the LLM to reduce token usage.
    else:
        effective_limit = (
            limit
            if limit is not None
            else MAX_HOSPITALS_FOR_AGENT
        )

        selected_hospitals = comparison_hospitals[
            :effective_limit
        ]

    # Only send fields that are useful to the LLM.
    compact_hospitals = [
        {
            HOSPITAL_FIELDS.FACILITY_ID_FIELD:
                hospital[
                    HOSPITAL_FIELDS.FACILITY_ID_FIELD
                ],

            HOSPITAL_FIELDS.FACILITY_NAME_FIELD:
                hospital[
                    HOSPITAL_FIELDS.FACILITY_NAME_FIELD
                ],

            HOSPITAL_FIELDS.CITYTOWN_FIELD:
                hospital[
                    HOSPITAL_FIELDS.CITYTOWN_FIELD
                ],

            HOSPITAL_FIELDS.COUNTY_FIELD:
                hospital[
                    HOSPITAL_FIELDS.COUNTY_FIELD
                ],
        }
        for hospital in selected_hospitals
    ]

    return {
        "source":
            "CMS Hospital General Information",

        "target_hospital":
            result["target_hospital"],

        "scope":
            result["scope"],

        "area":
            result["area"],

        # Total number of matching hospitals,
        # even if only part of them is returned.
        "comparison_count":
            result["comparison_count"],

        # Number actually included in the ToolMessage.
        "returned_count":
            len(compact_hospitals),

        # True when some matching hospitals were omitted.
        "truncated":
            result["comparison_count"]
            > len(compact_hospitals),

        "comparison_hospitals":
            compact_hospitals,
    }


@tool
def get_hospital_demographics(
    facility_id: str,
) -> dict:
    """
    Retrieve county-level Census demographics for a hospital.

    Use this tool when the user asks about the population or
    age demographics of the county containing a hospital.

    The facility_id must be a CMS Certification Number (CCN).

    Currently provides:
    - total county population
    - population age 65 and older
    - percentage of population age 65 and older

    Demographic data comes from the U.S. Census Bureau
    ACS 2024 5-Year estimates.
    """

    result = get_hospital_demographics_service(
        facility_id
    )

    if result is None:
        return {
            "error": "Hospital not found",
            "facility_id": facility_id,
        }

    return result

HOSPITAL_AGENT_TOOLS = [
    search_hospital,  # Find CMS hospitals by name.
    get_hospital_by_ccn,  # Retrieve hospital details by CCN.
    analyze_hospital_financials,  # Calculate financial indicators from CMS reports.
    analyze_healthcare_access,  # Find same-county alternative hospitals.
    compare_hospitals_by_area,  # Compare hospitals in the same county, ZIP, or state.
    get_hospital_demographics,  # Retrieve Census demographics for the hospital's county.
]

