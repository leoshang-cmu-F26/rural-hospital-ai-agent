"""
Distance analysis service for hospital accessibility.

This module:
- calculates straight-line geographic distance between
  latitude/longitude coordinates using the Haversine formula,
- identifies nearby alternative hospitals using CMS hospital data,
- reuses cached hospital coordinates from the geocoding service.

Distance calculations are deterministic and are performed
outside the LLM.

Current limitation:
- alternative hospital candidates are limited to hospitals
  within the same state,
- distances are straight-line distances rather than driving
  distance or travel time.
"""

from math import (
    asin,
    cos,
    radians,
    sin,
    sqrt,
)
from app.services.cms_service import (
    get_hospital_by_id,
    get_hospitals_by_state,
)
from app.services.geocoding_service import (
    geocode_hospital,
    geocode_hospital_record,
)


EARTH_RADIUS_MILES = 3958.8


def calculate_distance_miles(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    """
    Calculate straight-line distance between two geographic
    coordinates using the Haversine formula.

    Returns distance in miles.
    """

    lat1 = radians(latitude_1)
    lon1 = radians(longitude_1)

    lat2 = radians(latitude_2)
    lon2 = radians(longitude_2)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    haversine_value = (
        sin(delta_lat / 2) ** 2
        + cos(lat1)
        * cos(lat2)
        * sin(delta_lon / 2) ** 2
    )

    central_angle = (
        2
        * asin(
            sqrt(haversine_value)
        )
    )

    distance = EARTH_RADIUS_MILES * central_angle

    return round(distance, 2)


def get_nearest_hospitals(
    facility_id: str,
    limit: int = 5,
) -> dict | None:
    """
    Find the nearest alternative CMS-listed hospitals.

    Current implementation:
    - retrieves all hospitals in the target hospital's state,
    - excludes the target hospital,
    - geocodes each candidate hospital,
    - calculates straight-line distance,
    - returns the nearest hospitals.

    Results reuse the coordinate cache implemented in
    geocoding_service.py.

    Parameters:
        facility_id:
            CMS Certification Number (CCN).

        limit:
            Maximum number of nearest hospitals returned.

    Returns None if the target hospital cannot be found
    or geocoded.
    """

    if limit <= 0:
        raise ValueError(
            "limit must be greater than 0"
        )

    # -----------------------------------------------------
    # 1. Retrieve target hospital
    # -----------------------------------------------------

    target_hospital = get_hospital_by_id(
        facility_id
    )

    if target_hospital is None:
        return None

    # -----------------------------------------------------
    # 2. Geocode target hospital
    # -----------------------------------------------------

    target_coordinates = geocode_hospital(
        facility_id
    )

    if target_coordinates is None:
        return None

    # -----------------------------------------------------
    # 3. Retrieve same-state candidate hospitals
    # -----------------------------------------------------

    hospitals = get_hospitals_by_state(
        target_hospital.state
    )

    nearest_candidates = []

    skipped_geocoding_count = 0

    report_progress("Locating same-state hospitals and calculating distances…")
    for hospital in hospitals:

        candidate_id = hospital.get(
            "facility_id"
        )

        # Skip invalid records.
        if not candidate_id:
            continue

        # Do not compare the hospital with itself.
        if candidate_id == facility_id:
            continue

        # -------------------------------------------------
        # 4. Geocode candidate hospital
        # -------------------------------------------------

        report_progress(f"Locating hospital {len(nearest_candidates) + skipped_geocoding_count + 1}; calculating distances…")
        candidate_coordinates = geocode_hospital_record(hospital)

        if candidate_coordinates is None:
            skipped_geocoding_count += 1
            continue

        # -------------------------------------------------
        # 5. Calculate straight-line distance
        # -------------------------------------------------

        distance_miles = (
            calculate_distance_miles(
                target_coordinates[
                    "latitude"
                ],
                target_coordinates[
                    "longitude"
                ],
                candidate_coordinates[
                    "latitude"
                ],
                candidate_coordinates[
                    "longitude"
                ],
            )
        )

        nearest_candidates.append({
            "facility_id":
                candidate_coordinates[
                    "facility_id"
                ],

            "facility_name":
                candidate_coordinates[
                    "facility_name"
                ],

            "city":
                candidate_coordinates[
                    "city"
                ],

            "state":
                candidate_coordinates[
                    "state"
                ],

            "zip_code":
                candidate_coordinates[
                    "zip_code"
                ],

            "latitude":
                candidate_coordinates[
                    "latitude"
                ],

            "longitude":
                candidate_coordinates[
                    "longitude"
                ],

            "distance_miles":
                distance_miles,
        })

    # -----------------------------------------------------
    # 6. Sort by distance
    # -----------------------------------------------------

    nearest_candidates.sort(
        key=lambda hospital:
            hospital["distance_miles"]
    )

    selected_hospitals = (
        nearest_candidates[:limit]
    )

    # -----------------------------------------------------
    # 7. Return structured result
    # -----------------------------------------------------

    return {
        "target_hospital": {
            "facility_id":
                target_hospital.facility_id,

            "facility_name":
                target_hospital.facility_name,

            "city":
                target_hospital.citytown,

            "state":
                target_hospital.state,

            "zip_code":
                target_hospital.zip_code,

            "latitude":
                target_coordinates[
                    "latitude"
                ],

            "longitude":
                target_coordinates[
                    "longitude"
                ],
        },

        "candidate_scope":
            "same_state",

        "candidate_count":
            len(nearest_candidates),

        "skipped_geocoding_count":
            skipped_geocoding_count,

        "returned_count":
            len(selected_hospitals),

        "nearest_hospitals":
            selected_hospitals,

        "distance_method":
            "Haversine straight-line distance",

        "distance_unit":
            "miles",

        "limitations": [
            (
                "Candidate hospitals are currently limited "
                "to hospitals in the same state."
            ),
            (
                "Distances are straight-line distances, "
                "not driving distance or travel time."
            ),
            (
                "Hospital capacity and service availability "
                "are not considered."
            ),
        ],
    }
from app.services.agent_progress import report_progress
