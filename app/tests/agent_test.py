from app.agents.hospital_agent import ask_hospital_agent


response = ask_hospital_agent(
    "Find the CCN of Greenbrier Valley Medical Center."
)

print(response)