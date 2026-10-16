from pprint import pprint

from app.services.distance_service import (
    calculate_distance_miles,
    get_nearest_hospitals,
)


TEST_FACILITY_ID = "510002"


def test_distance_calculation():
    """
    Verify that the Haversine calculation produces
    a valid positive distance.
    """

    print(
        "\n=== Haversine Distance Test ==="
    )

    # Two example coordinates.
    distance = calculate_distance_miles(
        latitude_1=37.77214337932,
        longitude_1=-80.469134324531,
        latitude_2=38.0,
        longitude_2=-80.5,
    )

    print(
        f"Calculated distance: "
        f"{distance} miles"
    )

    assert distance > 0
    assert distance < 100

    print(
        "HAVERSINE DISTANCE TEST PASSED"
    )


def test_zero_distance():
    """
    Identical coordinates should produce
    zero distance.
    """

    print(
        "\n=== Zero Distance Test ==="
    )

    distance = calculate_distance_miles(
        latitude_1=37.77214337932,
        longitude_1=-80.469134324531,
        latitude_2=37.77214337932,
        longitude_2=-80.469134324531,
    )

    assert distance == 0

    print(
        "ZERO DISTANCE TEST PASSED"
    )


def test_nearest_hospitals():
    """
    Find nearest alternative hospitals for CCN 510002.
    """

    print(
        "\n=== Nearest Hospitals Test ==="
    )

    result = get_nearest_hospitals(
        facility_id=TEST_FACILITY_ID,
        limit=5,
    )

    print(
        "\nNearest hospital result:"
    )

    pprint(result)

    assert result is not None

    assert (
        result["target_hospital"][
            "facility_id"
        ]
        == TEST_FACILITY_ID
    )

    assert (
        result["candidate_scope"]
        == "same_state"
    )

    assert (
        result["returned_count"]
        <= 5
    )

    nearest_hospitals = result[
        "nearest_hospitals"
    ]

    assert len(nearest_hospitals) > 0

    # Target hospital must not appear
    # in alternative hospitals.
    assert all(
        hospital["facility_id"]
        != TEST_FACILITY_ID
        for hospital
        in nearest_hospitals
    )

    # Every returned hospital should have
    # a valid non-negative distance.
    assert all(
        hospital["distance_miles"]
        >= 0
        for hospital
        in nearest_hospitals
    )

    # Verify ascending distance order.
    distances = [
        hospital["distance_miles"]
        for hospital
        in nearest_hospitals
    ]

    assert distances == sorted(
        distances
    )

    print(
        "\nNEAREST HOSPITALS TEST PASSED"
    )


def run_tests():

    print("=" * 50)
    print("Hospital Distance Service Tests")
    print("=" * 50)

    test_distance_calculation()
    test_zero_distance()
    test_nearest_hospitals()

    print("\n" + "=" * 50)
    print(
        "ALL DISTANCE SERVICE TESTS PASSED"
    )
    print("=" * 50)


if __name__ == "__main__":
    run_tests()