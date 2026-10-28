# Rural Hospital Financial Distress & Healthcare Access Investigation AI Agent

An AI Agent prototype for investigating hospital finances, financial trends, and healthcare-access context using public CMS, Census, and HRSA data. This is the class project for 49-797 at CMU-SV.

**[Try the live Agent demo](https://rural-hospital-ai-agent.onrender.com/demo/)**

The chat frontend is served at `/demo/`; the root URL shows the API status. The hosted service may take time to wake up after inactivity. Repository updates appear in the hosted demo only after deployment. Initial statewide analyses may take several minutes while source data and coordinates are retrieved.

The prototype retrieves hospital and cost-report data from CMS, calculates deterministic financial and operational indicators for a single year and across multiple years, and uses an LLM-powered agent to generate evidence-based natural-language assessments.

## Historical financial database

The backend now supports Supabase/PostgreSQL financial snapshots. With
`DATABASE_URL` configured, financial analysis defaults to `database_only` mode:
reports and available years come from completed database imports, not live CMS
requests. Missing coverage is disclosed instead of interpreted as no filing.

Wisconsin and Wyoming 2020–2024 have been imported and verified: **900 report rows**
(753 WI + 147 WY), preserving all source fields and multiple reports. Results include source retrieval/import
dates; "latest" in this mode means the latest imported year. WI/WY hospital identity, ACS 2024 county estimates, HRSA primary-care features
and available coordinates are now stored too. Set `REFERENCE_DATA_MODE=database_only`
to use those dated snapshots; arbitrary new addresses may still require online matching.
See [reference import scope, refresh commands and capacity assessment](docs/reference_database.md).

A separate update command compares official catalog versions and only downloads
new/revised CSVs. It is not run in a user's analysis request. See
[setup, import/update commands, table inspection and coverage](docs/financial_database.md).

## Current Prototype

The system currently supports:

- Hospital lookup by state, by name, and by CMS Certification Number (CCN)
- Retrieval of CMS Hospital Provider Cost Report data for any dataset year from 2011 to the latest release
- Runtime discovery of CMS cost-report dataset IDs from the CMS catalog (see [CMS Cost Report Dataset Discovery](#cms-cost-report-dataset-discovery))
- Financial and operational indicator calculation with missing-data detection and the CMS rural/urban classification
- Multi-year financial trend analysis with deterministic trend directions and distress signals
- Same-county, same-ZIP, and same-state hospital comparison
- County-level healthcare-access analysis combining CMS hospital comparisons, Census demographics, and HRSA Primary Care HPSA designations
- Full hospital investigations and two-hospital comparisons with report-year and fiscal-period alignment checks
- State, county, and ZIP hospital-cohort access analysis, with an optional rural-only filter
- Dated non-rural hospital reminders and visible data-quality notices for unreliable ratios, fiscal periods, missing evidence, and trend reversals
- Address-based access analysis for facilities with user-confirmed physical addresses
- Historical CMS/IHS tribal-facility directory lookup, with institution types and PDF source pages
- Local methodology RAG over reviewed CMS, Census, and HRSA document snapshots using SQLite FTS5/BM25
- Bounded conversation context, streamed progress, source/coverage cards, and safe Markdown rendering
- LLM tool calling through a LangGraph/LangChain agent
- FastAPI endpoints and a chat UI served at `/demo/`

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
  +--> resolve_facility
  |      `--> Current CMS hospitals + historical tribal directory + rural context
  |
  +--> analyze_hospital_financials / analyze_financial_trend
  |      `--> CMS Hospital Provider Cost Report (2011 - latest)
  |             `--> dataset IDs discovered from https://data.cms.gov/data.json
  |
  +--> investigate_hospital / compare_hospital_investigations
  |      `--> Financials + trends + access, with data-quality checks
  |
  +--> compare_hospitals_by_area / analyze_healthcare_access
  |      `--> CMS hospitals + county evidence + same-state distance ranking
  |
  +--> analyze_area_healthcare_access / analyze_facility_access_by_address
  |      `--> State/county/ZIP cohorts or user-confirmed address context
  |
  +--> search_methodology_documents
  |      `--> Reviewed document snapshots + local SQLite FTS5/BM25 retrieval
  |
  `--> get_hospital_demographics / analyze_healthcare_access
         `--> U.S. Census Bureau ACS / HRSA GIS service
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
- Supabase/PostgreSQL financial snapshots using psycopg and a small TLS connection pool
- SQLite coordinate caching and regenerable directory/methodology indexes
- HTML, CSS, JavaScript, and a safe DOM-based Markdown renderer
- pytest (offline unit tests)
- CMS, U.S. Census Bureau ACS, and HRSA public data APIs

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
|   |   |-- access_service.py        # area comparison + combined access analysis
|   |   |-- census_service.py        # county ACS demographics
|   |   |-- cms_service.py           # CMS Hospital General Information
|   |   |-- cost_report_service.py   # cost reports, dataset discovery, multi-year history
|   |   `-- hrsa_service.py          # county-associated Primary Care HPSAs
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
|   |   |-- access_service_test.py       # live CMS + Census + HRSA, no LLM
|   |   |-- census_service_test.py       # live Census, no LLM
|   |   |-- hrsa_service_test.py         # live HRSA, no LLM
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

On startup the app warms the CMS catalog in the background. This reduces later catalog lookup work but does not guarantee a fast first analysis.

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

Each indicator response also includes `report_year`, the fiscal period, `rural_versus_urban` (`R` / `U` in the supported structured data), and `is_rural`. Missing inputs appear in `missing_fields`; zero denominators are distinct from missing values. Negative assets or revenue may produce traceable signed ratios, but affected metrics appear in `blocked_metrics` and must not be interpreted conventionally or used for direct comparisons. Non-finite computed values become `null`. `quality_warnings` describe verification steps.

An urban classification triggers a dated non-rural notice without refusing analysis. Unknown classification is neither rural nor urban; a cost-report classification does not establish current rural status under every geographic definition.

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
POST /agent/chat/stream
```

```json
{
  "message": "How has the financial condition of hospital 510002 changed over the past five years?"
}
```

The browser uses `/agent/chat/stream`, which emits newline-delimited JSON progress, warnings, evidence, context, and result/error events. It sends bounded recent history and compact active hospital/comparison identities. Refreshing or clearing chat resets browser-owned context; there is no persistent account-level conversation memory.

## Agent Tools

| Tool | Purpose | Data source |
|---|---|---|
| `resolve_facility` | Compact name/location or CCN resolution, current verification and rural context | CMS hospitals + historical directory + cost reports |
| `investigate_hospital` | Full financial, trend and access investigation | CMS + Census + HRSA |
| `compare_hospital_investigations` | Two hospitals with fiscal alignment checks | CMS + Census + HRSA |
| `analyze_hospital_financials` | Single-year indicators (latest year or `year=`), including rural flag | Hospital Provider Cost Report |
| `analyze_financial_trend` | Multi-year indicators, trend directions, distress signals | Hospital Provider Cost Report |
| `compare_hospitals_by_area` | Other CMS-listed hospitals in the same county / ZIP / state | Hospital General Information |
| `analyze_healthcare_access` | Same-county access proxy, county demographics, and Primary Care HPSA designations | CMS Hospital General Information + Census ACS + HRSA |
| `get_hospital_demographics` | County population, population 65+, and percent 65+ | U.S. Census ACS 2024 5-Year |
| `analyze_area_healthcare_access` | State/county/ZIP hospital cohorts, with optional rural filtering | CMS + Census + HRSA + cached coordinates |
| `analyze_facility_access_by_address` | Access context at a user-confirmed full physical address | Census Geocoder + CMS + Census + HRSA |
| `search_tribal_facility_directory` | Historical institution types, listed CCNs and source pages | CMS/IHS 2020 directory |
| `search_methodology_documents` | Short cited passages explaining methods and limitations | Reviewed CMS, Census and HRSA snapshots |

Legacy `search_hospital` and `get_hospital_by_ccn` wrappers remain for compatibility, but the agent registry uses `resolve_facility` instead.

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

Live scripts (each may access an external data source and/or OpenAI; run individually):

```bash
python -m app.tests.llm_test                    # OpenAI connection
python -m app.tests.agent_test                  # name -> CCN agent flow
python -m app.tests.financial_trend_test        # multi-year cost reports (CMS only)
python -m app.tests.trend_agent_test            # trend tool through the agent
python -m app.tests.area_comparison_agent_test  # area comparison through the agent
python -m app.tests.access_service_test         # access analysis (CMS + Census + HRSA)
python -m app.tests.census_service_test         # county demographics (Census only)
python -m app.tests.hrsa_service_test           # Primary Care HPSAs (HRSA only)
python -m app.tests.demographics_agent_test     # demographics through the agent
python -m app.tests.healthcare_access_agent_test # access analysis through the agent
```

A successful agent run shows the message flow `HumanMessage -> AIMessage (tool call) -> ToolMessage -> AIMessage`, confirming that the LLM used a tool instead of its own knowledge.

## Data Sources

Current:

- CMS Hospital General Information
- CMS Hospital Provider Cost Report, dataset years 2011 to the latest release
- U.S. Census Bureau ACS 2024 5-Year estimates (county population and age 65+)
- HRSA Primary Care Health Professional Shortage Area (HPSA) designations

HRSA designations may apply to a specific population group or service area; they should not automatically be interpreted as designating the entire county. Census and HRSA results are reported as unavailable if their data sources cannot be queried.

## Next Steps

- Evaluate live model routing, citation faithfulness, usability, latency, and cost
- Improve deployment authentication, rate limiting, concurrency controls, and timeout handling
- Collect feedback from public health and rural-health users
- Expand methodology coverage and retrieval evaluation
- Explore trend visualization, driving-time evidence, and current tribal-facility sources

## Security

Never commit secrets such as API keys. The following remain ignored by Git:

```text
.env
.venv/
__pycache__/
.pytest_cache/
data/*.db
data/*.db-*
```

## Status

Working investigation prototype with structured public-data retrieval, deterministic analytics, bounded chat context, state/county/ZIP access analysis, visible interpretation notices, and a first local lexical RAG implementation. Offline regression checks do not establish live model reliability or upstream availability. This research/learning project does not predict closure or replace clinical or financial decision-making.


## Location-aware search and full investigation

The chat accepts a hospital name with an optional state and county. These
constraints are passed to CMS search; the agent must clarify multiple matches
and must not silently drop location constraints. Search normalizes case and
punctuation, but does not infer old names or provide a tribal clinic directory.
CMS hospital list/search queries use explicit pagination before reporting counts.

Example prompts:

- `Find Mile Bluff Medical Center in Juneau County, Wisconsin.`
- `Investigate Mile Bluff Medical Center in Juneau County, Wisconsin. Include financials, trends, healthcare access, and data gaps.`
- `Now investigate Reedsburg Area Medical Center in Sauk County, WI.`
- `Analyze its financial distress.`

Full investigations use `investigate_hospital` after identifying a CCN, composing
existing latest-year financial, multi-year trend and healthcare-access tools.
One unavailable section does not discard other evidence. No combined risk score
or closure prediction is produced. Trend year bounds do not change the separate
latest financial report; the response must show actual periods.

The demo renders a limited Markdown subset using DOM nodes, including headings,
emphasis, lists, code, safe links and tables. Raw HTML is treated as text. Evidence
cards show tool-supplied sources, financial report periods, and missing-data
status; these cards are not inferred from generated prose. The current hospital
and CCN are shown above the chat. Clear chat resets the bounded local context.
Cards/progress are not included in the next message's conversation history.

Run with `python -m uvicorn app.main:app --reload`, open
`http://127.0.0.1:8000/demo/`, and hard-refresh after frontend changes.
Offline checks for this upgrade:
`python -m unittest app.tests.hospital_upgrade_test app.tests.chat_context_test app.tests.entrypoint_contract_test app.tests.chat_stream_test app.tests.facility_access_service_test app.tests.coordinate_cache_test`.


## Two-hospital comparison

Ask: `Compare Mile Bluff Medical Center in Juneau County, Wisconsin, and
Reedsburg Area Medical Center in Sauk County, Wisconsin. Include financial
condition and healthcare access.` The agent resolves both names then calls
`compare_hospital_investigations`. Two distinct CCNs are required.

Financial reports are checked from newest to oldest across the available CMS
dataset catalog, or for an explicitly requested year. A common dataset year
is shown separately from each hospital's actual fiscal dates. Numerical
differences are returned only when both fiscal periods match; direction is
second hospital minus first, and percentage metrics use percentage points.
If no common year is retrieved, separate latest retrieved reports remain
unaligned context; no financial differences or winner are invented. Failed
newer lookups are disclosed rather than claimed to prove a latest common year.
Trends and healthcare-access results retain their own coverage and data gaps.

The browser keeps only two compact comparison identities, in addition to the
bounded recent conversation. It does not replay complete comparison reports.
The active pair is displayed above the chat. A new single-hospital selection
or Clear chat resets the pair. Singular follow-ups with two active targets
require clarification. Refreshing the page resets local context.

Offline comparison checks: `python -m unittest app.tests.comparison_service_test`.


## Code reading guide

See [Code structure and reading guide](docs/code_structure.md) for module responsibilities, reading order, and offline verification commands.


## Historical tribal facility directory

`search_tribal_facility_directory` searches a curated table extracted from the
CMS **IHS-CMS All Tribal Facilities Listing**, created **2020-01-26**:
https://www.cms.gov/files/document/indian-healt-service-cms-all-final.pdf

The tracked PDF and JSON snapshot live in `data/reference/`. The JSON contains
163 source rows and 171 CCN entries because some rows list multiple CCNs. Its
type-specific row counts match the PDF subtotals. Each row retains its page,
type, city, state, and full CCN list; identifiers stay strings. The JSON records
the original PDF SHA-256. `data/tribal_facilities.db` is an ignored, regenerable
SQLite search index, built automatically from the JSON snapshot on first query.
No PDF extraction library is needed to run the app.

Example: `Which Wisconsin facilities are in the historical CMS/IHS tribal
directory? Include types, listed CCNs, source date and pages.`

This is structured historical lookup, **not vector RAG** and not a live registry.
It has no county, street address, coordinates, financial narratives or service
capacity. A missing match does not prove nonexistence. CCNs for FQHCs and other
non-hospitals are not hospital financial-analysis identifiers; historical hospital
entries must be rechecked in current CMS hospital data before analysis. Historical
lookup clears the old active hospital context to prevent an unrelated follow-up.

Offline tests: `python -m unittest app.tests.tribal_directory_test`.
To reproduce extraction, install `pdfplumber` in a separate development environment
and run `python scripts/extract_tribal_directory.py --pdf data/reference/ihs_cms_tribal_2020.pdf --output data/reference/ihs_cms_tribal_2020.json`.


## State, county and ZIP healthcare-access analysis

`analyze_area_healthcare_access(state, county=None, rural_only=True, year=None, zip_code=None)`
retrieves all current CMS-listed hospital targets in the requested geography.
A county always needs its state. For rural-only requests, eligibility uses the
CMS cost report `Rural Versus Urban` field (`R` / `U`) in one dataset year:
explicit `year`, or the latest known year. Missing reports/unknown codes are
reported separately, never assumed urban; no backward-year substitution is made.
Set `rural_only=False` to analyze all hospitals without cost-report classification.

The deterministic service geocodes each statewide hospital once per request,
then calculates each selected hospital's five nearest same-state alternatives.
Urban and out-of-county hospitals remain candidates. Persistent coordinate
caches are reused. County ACS and HRSA evidence is retrieved once per represented
county. Output includes cohort counts, classification gaps, per-hospital results,
source/period metadata in county evidence, and a nearest-distance summary with
its denominator. No model call per hospital is needed. Progress events remain
visible during classification, geocoding and county retrieval.

This is hospital-centered context, not a population-wide access assessment:
counties without selected hospitals are not assessed; county populations must
not be summed across hospital rows. Cross-state neighbors, travel times, capacity,
service equivalence and patient eligibility are not assessed. Initial statewide
runs may take several minutes, especially with a cold coordinate cache.

Example prompts:
- Analyze healthcare access around rural hospitals across Wyoming.
- Analyze healthcare access around rural hospitals in Fremont County, Wyoming.
- Analyze healthcare access around all hospitals in Juneau County, Wisconsin.
- Analyze rural hospital healthcare access in Wyoming using 2023 classification.

Offline regression tests: `python -m pytest app/tests/area_access_test.py -q`.


ZIP filtering is also supported:
`analyze_area_healthcare_access(state="WI", zip_code="53948", rural_only=False)`.
Use a five-digit string (leading zeros are preserved) and supply state. A county
plus ZIP request applies both filters, never silently broadens either. Stored
CMS ZIP+4 values match their first five digits. The filter selects hospital
mailing locations; it does not calculate a radius, ZIP population coverage or
Census ZCTA estimates. Neighbors still include the entire state. Demographics
and HPSA remain county-level and may cover several represented counties in one
ZIP. No matching hospital does not establish that nearby care is absent.


## Data-quality notices and methodology RAG

Hospital analyses now include dated rural/urban context and visible interpretation
notices. Urban hospitals may still be analyzed; unknown classification is never
assumed urban. Invalid ratio denominators, nonannual/overlapping fiscal periods,
trend reversals and missing access evidence are surfaced independently of model
prose. Affected comparison differences/directional labels are withheld.

`search_methodology_documents` retrieves short passages from reviewed CMS, Census
and HRSA snapshots using local SQLite FTS5/BM25. Citations include source URLs,
retrieval dates and dictionary PDF pages. This is lexical RAG without embedding
API calls; hospital numbers still come from deterministic structured tools.
See [data-quality rules, corpus provenance and test prompts](docs/data_quality_and_rag.md).

The initial corpus covers CMS cost-report provenance, ten CMS dictionary field definitions with PDF page citations, HRSA HPSA types, and Census ACS uncertainty/statistical comparisons. Retrieval dates are not publication dates or proof of current policy. HRSA uses an explicitly recorded reviewed excerpt where direct download returned 403. Unsupported questions must be disclosed rather than answered with invented citations.

Runtime retrieval returns up to three short passages by default and makes no embedding API calls. Normal answer-generation tokens still apply. Hospital identities and numbers continue to come from structured tools. The historical tribal directory is a separate structured lookup, not a tribal financial-report RAG corpus.

Try:

```text
What is the difference between a geographic HPSA and a population HPSA? Cite your sources.
```

```text
How does CMS define Net Patient Revenue? Cite the dictionary page.
```

## Runtime storage and deployment

Geocoding checks the in-memory TTL cache, then `data/hospital_coordinates.db`, then Census Geocoder. Successful coordinates persist across restarts only when the database file is preserved. `data/tribal_facilities.db` and `data/methodology.db` are regenerable local indexes built from tracked snapshots under `data/reference/`. Runtime databases are ignored by Git; normal app execution does not require PDF extraction libraries.

FastAPI serves both frontend and backend. For a Python web service, install with `pip install -r requirements.txt` and start with:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
```

Configure secrets in the hosting platform, use `/health` for health checks, and keep reference snapshots available at runtime. Ephemeral hosting may discard caches on restart/redeploy; preserving them requires a suitable persistent-storage setup. Review access protection and usage controls before broader public use.

## Additional offline regression checks

The default `pytest.ini` collects `test_*.py`; additional offline suites named `*_test.py` require explicit paths:

```bash
python -m pytest app/tests/area_access_test.py app/tests/data_quality_test.py app/tests/methodology_test.py app/tests/comparison_service_test.py app/tests/hospital_upgrade_test.py app/tests/facility_resolution_test.py app/tests/tribal_directory_test.py app/tests/chat_stream_test.py -q
node app/tests/frontend_comparison_test.cjs frontend
```

Live smoke scripts remain separate and may incur model API costs. Do not run every `*_test.py` indiscriminately as an offline suite.
