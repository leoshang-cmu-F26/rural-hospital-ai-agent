from pprint import pprint

from app.services.census_service import (
    get_county_demographics,
    get_hospital_demographics,
)


def run_test():

    print(
        "\n=== Census County Demographics Test ==="
    )

    result = get_county_demographics(
        state_fips="54",
        county_name="GREENBRIER",
    )

    pprint(result)

    assert result is not None

    assert (
        result["county"]
        == "GREENBRIER"
    )

    assert (
        result["total_population"]
        > 0
    )

    assert (
        result["population_65_plus"]
        > 0
    )

    assert (
        0
        <= result[
            "population_65_plus_percent"
        ]
        <= 100
    )

    print(
        "\nCENSUS SERVICE TEST PASSED"
    )

def test_hospital_demographics():

    print(
        "\n=== Hospital Demographics Test ==="
    )

    result = get_hospital_demographics(
        "510002"
    )

    pprint(result)

    assert result is not None

    assert (
        result["facility_id"]
        == "510002"
    )

    assert (
        result["state"]
        == "WV"
    )

    assert (
        result["county"]
        == "GREENBRIER"
    )

    assert (
        result["total_population"]
        > 0
    )

    assert (
        result["population_65_plus"]
        > 0
    )

    assert (
        0
        <= result[
            "population_65_plus_percent"
        ]
        <= 100
    )

    print(
        "\nHOSPITAL DEMOGRAPHICS TEST PASSED"
    )


if __name__ == "__main__":
    run_test()
    test_hospital_demographics()