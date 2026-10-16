from pprint import pprint
from unittest.mock import patch

from app.services.geocoding_service import (
    geocode_hospital,
    HOSPITAL_COORDINATE_CACHE,
)


TEST_FACILITY_ID = "510002"


def test_hospital_geocoding():
    """
    Test that a CMS hospital can be geocoded successfully.
    """

    print("\n=== Hospital Geocoding Test ===")

    # Clear cache so this test actually performs geocoding.
    HOSPITAL_COORDINATE_CACHE.clear()

    result = geocode_hospital(
        TEST_FACILITY_ID
    )

    print("\nGeocoding result:")
    pprint(result)

    assert result is not None

    assert (
        result["facility_id"]
        == TEST_FACILITY_ID
    )

    assert result["facility_name"] is not None
    assert result["address"] is not None
    assert result["city"] is not None
    assert result["state"] is not None
    assert result["zip_code"] is not None

    assert result["latitude"] is not None
    assert result["longitude"] is not None

    assert isinstance(
        result["latitude"],
        (int, float),
    )

    assert isinstance(
        result["longitude"],
        (int, float),
    )

    assert (
        -90
        <= result["latitude"]
        <= 90
    )

    assert (
        -180
        <= result["longitude"]
        <= 180
    )

    assert (
        result["source"]
        == "U.S. Census Bureau Geocoder"
    )

    print(
        "\nHOSPITAL GEOCODING TEST PASSED"
    )


def test_hospital_geocoding_cache():
    """
    Test that the second request for the same hospital
    uses the coordinate cache instead of calling the
    Census Geocoder again.
    """

    print("\n=== Hospital Geocoding Cache Test ===")

    HOSPITAL_COORDINATE_CACHE.clear()

    # First request:
    # should call the external geocoding service.
    first_result = geocode_hospital(
        TEST_FACILITY_ID
    )

    assert first_result is not None

    # Second request:
    # requests.get must NOT be called.
    #
    # If the cache is not working, this patch will cause
    # the test to fail immediately.
    with patch(
        "app.services.geocoding_service.requests.get",
        side_effect=AssertionError(
            "Census Geocoder was called "
            "despite coordinate cache hit."
        ),
    ):
        second_result = geocode_hospital(
            TEST_FACILITY_ID
        )

    assert second_result is not None

    assert (
        first_result
        == second_result
    )

    print(
        "\nHOSPITAL GEOCODING CACHE TEST PASSED"
    )


def run_tests():

    print("=" * 50)
    print("Hospital Geocoding Service Tests")
    print("=" * 50)

    test_hospital_geocoding()
    test_hospital_geocoding_cache()

    print("\n" + "=" * 50)
    print("ALL GEOCODING SERVICE TESTS PASSED")
    print("=" * 50)


if __name__ == "__main__":
    run_tests()