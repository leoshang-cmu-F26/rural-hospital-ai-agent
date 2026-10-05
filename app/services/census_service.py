import os
import requests
from dotenv import load_dotenv
from app.common.constants import CENSUS_FIELDS
from app.services.cms_service import get_hospital_by_id
from app.utils.state_utils import get_state_fips


load_dotenv()

# See https://api.census.gov/data/2024/acs/acs5/examples.html.
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
        county_name
        .strip()
        .upper()
    )

    # Census field names. 
    # See https://api.census.gov/data/2014/pep/natstprc/variables.html.
    params = {
        "get": (
            "NAME,"
            f"{CENSUS_FIELDS.TOTAL_POPULATION_FIELD},"
            f"{CENSUS_FIELDS.AGE_65_PLUS_FIELD},"
            f"{CENSUS_FIELDS.AGE_65_PLUS_PERCENT_FIELD}"
        ),
        "for": "county:*",
        "in": f"state:{state_fips}",
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

        # Example:
        # "Greenbrier County"
        #
        # CMS gives:
        # "GREENBRIER"
        census_county_name = (
            census_name
            .replace(" COUNTY", "")
            .strip()
        )

        if (
            census_county_name
            != normalized_county
        ):
            continue

        return {
            "county":
                county_name,

            "state_fips":
                state_fips,

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

    # 1. Find hospital from CMS
    hospital = get_hospital_by_id(
        facility_id
    )

    if hospital is None:
        return None


    # 2. Ensure county information is available
    if not hospital.countyparish:
        return {
            "facility_id": facility_id,
            "error": (
                "County information is unavailable "
                "for this hospital."
            ),
        }


    # 3. Convert hospital state to Census state FIPS
    state_fips = get_state_fips(
        hospital.state
    )


    # 4. Retrieve county demographics
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


    # 5. Combine hospital context with Census data
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