from langchain_core.tools import tool

from app.services.cost_report_service import (
    get_financial_data_by_hospital,
)
from app.tools.financial_tools import (
    calculate_financial_indicators,
)


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
            "facility_id": facility_id,
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