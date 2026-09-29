from app.agents.hospital_agent import ask_hospital_agent


response = ask_hospital_agent(
    "Analyze the financial condition of hospital 510002."
)

print(response)