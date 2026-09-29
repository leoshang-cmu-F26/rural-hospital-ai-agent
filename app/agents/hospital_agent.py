import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.tools.agent_tools import analyze_hospital_financials


load_dotenv()


model = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL", "gpt-5.6-terra"),
    use_responses_api=True,
    output_version="responses/v1",
)


SYSTEM_PROMPT = """
You are a rural hospital financial investigation AI agent.

Your job is to help users investigate rural hospital financial
and operational conditions using reliable public data.

When the user asks about a hospital's financial condition,
operating margin, occupancy rate, liability-to-asset ratio,
or cost-to-charge ratio, use the available financial analysis tool.

Do not invent missing financial data.

If an indicator is unavailable because required CMS data is missing,
clearly explain that limitation.

Always mention that the financial data comes from the
CMS Hospital Provider Cost Report when using the financial tool.
"""


hospital_agent = create_agent(
    model=model,
    tools=[
        analyze_hospital_financials,
    ],
    system_prompt=SYSTEM_PROMPT,
)


def ask_hospital_agent(message: str) -> str:
    result = hospital_agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": message,
                }
            ]
        }
    )

    # for msg in result["messages"]:
    #     print(type(msg).__name__, msg)

    final_message = result["messages"][-1]

    return final_message.text