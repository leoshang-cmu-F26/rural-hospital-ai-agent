from unittest.mock import patch

from app.services.census_service import (
    get_county_demographics,
    COUNTY_DEMOGRAPHICS_CACHE,
)

from app.services.hrsa_service import (
    get_county_primary_care_hpsa,
    PRIMARY_CARE_HPSA_CACHE,
)


def test_census_cache():

    print("\n=== Census Cache Test ===")

    # Make sure the first call is a cache miss
    COUNTY_DEMOGRAPHICS_CACHE.clear()

    # First call should access Census API
    first_result = get_county_demographics(
        state_fips="54",
        county_name="GREENBRIER",
    )

    assert first_result is not None

    # If HTTP is called again, fail immediately.
    with patch(
        "app.services.census_service.requests.get",
        side_effect=AssertionError(
            "Census API was called despite cache hit"
        ),
    ):
        second_result = get_county_demographics(
            state_fips="54",
            county_name="GREENBRIER",
        )

    assert first_result == second_result

    print("CENSUS CACHE TEST PASSED")


def test_hrsa_cache():

    print("\n=== HRSA Cache Test ===")

    # Make sure the first call is a cache miss
    PRIMARY_CARE_HPSA_CACHE.clear()

    # First call should access HRSA API
    first_result = get_county_primary_care_hpsa(
        state="WV",
        county="GREENBRIER",
    )

    assert first_result is not None

    # Second call must come from cache.
    with patch(
        "app.services.hrsa_service.requests.get",
        side_effect=AssertionError(
            "HRSA API was called despite cache hit"
        ),
    ):
        second_result = get_county_primary_care_hpsa(
            state="WV",
            county="GREENBRIER",
        )

    assert first_result == second_result

    print("HRSA CACHE TEST PASSED")


if __name__ == "__main__":

    print("=" * 40)
    print("External Service Cache Tests")
    print("=" * 40)

    test_census_cache()
    test_hrsa_cache()

    print("\n" + "=" * 40)
    print("ALL CACHE TESTS PASSED")
    print("=" * 40)