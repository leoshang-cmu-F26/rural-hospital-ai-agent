import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


load_dotenv()


model = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
)


response = model.invoke(
    "Reply with exactly: LLM connection successful."
)


print(response.text)