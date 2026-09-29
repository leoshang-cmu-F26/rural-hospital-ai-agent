from app.models.financial import (
    HospitalFinancialRecord,
    FinancialIndicators,
)


def calculate_occupancy_rate(
    record: HospitalFinancialRecord,
) -> float | None:
    if (
        record.total_days is None
        or record.total_bed_days_available is None
        or record.total_bed_days_available == 0
    ):
        return None

    return round(
        record.total_days
        / record.total_bed_days_available
        * 100,
        2,
    )


def calculate_operating_margin(
    record: HospitalFinancialRecord,
) -> float | None:
    if (
        record.net_income_from_service is None
        or record.net_patient_revenue is None
        or record.net_patient_revenue == 0
    ):
        return None

    return round(
        record.net_income_from_service / record.net_patient_revenue * 100, 2)


def calculate_liability_to_asset_ratio(
    record: HospitalFinancialRecord,
) -> float | None:
    if (
        record.total_liabilities is None
        or record.total_assets is None
        or record.total_assets == 0
    ):
        return None

    return round(record.total_liabilities / record.total_assets * 100, 2)

def calculate_financial_indicators(
    record: HospitalFinancialRecord,
) -> dict:
    return {
        "occupancy_rate": calculate_occupancy_rate(record),
        "operating_margin": calculate_operating_margin(record),
        "liability_to_asset_ratio":
            calculate_liability_to_asset_ratio(record),
        "cost_to_charge_ratio":
            record.cost_to_charge_ratio,
    }

def calculate_financial_indicators(
    record: HospitalFinancialRecord,
) -> FinancialIndicators:

    missing_fields = []

    if record.total_days is None:
        missing_fields.append("total_days")

    if record.total_bed_days_available is None:
        missing_fields.append("total_bed_days_available")

    if record.net_income_from_service is None:
        missing_fields.append("net_income_from_service")

    if record.net_patient_revenue is None:
        missing_fields.append("net_patient_revenue")

    if record.total_liabilities is None:
        missing_fields.append("total_liabilities")

    if record.total_assets is None:
        missing_fields.append("total_assets")

    return FinancialIndicators(
        facility_id=record.facility_id,
        hospital_name=record.hospital_name,

        occupancy_rate=calculate_occupancy_rate(record),

        operating_margin=calculate_operating_margin(record),

        liability_to_asset_ratio=
            calculate_liability_to_asset_ratio(record),

        cost_to_charge_ratio=record.cost_to_charge_ratio,

        missing_fields=missing_fields,
    )