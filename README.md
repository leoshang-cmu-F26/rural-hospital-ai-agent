# Rural Hospital Financial Distress & Healthcare Access Investigation AI Agent

An AI Agent prototype for investigating rural hospital financial condition using public CMS data. This is the class project for 49-797 at CMU-SV.

The prototype retrieves hospital and cost-report data from CMS, calculates deterministic financial and operational indicators for a single year and across multiple years, and uses an LLM-powered agent to generate evidence-based natural-language assessments.

## Current Prototype

The system currently supports:

- Hospital lookup by state, by name, and by CMS Certification Number (CCN)
- Retrieval of CMS Hospital Provider Cost Report data for any dataset year from 2011 to the latest release
- Runtime discovery of CMS cost-report dataset IDs from the CMS catalog (see [CMS Cost Report Dataset Discovery](#cms-cost-report-dataset-discovery))
- Financial and operational indicator calculation with missing-data detection and the CMS rural/urban classification
- Multi-year financial trend analysis with deterministic trend directions and distress signals
- Same-county, same-ZIP, and same-state hospital comparison
- Preliminary county-level healthcare-access proxy
- LLM tool calling through a LangGraph/LangChain agent
- FastAPI endpoints and a minimal chat UI served at `/demo`

## Architecture

```text
User (Swagger UI, /demo chat page, or API client)
  |
  v
FastAPI
  |
  v
LangGraph / LangChain Agent
  |
  v
OpenAI LLM  (intent, tool selection, explanation)
  |
  v
Agent Tools
  |
  +--> search_hospital / get_hospital_by_ccn
  |      `--> CMS Hospital General Information
  |
  +--> analyze_hospital_financials / analyze_financial_trend
  |      `--> CMS Hospital Provider Cost Report (2011 - latest)
  |             `--> dataset IDs discovered from https://data.cms.gov/data.json
  |
  +--> compare_hospitals_by_area / analyze_healthcare_access
  |      `--> CMS Hospital General Information
  |
  +--> get_hospital_demographics / analyze_healthcare_access
         `--> U.S. Census ACS 2024 5-Year (county population, age 65+)
  |
  v
Deterministic Python Analytics
  (indicators, trend directions, distress signals)
  |
  v
LLM Evidence Synthesis
  |
  v
Natural-Language Response
```

## Technology Stack

- Python 3.12
- FastAPI, Uvicorn, Pydantic
- LangChain, LangGraph, OpenAI API
- Requests, cachetools, python-dotenv
- pytest (offline unit tests)
- CMS public data APIs

## Project Structure

```text
rural-hospital-ai-agent/
|
|-- app/
|   |-- agents/
|   |   |-- agent.py                 # AgentRequest / AgentResponse models
|   |   `-- hospital_agent.py        # LangChain agent + system prompt
|   |
|   |-- api/
|   |   `-- routes.py
|   |
|   |-- common/
|   |   `-- constants.py
|   |
|   |-- models/
|   |   |-- financial.py             # cost-report record, indicators, history, trend
|   |   `-- hospital.py
|   |
|   |-- services/
|   |   |-- access_service.py        # same-county / ZIP / state comparison + access proxy
|   |   |-- census_service.py        # U.S. Census ACS county demographics
|   |   |-- cms_service.py           # CMS Hospital General Information
|   |   `-- cost_report_service.py   # cost reports, dataset discovery, multi-year history
|   |
|   |-- tools/
|   |   |-- agent_tools.py           # LangChain @tool wrappers
|   |   |-- financial_tools.py       # indicator calculations
|   |   `-- trend_tools.py           # multi-year trend math
|   |
|   |-- tests/
|   |   |-- conftest.py                  # offline test setup
|   |   |-- test_financial_tools.py      # offline unit tests (pytest)
|   |   |-- test_integration.py          # offline integration tests (pytest)
|   |   |-- access_service_test.py       # live CMS + Census, no LLM
|   |   |-- census_service_test.py       # live Census, no LLM
|   |   |-- financial_trend_test.py      # live CMS, no LLM
|   |   |-- llm_test.py                  # live OpenAI
|   |   |-- agent_test.py                # live OpenAI + CMS
|   |   |-- area_comparison_agent_test.py
|   |   |-- demographics_agent_test.py
|   |   |-- healthcare_access_agent_test.py
|   |   `-- trend_agent_test.py
|   |
|   |-- utils/
|   |   `-- state_utils.py
|   |
|   `-- main.py
|
|-- frontend/                        # minimal chat UI served at /demo
|   |-- index.html
|   |-- app.js
|   `-- style.css
|
|-- .env.example
|-- .gitignore
|-- pytest.ini
|-- requirements.txt
`-- README.md
```

## Setup

### 1. Create and activate a virtual environment

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Windows Git Bash:

```bash
source .venv/Scripts/activate
```

### 2. Install dependencies

```bash
python -m pip install -r requirements.txt
```

Re-run this whenever `requirements.txt` changes; a stale virtual environment is the most common reason the app fails to import.

### 3. Configure environment variables

Copy the template and fill in your key:

```bash
cp .env.example .env
```

```env
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-5.6-terra
CENSUS_API_KEY=your_census_api_key
```

`CENSUS_API_KEY` is a free key from https://api.census.gov/data/key_signup.html. It is needed for county demographics and the healthcare-access analysis; without it those tools still run but report demographics as unavailable.

`.env` is git-ignored. Never commit it.

## Run the API

From the project root:

```bash
python -m uvicorn app.main:app --reload
```

- Swagger UI: http://127.0.0.1:8000/docs
- Chat demo: http://127.0.0.1:8000/demo/

On startup the app downloads the CMS catalog in the background so the first financial request is fast.

## Main API Endpoints

### Health and hospital lookup

```http
GET /health
GET /hospitals?state=CA
GET /hospitals/search?name=STEVENS
GET /hospitals/{facility_id}
```

### Cost-report datasets

```http
GET /datasets/cost-reports
```

Lists the CMS cost-report dataset IDs currently known to the service, one per report year. Use it to confirm that catalog discovery is working.

### Single-year financials

```http
GET /hospitals/{facility_id}/financials
GET /hospitals/{facility_id}/financials?year=2019
GET /hospitals/{facility_id}/financials/raw?year=2019
GET /hospitals/{facility_id}/indicators
GET /hospitals/{facility_id}/indicators?year=2019
```

Without `year`, the most recent dataset year in which the hospital filed a report is used.

Current indicators:

| Indicator | Formula | Source fields |
|---|---|---|
| Occupancy rate (%) | total_days / total_bed_days_available x 100 | Total Days, Total Bed Days Available |
| Operating margin (%) | net_income_from_service / net_patient_revenue x 100 | Net Income from Service to Patients, Net Patient Revenue |
| Liability-to-asset ratio (%) | total_liabilities / total_assets x 100 | Total Liabilities, Total Assets |
| Cost-to-charge ratio | reported directly by CMS | Cost To Charge Ratio |

Each indicator response also includes `report_year`, the fiscal period, `rural_versus_urban` (`R` / `U` as reported by CMS), and `is_rural`. If a required field is unavailable the indicator is `null` and the field is listed in `missing_fields`. Values are passed through as reported: some hospitals report negative fund balances or assets, so ratios can be negative or exceed 100%.

### Multi-year history and trend

```http
GET /hospitals/{facility_id}/financials/history?start_year=2020&end_year=2024
GET /hospitals/{facility_id}/trend
GET /hospitals/{facility_id}/trend?start_year=2018&end_year=2024
```

Without a range, the most recent five dataset years are used. Years are fetched in parallel and classified as:

- `years_with_data`: a cost report was found
- `years_without_report`: the dataset was reachable but the hospital filed no report
- `years_unavailable`: the dataset could not be retrieved, with the reason

The trend response contains per-year indicators, an `indicator_trends` entry per indicator (first/last available year and value, absolute `change`, and a `direction`), and distress signals: years with negative operating margin, the number of consecutive negative-margin years ending at the latest year, years in which liabilities exceeded assets, and the average operating margin.

Direction semantics:

| Indicator | Better when | "stable" band |
|---|---|---|
| operating_margin | higher | change < 1 percentage point |
| occupancy_rate | higher | change < 1 percentage point |
| liability_to_asset_ratio | lower | change < 1 percentage point |
| cost_to_charge_ratio | no judgement; reported as `increased` / `decreased` | change < 0.01 |

### AI Agent

```http
POST /agent/chat
```

```json
{
  "message": "How has the financial condition of hospital 510002 changed over the past five years?"
}
```

## Agent Tools

| Tool | Purpose | Data source |
|---|---|---|
| `search_hospital` | Resolve a hospital name to CCN and basic information | Hospital General Information |
| `get_hospital_by_ccn` | Basic information for a known CCN | Hospital General Information |
| `analyze_hospital_financials` | Single-year indicators (latest year or `year=`), including rural flag | Hospital Provider Cost Report |
| `analyze_financial_trend` | Multi-year indicators, trend directions, distress signals | Hospital Provider Cost Report |
| `compare_hospitals_by_area` | Other CMS-listed hospitals in the same county / ZIP / state | Hospital General Information |
| `analyze_healthcare_access` | Same-county access proxy plus county demographics | Hospital General Information + Census ACS |
| `get_hospital_demographics` | County population, population 65+, and percent 65+ | U.S. Census ACS 2024 5-Year |

All numbers are computed in Python; the LLM is used for intent understanding, tool routing, and explanation only. The system prompt instructs the agent to cite the data source, state missing data explicitly, and avoid predicting closure or recovery from historical trends.

## CMS Cost Report Dataset Discovery

CMS publishes one Hospital Provider Cost Report dataset per report year and re-issues the dataset UUIDs without notice (every ID changed on 2026-09-30, and three changed again on 2026-10-05). Hard-coding an ID therefore breaks within days.

`app/services/cost_report_service.py` handles this by:

1. Downloading the CMS catalog (`https://data.cms.gov/data.json`) and extracting `{year: dataset_id}` from entries titled `Hospital Provider Cost Report : <year>-...`; the result is cached for six hours.
2. Refreshing the catalog automatically (with a cooldown) when a cached ID returns HTTP 404, then retrying once with the new ID.
3. Falling back to a bundled snapshot of the IDs when the catalog itself cannot be downloaded.

Dataset years are cost-report years, not calendar years: a hospital's fiscal period inside the 2019 dataset may run from May 2019 to April 2020. Responses always include the fiscal period.

## Testing

Offline tests (no network, no API key). `test_financial_tools.py` covers the indicator and trend math; `test_integration.py` runs the FastAPI routes, agent tools, cost-report service and analytics together with the CMS, Census and OpenAI boundaries faked, covering normal, edge and failure scenarios:

```bash
pytest
```

Live scripts (each hits CMS and/or OpenAI; run individually):

```bash
python -m app.tests.llm_test                    # OpenAI connection
python -m app.tests.agent_test                  # name -> CCN agent flow
python -m app.tests.access_service_test         # area comparison + access analysis (CMS + Census)
python -m app.tests.census_service_test         # county demographics (Census only)
python -m app.tests.financial_trend_test        # multi-year cost reports (CMS only)
python -m app.tests.trend_agent_test            # trend tool through the agent
python -m app.tests.area_comparison_agent_test  # area comparison through the agent
python -m app.tests.demographics_agent_test     # demographics through the agent
python -m app.tests.healthcare_access_agent_test # access analysis through the agent
```

A successful agent run shows the message flow `HumanMessage -> AIMessage (tool call) -> ToolMessage -> AIMessage`, confirming that the LLM used a tool instead of its own knowledge.

## Data Sources

Current:

- CMS Hospital General Information
- CMS Hospital Provider Cost Report, dataset years 2011 to the latest release
- U.S. Census Bureau ACS 2024 5-Year estimates (county population and age 65+)

Planned:

- HRSA
- Additional Census variables and rural healthcare / geographic-access datasets

## Planned Next Steps

- Conversation memory so the agent can follow up on clarification questions (next sprint, P0)
- Markdown rendering in the `/demo` chat UI (next sprint, P0)
- Tool-error handling inside the agent loop and a CI workflow running `pytest` (next sprint, P0)
- Additional indicators from the cost report (current ratio, cash on hand, charity care, bad debt)
- Peer rural-hospital financial comparison
- Distance- and travel-time-based healthcare-access analysis
- HRSA and Census integration
- RAG-based retrieval from CMS methodology documents
- Trend visualization

## Security

Never commit secrets such as API keys. The following remain ignored by Git:

```text
.env
.venv/
__pycache__/
.pytest_cache/
```

## Status

Working end-to-end AI Agent prototype with CMS retrieval, runtime dataset discovery, single-year and multi-year deterministic financial analytics, missing-data handling, LLM tool calling, FastAPI integration, and a minimal chat UI.
