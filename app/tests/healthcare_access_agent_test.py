from app.agents.hospital_agent import (
    ask_hospital_agent,
)


def run_test(prompt: str):

    print("\n" + "=" * 70)
    print("PROMPT:")
    print(prompt)
    print("=" * 70)

    response = ask_hospital_agent(prompt)

    print("\nFINAL RESPONSE:")
    print(response)


def run_tests():

    # Test 1:
    # Hospital name -> search_hospital
    # -> analyze_healthcare_access
    run_test(
        "Analyze healthcare access around "
        "Greenbrier Valley Medical Center."
    )

    # Test 2:
    # CCN is already known
    # -> analyze_healthcare_access directly
    run_test(
        "Analyze healthcare access around "
        "hospital 510002."
    )


if __name__ == "__main__":
    run_tests()