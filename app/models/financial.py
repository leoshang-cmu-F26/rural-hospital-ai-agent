from pydantic import BaseModel

class HospitalFinancialRecord(BaseModel):
    facility_id: str
    hospital_name: str
    fiscal_year_begin: str
    fiscal_year_end: str

    rural_versus_urban: str | None = None
    number_of_beds: float | None = None
    total_days: float | None = None
    total_bed_days_available: float | None = None
    total_discharges: float | None = None

    net_patient_revenue: float | None = None
    total_operating_expense: float | None = None
    net_income_from_service: float | None = None
    net_income: float | None = None

    total_assets: float | None = None
    total_liabilities: float | None = None

    total_costs: float | None = None
    cost_to_charge_ratio: float | None = None
    uncompensated_care: float | None = None

class FinancialIndicators(BaseModel):
    facility_id: str
    hospital_name: str

    occupancy_rate: float | None = None
    operating_margin: float | None = None
    liability_to_asset_ratio: float | None = None
    cost_to_charge_ratio: float | None = None

    missing_fields: list[str] = []