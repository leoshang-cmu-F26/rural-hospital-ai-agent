import requests
from app.models.financial import HospitalFinancialRecord

CMS_COST_REPORT_2023_URL = (
    "https://data.cms.gov/data-api/v1/dataset/"
    "cb8d0018-1bbe-4559-91bf-9429ac344b48/data"
)


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

def get_financial_data_by_hospital(
    facility_id: str,
) -> HospitalFinancialRecord | None:

    params = {
        "filter[Provider CCN]": facility_id,
        "size": 5,
    }

    response = requests.get(
        CMS_COST_REPORT_2023_URL,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    results = response.json()

    if not results:
        return None

    record = results[0]

    return HospitalFinancialRecord(
        facility_id=record["Provider CCN"],
        hospital_name=record["Hospital Name"],
        fiscal_year_begin=record["Fiscal Year Begin Date"],
        fiscal_year_end=record["Fiscal Year End Date"],

        net_patient_revenue=to_optional_float(
            record.get("Net Patient Revenue")
        ),

        total_operating_expense=to_optional_float(
            record.get("Less Total Operating Expense")
        ),

        net_income_from_service=to_optional_float(
            record.get("Net Income from Service to Patients")
        ),

        net_income=to_optional_float(
            record.get("Net Income")
        ),

        total_assets=to_optional_float(
            record.get("Total Assets")
        ),

        total_liabilities=to_optional_float(
            record.get("Total Liabilities")
        ),

        rural_versus_urban=record.get(
            "Rural Versus Urban"
        ),

        number_of_beds=to_optional_float(
            record.get("Number of Beds")
        ),

        total_days=to_optional_float(
            record.get(
                "Total Days (V + XVIII + XIX + Unknown)"
            )
        ),

        total_bed_days_available=to_optional_float(
            record.get("Total Bed Days Available")
        ),

        total_discharges=to_optional_float(
            record.get(
                "Total Discharges (V + XVIII + XIX + Unknown)"
            )
        ),

        total_costs=to_optional_float(
            record.get("Total Costs")
        ),

        cost_to_charge_ratio=to_optional_float(
            record.get("Cost To Charge Ratio")
        ),

        uncompensated_care=to_optional_float(
            record.get(
                "Total Unreimbursed and Uncompensated Care"
            )
        ),
    )

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

def get_raw_financial_data_by_hospital(
    facility_id: str,
):
    params = {
        "filter[Provider CCN]": facility_id,
        "size": 10,
    }

    response = requests.get(
        CMS_COST_REPORT_2023_URL,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()