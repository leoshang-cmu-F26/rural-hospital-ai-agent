"""
Live agent test for the multi-year trend tool. Requires OPENAI_API_KEY.
Run with: python -m app.tests.trend_agent_test
"""

from app.agents.hospital_agent import hospital_agent


def run_test(prompt: str):
    print("\n" + "=" * 70)
    print("PROMPT:")
    print(prompt)
    print("=" * 70)

    result = hospital_agent.invoke(
        {"messages": [{"role": "user", "content": prompt}]}
    )

    print("\nTOOL CALLS:")
    for message in result["messages"]:
        for tool_call in getattr(message, "tool_calls", None) or []:
            print(f"  {tool_call['name']}({tool_call['args']})")

    print("\nFINAL RESPONSE:")
    print(result["messages"][-1].text)


def run_tests():
    # Expected: analyze_financial_trend("510002") directly.
    run_test(
        "How has the financial condition of hospital 510002 "
        "changed over the past five years?"
    )

    # Expected: search_hospital -> analyze_financial_trend(
    #   start_year=2018, end_year=2024)
    run_test(
        "Show the financial trend of Greenbrier Valley Medical "
        "Center from 2018 to 2024. How many years in a row has it "
        "lost money?"
    )


if __name__ == "__main__":
    run_tests()
