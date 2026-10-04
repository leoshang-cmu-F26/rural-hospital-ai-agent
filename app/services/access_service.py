from app.common.constants import (HOSPITAL_FIELDS, SCOPE_FIELDS)
from app.services.cms_service import (
    get_hospital_by_id,
    get_hospitals_by_state,
)

def get_other_hospitals_in_county(
    facility_id: str,
) -> dict | None:
    """
    Find other hospitals located in the same county
    as the target hospital.

    This is an initial proxy for healthcare access.
    It does not yet calculate actual travel distance.
    """

    # 1. Find the target hospital
    target_hospital = get_hospital_by_id(facility_id)

    if target_hospital is None:
        return None


    # 2. Make sure county information exists
    if not target_hospital.countyparish:
        return {
            HOSPITAL_FIELDS.FACILITY_ID_FIELD: target_hospital.facility_id,
            HOSPITAL_FIELDS.FACILITY_NAME_FIELD: target_hospital.facility_name,
            HOSPITAL_FIELDS.STATE_FIELD: target_hospital.state,
            HOSPITAL_FIELDS.COUNTY: None,
            "alternative_hospital_count": 0,
            "alternative_hospitals": [],
            "error": "County information is unavailable.",
        }


    # 3. Get all hospitals in the same state
    hospitals_in_state = get_hospitals_by_state(
        target_hospital.state
    )


    target_county = target_hospital.countyparish.strip().upper()

    # 4. Filter hospitals in the same county
    alternative_hospitals = []
    for hospital in hospitals_in_state:

        if hospital[HOSPITAL_FIELDS.FACILITY_ID_FIELD] == facility_id:
            continue

        county = hospital.get(HOSPITAL_FIELDS.COUNTY_PARISH_FIELD)

        if not county:
            continue

        hospital_county = (
            county
            .strip()
            .upper()
        )

        if hospital_county == target_county:
            alternative_hospitals.append(
                {
                    HOSPITAL_FIELDS.FACILITY_ID_FIELD: hospital.get(
                        HOSPITAL_FIELDS.FACILITY_ID_FIELD
                    ),
                    HOSPITAL_FIELDS.FACILITY_NAME_FIELD: hospital.get(
                        HOSPITAL_FIELDS.FACILITY_NAME_FIELD
                    ),
                    HOSPITAL_FIELDS.ADDRESS_FIELD: hospital.get(
                        HOSPITAL_FIELDS.ADDRESS_FIELD
                    ),
                    HOSPITAL_FIELDS.CITYTOWN_FIELD: hospital.get(
                        HOSPITAL_FIELDS.CITYTOWN_FIELD
                    ),
                    HOSPITAL_FIELDS.STATE_FIELD: hospital.get(
                        HOSPITAL_FIELDS.STATE_FIELD
                    ),
                    HOSPITAL_FIELDS.ZIP_CODE_FIELD: hospital.get(
                        HOSPITAL_FIELDS.ZIP_CODE_FIELD
                    ),
                    HOSPITAL_FIELDS.HOSPITAL_TYPE_FIELD: hospital.get(
                        HOSPITAL_FIELDS.HOSPITAL_TYPE_FIELD
                    ),
                }
            )


    # 5. Return structured result
    return {
        HOSPITAL_FIELDS.FACILITY_ID_FIELD: target_hospital.facility_id,
        HOSPITAL_FIELDS.FACILITY_NAME_FIELD: target_hospital.facility_name,
        "county": target_hospital.countyparish,
        HOSPITAL_FIELDS.STATE_FIELD: target_hospital.state,
        "alternative_hospital_count": len(alternative_hospitals),
        "alternative_hospitals": alternative_hospitals,
    }

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
    target_hospital = get_hospital_by_id(
        facility_id
    )

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
            hospital_area = hospital.get(
                HOSPITAL_FIELDS.COUNTY_PARISH_FIELD,
                "",
            ).strip().upper()
        elif scope == "zip":
            hospital_area = hospital.get(HOSPITAL_FIELDS.ZIP_CODE_FIELD, "").strip()
        else:
            hospital_area = hospital.get(HOSPITAL_FIELDS.STATE_FIELD, "").strip().upper()

        if hospital_area != target_area:
            continue


        comparison_hospitals.append(
            {
                HOSPITAL_FIELDS.FACILITY_ID_FIELD:
                    hospital.get(HOSPITAL_FIELDS.FACILITY_ID_FIELD),

                HOSPITAL_FIELDS.FACILITY_NAME_FIELD:
                    hospital.get(HOSPITAL_FIELDS.FACILITY_NAME_FIELD),

                HOSPITAL_FIELDS.ADDRESS_FIELD:
                    hospital.get(HOSPITAL_FIELDS.ADDRESS_FIELD),

                HOSPITAL_FIELDS.CITYTOWN_FIELD:
                    hospital.get(HOSPITAL_FIELDS.CITYTOWN_FIELD),

                HOSPITAL_FIELDS.STATE_FIELD:
                    hospital.get(HOSPITAL_FIELDS.STATE_FIELD),

                HOSPITAL_FIELDS.ZIP_CODE_FIELD:
                    hospital.get(HOSPITAL_FIELDS.ZIP_CODE_FIELD),

                HOSPITAL_FIELDS.COUNTY_FIELD:
                    hospital.get(HOSPITAL_FIELDS.COUNTY_PARISH_FIELD),

                HOSPITAL_FIELDS.HOSPITAL_TYPE_FIELD:
                    hospital.get(HOSPITAL_FIELDS.HOSPITAL_TYPE_FIELD),
            }
        )


    # 7. Return structured result
    return {
        "target_hospital": {
            HOSPITAL_FIELDS.FACILITY_ID_FIELD:
                target_hospital.facility_id,

            HOSPITAL_FIELDS.FACILITY_NAME_FIELD:
                target_hospital.facility_name,

            HOSPITAL_FIELDS.COUNTY_FIELD:
                target_hospital.countyparish,

            HOSPITAL_FIELDS.ZIP_CODE_FIELD:
                target_hospital.zip_code,

            HOSPITAL_FIELDS.STATE_FIELD:
                target_hospital.state,
        },

        "scope": scope,

        "area": target_area,

        "comparison_count":
            len(comparison_hospitals),

        "comparison_hospitals":
            comparison_hospitals,
    }