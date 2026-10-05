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

    # --------------------------------------------------
    # Test 1:
    # Hospital name -> demographics
    #
    # Expected:
    # search_hospital
    # -> get_hospital_demographics
    # --------------------------------------------------

    run_test(
        "What are the demographics around "
        "Greenbrier Valley Medical Center?"
    )


    # --------------------------------------------------
    # Test 2:
    # CCN already known
    #
    # Expected:
    # get_hospital_demographics directly
    # --------------------------------------------------

    run_test(
        "What are the county demographics "
        "for hospital 510002?"
    )


    # --------------------------------------------------
    # Test 3:
    # Explicit question about age 65+
    #
    # Expected:
    # search_hospital
    # -> get_hospital_demographics
    # --------------------------------------------------

    run_test(
        "What percentage of people age 65 or older "
        "live in the county containing "
        "Greenbrier Valley Medical Center?"
    )


if __name__ == "__main__":
    run_tests()