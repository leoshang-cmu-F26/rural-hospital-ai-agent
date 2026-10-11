from pprint import pprint

from app.services.hrsa_service import (
    get_county_primary_care_hpsa,
)


def test_greenbrier_primary_care_hpsa():

    print(
        "\n=== HRSA Primary Care HPSA Test ==="
    )

    result = get_county_primary_care_hpsa(
        state="WV",
        county="GREENBRIER",
    )

    pprint(result)

    assert result is not None

    assert result["state"] == "West Virginia"
    assert result["county"] == "GREENBRIER"

    assert "designation_count" in result
    assert "designations" in result

    assert (
        result["has_active_primary_care_hpsa"]
        is True
    )

    assert (
        result["active_designation_count"]
        == 1
    )

    assert (
        result["max_hpsa_score"]
        == 18.0
    )

    print(
        "\nHRSA PRIMARY CARE HPSA TEST PASSED"
    )


if __name__ == "__main__":
    test_greenbrier_primary_care_hpsa()