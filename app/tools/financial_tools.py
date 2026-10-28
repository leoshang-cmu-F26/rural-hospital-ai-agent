"""Deterministic financial indicators with explicit missing-data handling."""

from math import isfinite

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


# Deterministic ratio calculations


def calculate_occupancy_rate(
    record: HospitalFinancialRecord,
) -> float | None:
    """Calculate occupancy percent from finite inputs and a nonzero denominator."""
    if (
        record.total_days is None
        or record.total_bed_days_available is None
        or not isfinite(record.total_days)
        or not isfinite(record.total_bed_days_available)
        or record.total_bed_days_available == 0
    ):
        return None

    return round(
        record.total_days / record.total_bed_days_available * 100,
        2,
    )


def calculate_operating_margin(
    record: HospitalFinancialRecord,
) -> float | None:
    """Calculate service-income margin percent from reported fields."""
    if (
        record.net_income_from_service is None
        or record.net_patient_revenue is None
        or not isfinite(record.net_income_from_service)
        or not isfinite(record.net_patient_revenue)
        or record.net_patient_revenue == 0
    ):
        return None

    return round(
        record.net_income_from_service / record.net_patient_revenue * 100,
        2,
    )


def calculate_liability_to_asset_ratio(
    record: HospitalFinancialRecord,
) -> float | None:
    """Calculate the reported liabilities-to-assets percentage."""
    if (
        record.total_liabilities is None
        or record.total_assets is None
        or not isfinite(record.total_liabilities)
        or not isfinite(record.total_assets)
        or record.total_assets == 0
    ):
        return None

    return round(
        record.total_liabilities / record.total_assets * 100,
        2,
    )


# Rural code interpretation


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


# Indicators with source-quality flags


def calculate_financial_indicators(
    record: HospitalFinancialRecord,
) -> FinancialIndicators:
    """Calculate each supported indicator and retain its missing-input fields."""
    from app.services.data_quality_service import financial_quality

    quality_warnings, blocked_metrics = financial_quality(record)
    missing_fields = []
    for field in INDICATOR_INPUT_FIELDS:
        if getattr(record, field) is None:
            missing_fields.append(field)

    cost_ratio = record.cost_to_charge_ratio
    if cost_ratio is not None and not isfinite(cost_ratio):
        cost_ratio = None

    return FinancialIndicators(
        facility_id=record.facility_id,
        hospital_name=record.hospital_name,
        report_year=record.report_year,
        source_provenance=record.source_provenance,
        fiscal_year_begin=record.fiscal_year_begin,
        fiscal_year_end=record.fiscal_year_end,
        rural_versus_urban=record.rural_versus_urban,
        is_rural=is_rural_hospital(record),
        occupancy_rate=calculate_occupancy_rate(record),
        operating_margin=calculate_operating_margin(record),
        liability_to_asset_ratio=calculate_liability_to_asset_ratio(record),
        cost_to_charge_ratio=cost_ratio,
        missing_fields=missing_fields,
        blocked_metrics=blocked_metrics,
        quality_warnings=quality_warnings,
    )
