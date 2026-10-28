import requests
from app.common.constants import HOSPITAL_FIELDS, SCOPE_FIELDS
from app.services.cms_service import (
    get_hospital_by_id,
    get_hospitals_by_state,
)
from app.services.census_service import (
    get_hospital_demographics,
)
from app.services.hrsa_service import (
    get_county_primary_care_hpsa,
)
from app.services.distance_service import get_nearest_hospitals


def compare_hospitals_in_area(
    facility_id: str,
    scope: str,
) -> dict | None:
    """
    Find other hospitals in the same county, ZIP code,
    or state as the target hospital.

    This function uses CMS Hospital General Information only.
    It does not use geocoding or an LLM.

    Supported scopes:
    - "county"
    - "zip"
    - "state"
    """

    # 1. Normalize input
    facility_id = facility_id.strip()
    scope = scope

    # 2. Validate comparison scope
    if scope not in SCOPE_FIELDS.__dict__.values():
        raise ValueError("scope must be 'county', 'zip', or 'state'")

    # 3. Find target hospital
    target_hospital = get_hospital_by_id(facility_id)

    if target_hospital is None:
        return None

    # 4. Get all hospitals in the target hospital's state
    hospitals_in_state = get_hospitals_by_state(target_hospital.state)

    # 5. Determine target comparison area
    if scope == "county":

        if not target_hospital.countyparish:
            return {
                HOSPITAL_FIELDS.FACILITY_ID_FIELD: facility_id,
                "scope": scope,
                "error": "County information is unavailable.",
            }

        target_area = target_hospital.countyparish.strip().upper()
    elif scope == "zip":

        if not target_hospital.zip_code:
            return {
                HOSPITAL_FIELDS.FACILITY_ID_FIELD: facility_id,
                "scope": scope,
                "error": "ZIP code information is unavailable.",
            }

        target_area = target_hospital.zip_code.strip()
    else:
        target_area = target_hospital.state.strip().upper()

    # 6. Find hospitals in the same area
    comparison_hospitals = []

    for hospital in hospitals_in_state:

        # Do not compare the hospital with itself
        if hospital.get(HOSPITAL_FIELDS.FACILITY_ID_FIELD) == facility_id:
            continue

        if scope == "county":
            hospital_area = (
                hospital.get(
                    HOSPITAL_FIELDS.COUNTY_PARISH_FIELD,
                    "",
                )
                .strip()
                .upper()
            )
        elif scope == "zip":
            hospital_area = hospital.get(HOSPITAL_FIELDS.ZIP_CODE_FIELD, "").strip()
        else:
            hospital_area = hospital.get(HOSPITAL_FIELDS.STATE_FIELD, "").strip().upper()

        if hospital_area != target_area:
            continue

        comparison_hospitals.append(
            {
                HOSPITAL_FIELDS.FACILITY_ID_FIELD: hospital.get(HOSPITAL_FIELDS.FACILITY_ID_FIELD),
                HOSPITAL_FIELDS.FACILITY_NAME_FIELD: hospital.get(
                    HOSPITAL_FIELDS.FACILITY_NAME_FIELD
                ),
                HOSPITAL_FIELDS.ADDRESS_FIELD: hospital.get(HOSPITAL_FIELDS.ADDRESS_FIELD),
                HOSPITAL_FIELDS.CITYTOWN_FIELD: hospital.get(HOSPITAL_FIELDS.CITYTOWN_FIELD),
                HOSPITAL_FIELDS.STATE_FIELD: hospital.get(HOSPITAL_FIELDS.STATE_FIELD),
                HOSPITAL_FIELDS.ZIP_CODE_FIELD: hospital.get(HOSPITAL_FIELDS.ZIP_CODE_FIELD),
                HOSPITAL_FIELDS.COUNTY_FIELD: hospital.get(HOSPITAL_FIELDS.COUNTY_PARISH_FIELD),
                HOSPITAL_FIELDS.HOSPITAL_TYPE_FIELD: hospital.get(
                    HOSPITAL_FIELDS.HOSPITAL_TYPE_FIELD
                ),
            }
        )

    # 7. Return structured result
    return {
        "data_provenance": target_hospital.source_provenance,
        "target_hospital": {
            HOSPITAL_FIELDS.FACILITY_ID_FIELD: target_hospital.facility_id,
            HOSPITAL_FIELDS.FACILITY_NAME_FIELD: target_hospital.facility_name,
            HOSPITAL_FIELDS.COUNTY_FIELD: target_hospital.countyparish,
            HOSPITAL_FIELDS.ZIP_CODE_FIELD: target_hospital.zip_code,
            HOSPITAL_FIELDS.STATE_FIELD: target_hospital.state,
        },
        "scope": scope,
        "area": target_area,
        "comparison_count": len(comparison_hospitals),
        "comparison_hospitals": comparison_hospitals,
    }


def get_healthcare_access_analysis(
    facility_id: str,
) -> dict | None:
    """
    Build a basic county-level healthcare access analysis
    for a hospital using CMS hospital data and Census
    demographics.
    """

    # 1. Retrieve the target hospital and same-county comparison.
    comparison = compare_hospitals_in_area(
        facility_id=facility_id,
        scope=SCOPE_FIELDS.COUNTY,
    )

    if comparison is None:
        return None
    comparison_error = comparison.get("error")
    if comparison_error:
        hospital = get_hospital_by_id(facility_id)
        if hospital is None:
            return None
        comparison = {
            "target_hospital": {
                "facility_id": hospital.facility_id,
                "facility_name": hospital.facility_name,
                "state": hospital.state,
                "county": hospital.countyparish,
            },
            "comparison_count": None,
            "comparison_hospitals": [],
        }

    # 2. Retrieve county demographics for the target hospital.
    demographics = get_hospital_demographics(facility_id=facility_id)

    # 3. Normalize available or missing demographic data.
    if demographics is None or "error" in demographics:
        if isinstance(demographics, dict):
            demographic_error = demographics.get("error")
        else:
            demographic_error = "Demographic data unavailable."
        demographic_result = {
            "available": False,
            "error": demographic_error,
        }

    else:
        demographic_result = {
            "available": True,
            "total_population": demographics["total_population"],
            "population_65_plus": demographics["population_65_plus"],
            "population_65_plus_percent": demographics["population_65_plus_percent"],
            "source": demographics["source"],
            "data_provenance": demographics.get("data_provenance"),
        }

    # 4. Use the resolved county and state to query HRSA.
    target_hospital = comparison["target_hospital"]

    # Keep HRSA availability separate so a lookup failure does not
    # discard the CMS comparison or Census results.
    try:
        if not target_hospital.get("county"):
            raise ValueError("County information is unavailable.")
        hpsa = get_county_primary_care_hpsa(
            state=target_hospital["state"],
            county=target_hospital["county"],
        )

        hpsa_result = {
            "available": True,
            "has_active_primary_care_hpsa": hpsa["has_active_primary_care_hpsa"],
            "active_designation_count": hpsa["active_designation_count"],
            "max_hpsa_score": hpsa["max_hpsa_score"],
            "designations": hpsa["designations"],
            "source": hpsa["source"],
            "data_provenance": hpsa.get("data_provenance"),
        }

    except Exception as error:
        hpsa_result = {
            "available": False,
            "error": str(error),
        }

    # Keep other evidence available if distance analysis fails.
    try:
        distance_analysis = get_nearest_hospitals(
            facility_id=facility_id,
            limit=5,
        )

        if distance_analysis is None:
            distance_result = {
                "available": False,
                "error": "Hospital coordinates unavailable.",
            }
        else:
            available_distance = {}
            available_distance['available'] = True
            for copied_key, copied_value in (distance_analysis).items():
                available_distance[copied_key] = copied_value

            distance_result = available_distance

    except requests.RequestException as error:
        distance_result = {
            "available": False,
            "error": str(error),
        }

    # 5. Combine hospital comparison, demographics, and HRSA evidence.
    return {
        "data_provenance": comparison.get("data_provenance"),
        HOSPITAL_FIELDS.FACILITY_ID_FIELD: target_hospital[HOSPITAL_FIELDS.FACILITY_ID_FIELD],
        HOSPITAL_FIELDS.FACILITY_NAME_FIELD: target_hospital[HOSPITAL_FIELDS.FACILITY_NAME_FIELD],
        HOSPITAL_FIELDS.STATE_FIELD: target_hospital[HOSPITAL_FIELDS.STATE_FIELD],
        HOSPITAL_FIELDS.COUNTY_FIELD: target_hospital[HOSPITAL_FIELDS.COUNTY_FIELD],
        "county_comparison_available": not bool(comparison_error),
        "county_comparison_error": comparison_error,
        "alternative_hospital_count": comparison["comparison_count"],
        "alternative_hospitals": comparison["comparison_hospitals"],
        "county_demographics": demographic_result,
        "primary_care_hpsa": hpsa_result,
        "distance_analysis": distance_result,
        "limitations": [
            ("Same-county hospital count is an " "administrative-area proxy."),
            ("County population is not the hospital's " "exact patient service area."),
            ("Distances are straight-line distances, not driving distance or travel time."),
            (
                "Nearest-hospital candidates are limited to the same state; "
                "hospitals without matched coordinates are excluded."
            ),
            (
                "HPSA designations may apply to specific "
                "population groups or geographic areas "
                "rather than the entire county."
            ),
        ],
    }
