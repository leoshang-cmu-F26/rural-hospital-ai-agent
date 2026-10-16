"""
Geocoding service for rural hospital locations.

This module:
- retrieves hospital address data from CMS,
- converts hospital addresses to latitude/longitude
  using the U.S. Census Bureau Geocoder,
- caches hospital coordinates to avoid repeated
  external geocoding requests.

The geocoded coordinates are used by later
healthcare-access analysis, such as calculating
distance to alternative hospitals.

Note:
- Geocoding is deterministic and handled outside
  the LLM.
- Cached coordinates are keyed by CMS Certification
  Number (CCN).
"""

from app.services.coordinate_cache import read_coordinate_cache, write_coordinate_cache

import requests
from cachetools import TTLCache
from app.services.cms_service import (
    get_hospital_by_id,
)

CENSUS_GEOCODER_URL = (
    "https://geocoding.geo.census.gov/geocoder/"
    "locations/address"
)


# ---------------------------------------------------------
# Cache
# ---------------------------------------------------------

# Hospital coordinates change very rarely.
# Cache them for 7 days.
HOSPITAL_COORDINATE_CACHE = TTLCache(
    maxsize=5000,
    ttl=604800,
)


# ---------------------------------------------------------
# Address geocoding
# ---------------------------------------------------------

def geocode_address(
    address: str,
    city: str,
    state: str,
    zip_code: str,
) -> dict | None:
    """
    Convert a U.S. street address into latitude and longitude
    using the U.S. Census Bureau Geocoder.

    Returns:
        {
            "latitude": float,
            "longitude": float,
            "matched_address": str | None,
            "source": str
        }

    Returns None if no address match is found.
    """

    # See https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html.
    params = {
        "street": address,
        "city": city,
        "state": state,
        "zip": zip_code,
        "benchmark": "Public_AR_Current",
        "format": "json",
    }

    response = requests.get(
        CENSUS_GEOCODER_URL,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    matches = data.get("result", {}).get("addressMatches", [])

    if not matches:
        return None

    # Use the first Census address match.
    match = matches[0]

    coordinates = match.get(
        "coordinates",
        {},
    )

    # Census Geocoder:
    # x = longitude
    # y = latitude
    longitude = coordinates.get("x")
    latitude = coordinates.get("y")

    if (
        latitude is None
        or longitude is None
    ):
        return None

    return {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "matched_address":
            match.get("matchedAddress"),
        "source":
            "U.S. Census Bureau Geocoder",
    }


# ---------------------------------------------------------
# Hospital geocoding
# ---------------------------------------------------------

def geocode_hospital(
    facility_id: str,
) -> dict | None:
    """
    Retrieve a hospital from CMS and geocode its address.

    The hospital's coordinates are cached using its
    CMS Certification Number (CCN).

    Returns:
        {
            "facility_id": str,
            "facility_name": str,
            "address": str,
            "city": str,
            "state": str,
            "zip_code": str,
            "latitude": float,
            "longitude": float,
            "matched_address": str | None,
            "source": str
        }

    Returns None if:
    - the hospital does not exist,
    - the hospital has no address,
    - or the Census Geocoder cannot match the address.
    """

    # -----------------------------------------------------
    # 1. Check cache
    # -----------------------------------------------------

    if facility_id in HOSPITAL_COORDINATE_CACHE:
        return HOSPITAL_COORDINATE_CACHE[
            facility_id
        ]

    persistent_result = read_coordinate_cache(facility_id)
    if persistent_result is not None:
        HOSPITAL_COORDINATE_CACHE[facility_id] = persistent_result
        return persistent_result

    # -----------------------------------------------------
    # 2. Retrieve hospital information from CMS
    # -----------------------------------------------------

    hospital = get_hospital_by_id(
        facility_id
    )

    if hospital is None:
        return None

    # -----------------------------------------------------
    # 3. Validate address data
    # -----------------------------------------------------

    if not hospital.address:
        return None

    if not hospital.citytown:
        return None

    if not hospital.state:
        return None

    if not hospital.zip_code:
        return None

    # -----------------------------------------------------
    # 4. Geocode hospital address
    # -----------------------------------------------------

    coordinates = geocode_address(
        address=hospital.address,
        city=hospital.citytown,
        state=hospital.state,
        zip_code=hospital.zip_code,
    )

    if coordinates is None:
        return None

    # -----------------------------------------------------
    # 5. Build structured result
    # -----------------------------------------------------

    result = {
        "facility_id":
            hospital.facility_id,

        "facility_name":
            hospital.facility_name,

        "address":
            hospital.address,

        "city":
            hospital.citytown,

        "state":
            hospital.state,

        "zip_code":
            hospital.zip_code,

        "latitude":
            coordinates["latitude"],

        "longitude":
            coordinates["longitude"],

        "matched_address":
            coordinates["matched_address"],

        "source":
            coordinates["source"],
    }

    # -----------------------------------------------------
    # 6. Cache coordinates
    # -----------------------------------------------------

    write_coordinate_cache(result)
    HOSPITAL_COORDINATE_CACHE[
        facility_id
    ] = result

    return result


def geocode_hospital_record(
    hospital: dict,
) -> dict | None:
    """
    Geocode a hospital using an already-retrieved CMS
    hospital record.

    This avoids calling get_hospital_by_id() again when
    hospital information has already been retrieved through
    a state-level CMS query.

    Coordinates are cached by CMS Certification Number (CCN).
    """

    facility_id = hospital.get(
        "facility_id"
    )

    if not facility_id:
        return None

    # -----------------------------------------------------
    # 1. Check coordinate cache
    # -----------------------------------------------------

    if facility_id in HOSPITAL_COORDINATE_CACHE:
        return HOSPITAL_COORDINATE_CACHE[
            facility_id
        ]

    persistent_result = read_coordinate_cache(facility_id)
    if persistent_result is not None:
        HOSPITAL_COORDINATE_CACHE[facility_id] = persistent_result
        return persistent_result

    # -----------------------------------------------------
    # 2. Read address fields directly from CMS record
    # -----------------------------------------------------

    address = hospital.get("address")
    city = hospital.get("citytown")
    state = hospital.get("state")
    zip_code = hospital.get("zip_code")

    if not all([
        address,
        city,
        state,
        zip_code,
    ]):
        return None

    # -----------------------------------------------------
    # 3. Geocode
    # -----------------------------------------------------

    coordinates = geocode_address(
        address=address,
        city=city,
        state=state,
        zip_code=zip_code,
    )

    if coordinates is None:
        return None

    # -----------------------------------------------------
    # 4. Build result
    # -----------------------------------------------------

    result = {
        "facility_id":
            facility_id,

        "facility_name":
            hospital.get(
                "facility_name"
            ),

        "address":
            address,

        "city":
            city,

        "state":
            state,

        "zip_code":
            zip_code,

        "latitude":
            coordinates["latitude"],

        "longitude":
            coordinates["longitude"],

        "matched_address":
            coordinates[
                "matched_address"
            ],

        "source":
            coordinates["source"],
    }

    # -----------------------------------------------------
    # 5. Cache
    # -----------------------------------------------------

    write_coordinate_cache(result)
    HOSPITAL_COORDINATE_CACHE[
        facility_id
    ] = result

    return result