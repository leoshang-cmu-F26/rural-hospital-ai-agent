# Code structure and reading guide

This project separates model orchestration from external data retrieval and
deterministic calculations. Comments describe functional stages and data limits.
Production Python uses explicit loops and `if/else` instead of comprehensions
and conditional expressions. Dictionary copies/merges use explicit item loops; lists use `append()`. Standard
model constructors and concurrency APIs remain where they express the operation
clearly. Test fixtures may retain compact sample-data setup.

## Recommended reading order

1. `app/main.py`: startup, background catalog warmup, API routes, demo assets.
2. `app/api/routes.py`: input validation, HTTP errors and streaming responses.
3. `app/agents/agent.py`: bounded conversation request/response schemas.
4. `app/agents/hospital_agent.py`: model setup, routing instructions, invocation.
5. `app/tools/agent_tools.py`: the tools exposed to the model and compact outputs.
6. `app/services/`: source adapters, cached coordinates, orchestration and context.
7. `app/tools/financial_tools.py` and `trend_tools.py`: deterministic calculations.
8. `frontend/app.js` and `markdown.js`: streamed chat lifecycle and safe rendering.

## Data retrieval and caches

- `cms_service.py`: hospital identity, full result pagination, state/county search.
- `cost_report_service.py`: catalog discovery, report selection, parsing and history.
- `census_service.py`: county population/age estimates and hospital county mapping.
- `hrsa_service.py`: county-associated primary-care shortage designations.
- `geocoding_service.py`: imported coordinate snapshots when configured; otherwise
  in-memory TTL cache, SQLite, then Census Geocoder.
- `coordinate_cache.py`: create/read/update the runtime coordinate database.
- `state_utils.py`, `constants.py`, `models/`: shared names, codes and typed records.

Missing data remains unavailable, not zero. A missing matching report is distinct
from a failed dataset request. County evidence is not a hospital service-area or
tribal-population measure.

## Database snapshots and independent import jobs

- `financial_store.py`: connection policy/pool, read-only report queries, audited
  imports, and atomic publication of complete state/year snapshots.
- `reference_store.py`: cached state snapshots for directories, counties, HPSA and
  coordinates, with explicit coverage and source dates.
- `financial_import_service.py`: official catalog discovery, checked downloads,
  source-row validation, revision detection and per-year import jobs.
- `reference_import_service.py`: complete directory/Census/HPSA retrieval and
  coordinate imports with explicit unavailable matches.
- `scripts/import_financial_history.py` and `scripts/import_reference_data.py`:
  command-line options and safe exit statuses; neither runs as part of chat.
- `supabase/migrations/`: private tables and scope constraints. Code cleanup does
  not rerun migrations, refresh sources or change existing database contents.

See [financial snapshots](financial_database.md) and
[reference snapshots](reference_database.md) for configuration and import commands.

## Data quality and document retrieval

- `data_quality_service.py`: metric interpretation guards, dated rural notices and
  model-independent frontend warnings.
- `methodology_service.py`: checksum verification, exact document chunks and local
  SQLite FTS5/BM25 retrieval.
- `scripts/build_methodology_corpus.py`, `extract_cost_dictionary.py` and
  `extract_tribal_directory.py`: reviewed reference extraction and refresh helpers.

## Analysis orchestration

- `access_service.py`: administrative alternatives, demographics, HPSA and distance.
- `distance_service.py`: same-state candidate ranking in Haversine straight-line miles.
- `facility_access_service.py`: confirmed-address access analysis without a CCN.
- `investigation_service.py`: latest financials, trends, access and independent gaps.
- `comparison_service.py`: two identities, common report year, fiscal alignment,
  second-minus-first differences, trends and access for both hospitals.

Dataset year and fiscal dates are separate. Comparisons do not calculate a risk
score or identify an overall winner. Individual section failures preserve the
other evidence where supported.

## Conversation and public progress

- `chat_context.py`: bounded recent messages and compact single/pair identities.
- `agent_progress.py`: request-local tool callbacks; no model reasoning is exposed.
- `chat_stream.py`: one worker/queue per request, heartbeat frames and final/error events.
- `evidence_summary.py`: sources, periods and coverage from structured tool outputs.

Disconnect stops event delivery, but does not cancel an external request already
running. Browser state remains local and resets on refresh or Clear chat; this is
not server-side conversation persistence or an explicit topic-state graph.

## Frontend responsibilities

- `index.html`: accessible page controls, examples and initial identity banner.
- `app.js`: submit, decode ordered events, commit successful context, progress,
  evidence cards and clear-chat behavior.
- `markdown.js`: supported Markdown blocks and inline formatting using DOM nodes;
  raw model HTML is never interpolated.
- `style.css`: layout, chat, progress, Markdown, coverage cards and narrow screens.

## Verification

Offline regression checks:

```powershell
python -m pytest app/tests/comparison_service_test.py app/tests/hospital_upgrade_test.py app/tests/test_financial_tools.py app/tests/test_integration.py app/tests/entrypoint_contract_test.py app/tests/chat_context_test.py app/tests/chat_stream_test.py app/tests/facility_access_service_test.py app/tests/coordinate_cache_test.py -q
node app/tests/frontend_comparison_test.cjs frontend
```

Tests ending in `_agent_test.py` and several standalone service scripts use live
external services; do not include them in an offline run accidentally.
