# Beta Status: Must Have Functionality

Each Must Have requirement is listed with the component that delivers it and the automated evidence for it. Run the offline suite with `python -m pytest -q`. The full command list is in [README › Testing](../README.md#testing).

| # | Must Have | Component | Interface | Evidence | Status |
|---|---|---|---|---|---|
| M1 | Find a hospital by name, location or CCN | `facility_resolution_service`, `cms_service` | Chat, `GET /hospitals` | `facility_resolution_test.py`, `test_integration.py` | ✅ |
| M2 | Single-year financial indicators with missing-data detection | `financial_tools`, `cost_report_service` | Chat, `GET /hospitals/{ccn}/financials` | `test_financial_tools.py` | ✅ |
| M3 | Multi-year trend and distress signals | `trend_tools` | Chat, trend endpoint | `test_financial_tools.py`, `financial_store_test.py` | ✅ |
| M4 | Hospital comparison with fiscal-period alignment | `comparison_service` | Chat | `comparison_service_test.py`, `frontend_comparison_test.cjs` | ✅ |
| M5 | State, county and ZIP healthcare-access analysis (CMS + Census + HRSA) | `access_service`, `area_access_service` | Chat | `area_access_test.py` | ✅ |
| M6 | Visible data-quality notices and sources | `data_quality_service`, `evidence_summary` | Chat cards | `data_quality_test.py`, `chat_stream_test.py` | ✅ |
| M7 | Methodology Q&A grounded in reviewed documents (RAG) | `methodology_vectors` (pgvector) | Chat | `methodology_vectors_test.py`, `methodology_test.py` | ✅ |
| M8 | Financial charts | `financial_charts`, `frontend/financial-charts.js` | Chat | `financial_charts_test.py`, `frontend_charts_test.cjs` | ✅ |
| M9 | LLM agent with tool calling and bounded context | `hospital_agent`, `chat_context` | `POST /agent/chat[/stream]` | `entrypoint_contract_test.py`, `chat_context_test.py` | ✅ |
| M10 | Error handling: invalid input → 400, unknown entity → 404, upstream failure → 502/503, UI error message | `api/routes.py`, `frontend/app.js` | All | `test_integration.py` (failure scenarios) | ✅ |
| M11 | Deployed, health-checked environment | `render.yaml`, `Dockerfile` | `/health`, `/demo/` | [DEPLOYMENT.md](DEPLOYMENT.md) | ✅ |

## Known limitations (beta)

- Stored financial history covers CA, WI and WY for 2020–2024. Other states fall back to live CMS retrieval or disclose missing coverage.
- On the free hosting tier the service sleeps when idle, so the first request after a wake-up takes about 50 s.
- There is no authentication or rate limiting yet. The beta is intended for invited testers only.
- Answers are evidence summaries, not closure predictions or financial advice.

## Independent testing

See [`testing/`](../testing/): test script, [defect log](../testing/DEFECT_LOG.md) and [independent test report](../testing/INDEPENDENT_TEST_REPORT.md). M7 was degraded in production at test time (D-01) and is fixed pending a one-time vector re-import.
