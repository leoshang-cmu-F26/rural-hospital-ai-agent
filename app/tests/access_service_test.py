from collections import defaultdict
from pprint import pprint

from app.common.constants import HOSPITAL_FIELDS
from app.services.cms_service import get_hospitals_by_state
from app.services.access_service import (
    compare_hospitals_in_area,
    get_healthcare_access_analysis,
)



def test_greenbrier_negative_case():
    """
    Verify the known case where Greenbrier County has
    no other CMS-listed hospitals besides CCN 510002.
    """

    print("\n=== Test 1: Greenbrier County Negative Case ===")

    result = compare_hospitals_in_area(
        "510002",
        "county",
    )

    pprint(result)

    assert result is not None
    assert result["scope"] == "county"
    assert result["area"] == "GREENBRIER"
    assert result["comparison_count"] == 0
    assert result["comparison_hospitals"] == []

    print("PASS: Greenbrier County returned 0 comparison hospitals.")


def find_county_with_multiple_hospitals(state: str = "WV"):
    """
    Find the first county in a state that contains
    more than one CMS-listed hospital.
    """

    hospitals = get_hospitals_by_state(state)

    hospitals_by_county = defaultdict(list)

    for hospital in hospitals:
        county = (
            hospital
            .get(HOSPITAL_FIELDS.COUNTY_PARISH_FIELD, "")
            .strip()
            .upper()
        )

        if county:
            hospitals_by_county[county].append(hospital)

    for county, county_hospitals in hospitals_by_county.items():
        if len(county_hospitals) > 1:
            return county, county_hospitals

    return None, []


def test_positive_county_case():
    """
    Automatically find a county with multiple hospitals,
    then verify compare_hospitals_in_area().
    """

    print("\n=== Test 2: Positive County Comparison ===")

    county, hospitals = find_county_with_multiple_hospitals(
        "WV"
    )

    assert county is not None
    assert len(hospitals) > 1

    print(
        f"Found county: {county} "
        f"with {len(hospitals)} hospitals"
    )

    print("\nHospitals in county:")

    for hospital in hospitals:
        print(
            hospital.get(HOSPITAL_FIELDS.FACILITY_ID_FIELD),
            hospital.get(HOSPITAL_FIELDS.FACILITY_NAME_FIELD),
        )

    target_hospital = hospitals[0]

    target_facility_id = target_hospital[HOSPITAL_FIELDS.FACILITY_ID_FIELD]

    print(
        "\nTesting target hospital:",
        target_facility_id,
        target_hospital[HOSPITAL_FIELDS.FACILITY_NAME_FIELD],
    )

    result = compare_hospitals_in_area(
        target_facility_id,
        "county",
    )

    print("\nComparison result:")

    pprint(result)

    expected_comparison_count = len(hospitals) - 1

    assert result is not None
    assert result["scope"] == "county"
    assert result["area"] == county

    assert (
        result["comparison_count"]
        == expected_comparison_count
    )

    assert (
        len(result["comparison_hospitals"])
        == expected_comparison_count
    )

    print(
        "PASS:",
        f"Expected {expected_comparison_count} comparison hospitals",
        f"and received {result['comparison_count']}.",
    )


def test_zip_case():
    """
    Verify ZIP comparison works for the known hospital.
    """

    print("\n=== Test 3: ZIP Comparison ===")

    result = compare_hospitals_in_area(
        "510002",
        "zip",
    )

    pprint(result)

    assert result is not None
    assert result["scope"] == "zip"
    assert result["area"] == "24970"

    print(
        "PASS:",
        f"ZIP comparison returned "
        f"{result['comparison_count']} other hospitals.",
    )


def run_tests():
    print(
        "\n========================================"
    )
    print(
        "Healthcare Access Service Tests"
    )
    print(
        "========================================"
    )

    # test_greenbrier_negative_case()

    # test_positive_county_case()

    # test_zip_case()

    test_healthcare_access_analysis()

    print(
        "\n========================================"
    )
    print(
        "ALL ACCESS SERVICE TESTS PASSED"
    )
    print(
        "========================================\n"
    )


def test_healthcare_access_analysis():

    print(
        "\n=== Healthcare Access Analysis Test ==="
    )

    result = get_healthcare_access_analysis(
        "510002"
    )

    pprint(result)

    assert result is not None

    assert result["facility_id"] == "510002"
    assert result["state"] == "WV"
    assert result["county"] == "GREENBRIER"

    # CMS hospital alternatives
    assert (
        result["alternative_hospital_count"]
        >= 0
    )

    # Census demographics
    demographics = result[
        "county_demographics"
    ]

    assert demographics["available"] is True

    assert (
        demographics["total_population"]
        > 0
    )

    assert (
        demographics["population_65_plus"]
        > 0
    )

    assert (
        0
        <= demographics[
            "population_65_plus_percent"
        ]
        <= 100
    )

    print(
        "\nHEALTHCARE ACCESS ANALYSIS TEST PASSED"
    )


if __name__ == "__main__":
    run_tests()