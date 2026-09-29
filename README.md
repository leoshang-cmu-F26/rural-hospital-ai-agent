# Rural Hospital Financial Distress & Healthcare Access Investigation AI Agent

An AI Agent prototype for investigating rural hospital financial condition using public CMS data. This is the class project for 49-797 at CMU-SV.

The current prototype retrieves hospital and cost-report data from CMS, calculates deterministic financial and operational indicators, and uses an LLM-powered agent to generate evidence-based natural-language assessments.

## Current Prototype

The system currently supports:

- Hospital lookup by state
- Hospital search by name
- Hospital lookup by CMS Certification Number (CCN)
- Retrieval of CMS Hospital Provider Cost Report data
- Financial and operational indicator calculation
- Missing-data detection
- LLM tool calling through a LangGraph/LangChain agent
- Natural-language financial analysis through a FastAPI endpoint

## Architecture

```text
User
  |
  v
FastAPI
  |
  v
LangGraph / LangChain Agent
  |
  v
OpenAI LLM
  |
  v
Agent Tool
  |
  +--> CMS Hospital General Information
  |
  +--> CMS Hospital Provider Cost Report
  |
  v
Deterministic Python Analytics
  |
  v
Financial Indicators
  |
  v
LLM Evidence Synthesis
  |
  v
Natural-Language Response
```

## Technology Stack

- Python 3.12
- FastAPI
- Uvicorn
- Pydantic
- LangChain
- LangGraph
- OpenAI API
- Requests
- python-dotenv
- CMS public data APIs

## Project Structure

```text
rural-hospital-ai-agent/
|
|-- app/
|   |-- agents/
|   |   |-- hospital_agent.py
|   |   `-- tests/
|   |       |-- agent_test.py
|   |       `-- llm_test.py
|   |
|   |-- api/
|   |   `-- routes.py
|   |
|   |-- models/
|   |   |-- agent.py
|   |   |-- financial.py
|   |   `-- hospital.py
|   |
|   |-- services/
|   |   |-- cms_service.py
|   |   `-- cost_report_service.py
|   |
|   |-- tools/
|   |   |-- agent_tools.py
|   |   `-- financial_tools.py
|   |
|   |-- utils/
|   |   `-- state_utils.py
|   |
|   `-- main.py
|
|-- .env
|-- .gitignore
|-- requirements.txt
`-- README.md
```

## Setup

### 1. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

For Git Bash:

```bash
source .venv/Scripts/activate
```

### 2. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-5.6-terra
```

Do not commit `.env` to Git.

## Run the API

```bash
python -m uvicorn app.main:app --reload
```

Open the Swagger API documentation:

```text
http://127.0.0.1:8000/docs
```

## Main API Endpoints

### Health Check

```http
GET /health
```

### Hospitals by State

```http
GET /hospitals?state=CA
GET /hospitals?state=California
```

### Search Hospitals by Name

```http
GET /hospitals/search?name=STEVENS
```

### Hospital by CCN

```http
GET /hospitals/{facility_id}
```

Example:

```http
GET /hospitals/510002
```

### Hospital Financial Data

```http
GET /hospitals/{facility_id}/financials
```

### Hospital Financial Indicators

```http
GET /hospitals/{facility_id}/indicators
```

Current indicators include:

- Occupancy rate
- Operating margin
- Liability-to-asset ratio
- Cost-to-charge ratio

If required CMS fields are unavailable, the API returns `null` for the affected indicator and identifies the missing fields.

### AI Agent

```http
POST /agent/chat
```

Example request:

```json
{
  "message": "Analyze the financial condition of hospital 510002."
}
```

The agent determines when to call the hospital financial-analysis tool, retrieves CMS data, executes deterministic calculations, and generates a natural-language assessment.

## Testing

Test the OpenAI connection:

```bash
python -m app.agents.tests.llm_test
```

Test the Agent workflow:

```bash
python -m app.agents.tests.agent_test
```

A successful Agent execution should include this internal flow:

```text
HumanMessage
AIMessage
ToolMessage
AIMessage
```

This confirms that the LLM selected and invoked the financial-analysis tool rather than relying only on its internal knowledge.

## Data Sources

Current prototype:

- CMS Hospital General Information
- CMS Hospital Provider Cost Report

Planned future sources:

- HRSA
- U.S. Census
- Additional rural healthcare and geographic-access datasets

## Planned Next Steps

- Hospital-name-based Agent lookup
- Multi-year financial trend analysis
- Healthcare-access impact analysis
- HRSA and Census integration
- Peer rural-hospital comparison
- RAG-based retrieval from government reports and methodology documents
- Visualization and frontend interface

## Security

Never commit secrets such as API keys.

The following should remain ignored by Git:

```text
.env
.venv/
__pycache__/
```

## Status

Current status: working end-to-end AI Agent prototype with CMS retrieval, deterministic financial analytics, missing-data handling, LLM tool calling, and FastAPI integration.
