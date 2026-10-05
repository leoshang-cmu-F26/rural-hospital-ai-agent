from app.models.financial import (
    HospitalFinancialRecord,
    FinancialIndicators,
)


# Record fields that feed the indicators. Any of these being None is
# reported back in FinancialIndicators.missing_fields.
INDICATOR_INPUT_FIELDS = (
    "total_days",
    "total_bed_days_available",
    "net_income_from_service",
    "net_patient_revenue",
    "total_liabilities",
    "total_assets",
    "cost_to_charge_ratio",
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
        record.net_income_from_service
        / record.net_patient_revenue
        * 100,
        2,
    )


def calculate_liability_to_asset_ratio(
    record: HospitalFinancialRecord,
) -> float | None:
    if (
        record.total_liabilities is None
        or record.total_assets is None
        or record.total_assets == 0
    ):
        return None

    return round(
        record.total_liabilities
        / record.total_assets
        * 100,
        2,
    )


def is_rural_hospital(
    record: HospitalFinancialRecord,
) -> bool | None:
    """
    Map the cost report's "Rural Versus Urban" code to a boolean.

    Returns None when the code is missing or unrecognised so that
    callers never mistake "unknown" for "urban".
    """
    if record.rural_versus_urban is None:
        return None

    code = record.rural_versus_urban.strip().upper()

    if code == "R":
        return True

    if code == "U":
        return False

    return None


def calculate_financial_indicators(
    record: HospitalFinancialRecord,
) -> FinancialIndicators:

    missing_fields = [
        field
        for field in INDICATOR_INPUT_FIELDS
        if getattr(record, field) is None
    ]

    return FinancialIndicators(
        facility_id=record.facility_id,
        hospital_name=record.hospital_name,

        report_year=record.report_year,
        fiscal_year_begin=record.fiscal_year_begin,
        fiscal_year_end=record.fiscal_year_end,

        rural_versus_urban=record.rural_versus_urban,
        is_rural=is_rural_hospital(record),

        occupancy_rate=calculate_occupancy_rate(record),

        operating_margin=calculate_operating_margin(record),

        liability_to_asset_ratio=
            calculate_liability_to_asset_ratio(record),

        cost_to_charge_ratio=record.cost_to_charge_ratio,

        missing_fields=missing_fields,
    )
