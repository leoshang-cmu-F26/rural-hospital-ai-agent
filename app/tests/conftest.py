"""
Shared pytest setup for the offline test suite.

Importing app.main pulls in app.agents.hospital_agent, which builds
the ChatOpenAI client at import time and therefore needs an OpenAI
key to exist even though the offline tests never call OpenAI.
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "offline-test-key")

# Existing fake-CMS suites must never reach a developer's real cloud database.
os.environ.setdefault("FINANCIAL_DATA_MODE", "live")

os.environ.setdefault("REFERENCE_DATA_MODE", "live")
