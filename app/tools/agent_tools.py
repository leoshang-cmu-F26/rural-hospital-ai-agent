from langchain_core.tools import tool

from app.common.constants import HOSPITAL_FIELDS
from app.services.cost_report_service import (
    get_financial_data_by_hospital,
)
from app.tools.financial_tools import (
    calculate_financial_indicators,
)
from app.services.cms_service import (
    search_hospitals_by_name,
    get_hospital_by_id,
)
from app.services.access_service import (
    get_other_hospitals_in_county,
)
from app.services.access_service import compare_hospitals_in_area

MAX_HOSPITALS_FOR_AGENT = 10

@tool
def analyze_hospital_financials(facility_id: str) -> dict:
    """
    Retrieve CMS cost-report data for a hospital and calculate
    financial and operational indicators.

    Use this tool when the user asks about a hospital's financial
    condition, operating margin, occupancy rate,
    liability-to-asset ratio, or cost-to-charge ratio.

    The facility_id must be a CMS Certification Number (CCN).
    """

    financial_record = get_financial_data_by_hospital(
        facility_id
    )

    if financial_record is None:
        return {
            "error": "Financial data not found",
            HOSPITAL_FIELDS.FACILITY_ID_FIELD: facility_id,
        }

    indicators = calculate_financial_indicators(
        financial_record
    )

    return {
        "source": "CMS Hospital Provider Cost Report",
        "fiscal_year_begin":
            financial_record.fiscal_year_begin,
        "fiscal_year_end":
            financial_record.fiscal_year_end,
        "indicators": indicators.model_dump(),
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
def analyze_healthcare_access(facility_id: str) -> dict:
    """
    Analyze basic healthcare access for a hospital.

    Use this tool when the user asks about healthcare access,
    alternative hospitals, or the potential access impact
    if a hospital closes.

    This initial version uses other CMS-listed hospitals
    in the same county as a county-level access proxy.
    """

    result = get_other_hospitals_in_county(facility_id)

    if result is None:
        return {
            "error": "Hospital not found",
            HOSPITAL_FIELDS.FACILITY_ID_FIELD: facility_id,
        }

    return {
        "source": "CMS Hospital General Information",
        "method": "Same-county alternative hospital proxy",
        **result,
    }

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