# Historical financial snapshots in Supabase

## Query path

The backend reads stored CMS financial reports before any request-time CMS data
access. `FINANCIAL_DATA_MODE` controls the policy:

- `database_only`: query completed imports only. No financial catalog/API download
  is performed during analysis. This is the default when `DATABASE_URL` is set.
- `hybrid`: read snapshots first, then use the existing CMS path for uncovered
  hospital/year combinations or a database outage. This fallback is explicit;
  online fallback rows are not silently published as complete state snapshots.
- `live`: keep the original CMS retrieval path without accessing PostgreSQL.

Without a configured database, the default is `live`. PostgreSQL reads reuse a
small pool of at most four TLS connections and use read-only transactions.
Database errors, not-yet-imported data, and absent source records remain distinct.

Financial and reference modes are independent. WI/WY hospital directories, ACS
2024 county data, HRSA and available coordinates are now also available as dated
snapshots via `REFERENCE_DATA_MODE=database_only`. See [reference snapshots](reference_database.md).
Arbitrary user-confirmed addresses may still require an online Census match. Model inference still takes time and consumes tokens;
SQL does not reduce the tokens required to explain the same returned evidence.

## Configuration

Install the updated requirements and set these values privately in `.env`:

```env
DATABASE_URL=your_private_postgresql_connection_string
FINANCIAL_DATA_MODE=database_only
```

The driver requires SSL. Do not commit the real URL or credentials. Production
Render environment variables must be configured separately, followed by a new
deployment. The frontend never receives the database connection string.

## Tables and completeness

The migration creates a private `hospital_data` schema:

- `financial_import_runs`: source dataset ID, CSV URL, catalog revision, download
  checksum/date, counts and running/complete/failed state.
- `financial_report_rows`: all raw source fields and report rows for the selected
  state; multiple fiscal reports per CCN/year are preserved.
- `financial_coverage`: the active complete import for each state/year.

The importer scans the entire national CSV, validates required columns and row
shape, then filters the state. A compact national CCN inventory is retained,
even though out-of-state report payloads are not stored. It prevents a state-only
import from falsely proving that an out-of-state or relocated hospital filed no
report. A national inventory with no CCN establishes absence in that snapshot;
an existing CCN with no stored payload is **uncovered**, not absent.

Report rows, final counts and the active coverage pointer publish in one database
transaction. A failed or interrupted replacement leaves the previous complete
snapshot active. Each attempt has an audit record; retrying skips already-current
years and starts a new attempt for failed/outdated ones. Failed transactions roll
back report writes. Cached CSVs are verified before reuse; downloads finish via a
temporary file so truncated files are never accepted as complete.

Source metadata is exposed as `data_provenance` / `source_provenance`. A raw row
returned by the app can include `_source_provenance` in addition to the unchanged
stored CMS fields. Results must be described as dated snapshots, not a real-time
CMS freshness check. In database-only mode, "latest" means latest completed
imported dataset year, which may lag the newest CMS release.

## Initial import

From the repository root:

```bash
python -m scripts.import_financial_history --state WI --start-year 2020 --end-year 2024 --init-db
```

`--init-db` applies the idempotent SQL migration explicitly. Analysis requests never
create or migrate tables. Source files and integrity sidecars live in ignored
`data/imports/`; source URLs come from the current official CMS catalog rather
than guessed or bundled fallback download addresses.

Initial verified coverage on 2026-10-27:

- 2020: 144 Wisconsin report rows.
- 2021: 149 rows.
- 2022: 150 rows.
- 2023: 153 rows.
- 2024: 157 rows.

Initial WI total: 753 rows. Wyoming subsequently added 147 rows (29/29/29/30/30 across 2020–2024), bringing the combined total to 900 rows. The stored tables and indexes occupied about 2.6 MB after the
first import (not the whole Supabase project's storage). These are report rows,
not a count of unique hospitals. Retained revisions consume additional space;
measure usage before expanding to all states/years on the free plan.

## Check for releases and revisions

Read catalog publication metadata without downloading data CSVs:

```bash
python -m scripts.import_financial_history --state WI --start-year 2020 --check-updates
```

Download/import only new or changed years, including newly published years:

```bash
python -m scripts.import_financial_history --state WI --start-year 2020
```

Omitting `--end-year` includes the latest published year discovered in the current
catalog. Revisions are detected using dataset ID, CSV URL and modified metadata.
If CMS silently changes bytes without changing metadata, use `--refresh` to force
a fresh download and checksum. This is not continuous monitoring: run the command
manually or configure a separate scheduled job after choosing an update frequency.
No recurring automation is created by this implementation.

## Inspect in Supabase

Choose `hospital_data` in the Table Editor schema selector, or run:

```sql
SELECT state, dataset_year, status, state_row_count, source_retrieved_at
FROM hospital_data.financial_import_runs
ORDER BY dataset_year, started_at;
```

```sql
SELECT r.facility_id, i.dataset_year, r.fiscal_year_begin, r.fiscal_year_end
FROM hospital_data.financial_report_rows r
JOIN hospital_data.financial_import_runs i ON i.id = r.run_id
JOIN hospital_data.financial_coverage c ON c.active_run_id = i.id
WHERE r.facility_id = '520109'
ORDER BY i.dataset_year;
```

## Verification

```bash
python -m pytest app/tests/financial_store_test.py -q
```

Offline tests force the original fake-CMS suites to `live` mode, so a developer's
real `.env` database is never queried by the regression suite. Store/import tests
mock all database/network boundaries. Separate live checks verified five-year
Mile Bluff financial/tool output with CMS HTTP calls deliberately prohibited,
and verified that all five current import sources were reported unchanged.

For display tests, ask the agent to analyze Mile Bluff using 2020–2024, and inspect
snapshot provenance. An out-of-scope hospital should prompt an import/update,
not trigger an undisclosed live request or imply no filing.
