from app.agents.hospital_agent import ask_hospital_agent


def run_test(prompt: str):
    print("\n" + "=" * 70)
    print("PROMPT:")
    print(prompt)
    print("=" * 70)

    response = ask_hospital_agent(prompt)

    print("\nFINAL RESPONSE:")
    print(response)


def run_tests():

    # --------------------------------------------------
    # Test 1: Hospital name -> county comparison
    # Expected:
    # search_hospital
    # -> compare_hospitals_by_area(scope="county")
    # --------------------------------------------------

    run_test(
        "Compare West Virginia University Hospitals "
        "with other hospitals in the same county."
    )


    # --------------------------------------------------
    # Test 2: Hospital name -> ZIP comparison
    # Expected:
    # search_hospital
    # -> compare_hospitals_by_area(scope="zip")
    # --------------------------------------------------

    run_test(
        "Compare Greenbrier Valley Medical Center "
        "with other hospitals in the same ZIP code."
    )


    # --------------------------------------------------
    # Test 3: Hospital name -> state comparison
    # Expected:
    # search_hospital
    # -> compare_hospitals_by_area(scope="state")
    # --------------------------------------------------

    run_test(
        "Compare Greenbrier Valley Medical Center "
        "with other hospitals in the same state."
    )


    # --------------------------------------------------
    # Test 4: CCN already known
    # Expected:
    # compare_hospitals_by_area directly
    # No search_hospital needed
    # --------------------------------------------------

    run_test(
        "Compare hospital 510001 with other hospitals "
        "in the same county."
    )


if __name__ == "__main__":
    run_tests()