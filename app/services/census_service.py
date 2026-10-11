import os
import threading
from copy import deepcopy

import requests
from dotenv import load_dotenv
from cachetools import TTLCache

from app.common.constants import CENSUS_FIELDS
from app.services.cms_service import get_hospital_by_id
from app.utils.state_utils import get_state_fips


load_dotenv()

# Keep successful lookups for 24 hours. The cache is bounded to avoid
# unbounded memory growth; failed and not-found lookups are not cached.
COUNTY_DEMOGRAPHICS_CACHE = TTLCache(
    maxsize=5000,
    ttl=86400,
)
_COUNTY_DEMOGRAPHICS_CACHE_LOCK = threading.Lock()

# See https://api.census.gov/data/2024/acs/acs5/profile/variables.html.
CENSUS_API_URL = (
    "https://api.census.gov/data/2024/"
    "acs/acs5/profile"
)

CENSUS_API_KEY = os.getenv(
    "CENSUS_API_KEY"
)


def get_county_demographics(
    state_fips: str,
    county_name: str,
) -> dict | None:
    """
    Retrieve basic county demographics from the
    U.S. Census ACS 5-Year Profile.

    Currently returns:
    - total population
    - population age 65+
    - percent age 65+
    """

    if not CENSUS_API_KEY:
        raise ValueError(
            "CENSUS_API_KEY is not configured."
        )

    normalized_county = (
        county_name.strip().upper()
    )
    if normalized_county.endswith(" COUNTY"):
        normalized_county = normalized_county[:-7].strip()

    normalized_state_fips = state_fips.strip()
    cache_key = (
        normalized_state_fips,
        normalized_county,
    )

    # Return a copy so callers cannot mutate the cached value.
    with _COUNTY_DEMOGRAPHICS_CACHE_LOCK:
        cached_result = COUNTY_DEMOGRAPHICS_CACHE.get(cache_key)
        if cached_result is not None:
            return deepcopy(cached_result)

    # Census returns every county in the state; select the requested one
    # locally after the response arrives.
    params = {
        "get": (
            "NAME,"
            f"{CENSUS_FIELDS.TOTAL_POPULATION_FIELD},"
            f"{CENSUS_FIELDS.AGE_65_PLUS_FIELD},"
            f"{CENSUS_FIELDS.AGE_65_PLUS_PERCENT_FIELD}"
        ),
        "for": "county:*",
        "in": f"state:{normalized_state_fips}",
        "key": CENSUS_API_KEY,
    }

    response = requests.get(
        CENSUS_API_URL,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    rows = response.json()

    if len(rows) <= 1:
        return None

    headers = rows[0]

    for row in rows[1:]:

        data = dict(
            zip(headers, row)
        )

        census_name = (
            data["NAME"]
            .split(",")[0]
            .upper()
        )

        # Census county names include the "County" suffix, while callers
        # may pass county names without it.
        census_county_name = census_name
        if census_county_name.endswith(" COUNTY"):
            census_county_name = census_county_name[:-7].strip()

        if (
            census_county_name
            != normalized_county
        ):
            continue

        data = {
            "county":
                normalized_county,

            "state_fips":
                normalized_state_fips,

            "total_population":
                int(
                    data[
                        CENSUS_FIELDS.TOTAL_POPULATION_FIELD
                    ]
                ),

            "population_65_plus":
                int(
                    data[
                        CENSUS_FIELDS.AGE_65_PLUS_FIELD
                    ]
                ),

            "population_65_plus_percent":
                float(
                    data[
                        CENSUS_FIELDS.AGE_65_PLUS_PERCENT_FIELD
                    ]
                ),

            "source":
                "U.S. Census Bureau ACS 2024 5-Year",

            "dataset":
                "ACS Demographic and Housing Estimates",
        }

        # Store a separate copy so the returned object remains independent.
        with _COUNTY_DEMOGRAPHICS_CACHE_LOCK:
            COUNTY_DEMOGRAPHICS_CACHE[cache_key] = deepcopy(data)

        return data

    return None


def get_hospital_demographics(
    facility_id: str,
) -> dict | None:
    """
    Retrieve county-level Census demographics for
    the area containing the selected hospital.

    The hospital's state and county are resolved
    automatically from CMS Hospital General Information.
    """

    # Look up the hospital so its state and county do not need to be
    # supplied separately.
    hospital = get_hospital_by_id(
        facility_id
    )

    if hospital is None:
        return None


    # County demographics cannot be queried without the hospital's county.
    if not hospital.countyparish:
        return {
            "facility_id": facility_id,
            "error": (
                "County information is unavailable "
                "for this hospital."
            ),
        }


    # Census uses the numeric state FIPS code rather than a state
    # abbreviation such as "WV".
    state_fips = get_state_fips(
        hospital.state
    )


    # Reuse the county-level lookup, including its cache.
    demographics = get_county_demographics(
        state_fips=state_fips,
        county_name=hospital.countyparish,
    )

    if demographics is None:
        return {
            "facility_id": facility_id,
            "error": (
                "Census demographics were not found "
                "for the hospital's county."
            ),
        }


    # Include hospital identifiers alongside the county-level estimates.
    return {
        "facility_id":
            hospital.facility_id,

        "facility_name":
            hospital.facility_name,

        "state":
            hospital.state,

        "county":
            hospital.countyparish,

        **demographics,
    }