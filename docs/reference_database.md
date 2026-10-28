# Wisconsin and Wyoming reference snapshots

## Imported scope

The database now contains current source snapshots for both WI and WY, alongside
their 2020–2024 financial cost reports. These dates are different concepts:

- Financial reports: dataset years 2020–2024, 753 WI rows and 147 WY rows.
- Hospital directory: 140 WI hospitals and 31 WY hospitals at import time.
- Census: ACS **2024 5-Year** county estimates, 72 WI counties and 23 WY counties.
- HRSA: 481 WI and 32 WY primary-care source features, as of the import snapshot.
  These are source rows, not a count of unique active county-wide designations.
- Coordinates: 122/140 WI hospitals and 25/31 WY hospitals have verified coordinates.
  The other 24 hospitals remain explicitly unavailable; no locations were guessed.

Coordinate matches reused the existing SQLite cache only when the address/city/
state/ZIP still matched the hospital record. Cached points retain their SQLite
observation timestamp; new matches retain the geocoder timestamp. Importing an
old coordinate does not make it a newly geocoded location.

## Tables

All tables are in the private `hospital_data` schema:

- `reference_import_runs`: kind/state, source URL/year, retrieval date, counts,
  complete/partial status, content checksum and scope metadata.
- `reference_records`: raw/normalized records indexed by CCN, county or HRSA object ID.
- `reference_coverage`: the active snapshot per kind and state.

Reference and financial coverage have composite foreign keys enforcing the correct
kind/state/year scope. A legacy coverage mismatch discovered during cross-state
validation was repaired from the original complete reports; source rows were not
lost. The database rejects an attempt to point WI 2020 at a WY 2024 run.

## Runtime policy

```env
DATABASE_URL=your_private_connection_string
FINANCIAL_DATA_MODE=database_only
REFERENCE_DATA_MODE=database_only
```

`REFERENCE_DATA_MODE` is opt-in and defaults to `live` for compatibility. Other
supported values are `hybrid` (explicit fallback for uncovered data) and
`database_only` (no silent external retry). Financial mode has its own setting.
Local configuration was updated; Render must be configured/deployed separately.

In reference database-only mode:

1. State directories and hospital CCNs come from PostgreSQL.
2. Hospital name lookup requires a state, rather than claiming that WI/WY is a
   complete national registry. Unimported CCNs/states are unknown, not nonexistent.
3. County Census results do not need a request-time Census API key.
4. HPSA summaries reuse the existing rules over complete stored state features.
   Designated/withdrawn status is a snapshot observation, not guaranteed live status.
5. Coordinate lookups reuse stored state snapshots. Unmatched or changed-address
   records stay unavailable, including when old SQLite entries exist.

State snapshots are cached in memory for five minutes and read through the shared
small PostgreSQL TLS connection pool. Results preserve source dates in provenance.
The app still performs model inference. Arbitrary user-confirmed address analysis
may need an online Census address/county match: it is not a preloaded facility record.
The historical tribal directory and methodology corpus remain their existing local
reference indexes; this migration does not turn them into tribal financial reports.

## Refresh command

```bash
python -m scripts.import_reference_data --states WI WY --init-db
```

The directory import verifies complete CMS pagination. Census makes one all-county
query per state and validates the 2024 county count. HRSA first enumerates all object
IDs, retrieves batches, and rejects missing IDs/transfer-limit truncation. Coordinates
publish explicit unavailable entries with partial coverage. Components publish
atomically; a source failure leaves the previous active component intact and is
reported as a failed CLI result. Reference jobs refresh dated snapshots; they do
not silently run as part of a chat request. No recurring schedule has been created.

To refresh only directory/Census/HPSA while keeping existing coordinates:

```bash
python -m scripts.import_reference_data --states WI WY --skip-coordinates
```

Financial release/revision checks are separate:

```bash
python -m scripts.import_financial_history --state WY --start-year 2020 --check-updates
python -m scripts.import_financial_history --state WY --start-year 2020
```

## Inspect in Supabase

Select `hospital_data` in the Table Editor, or run:

```sql
SELECT i.kind, i.state, i.status, i.row_count, i.available_count,
       i.source_year, i.retrieved_at
FROM hospital_data.reference_import_runs i
JOIN hospital_data.reference_coverage c ON c.active_run_id = i.id
ORDER BY i.state, i.kind;
```

```sql
SELECT r.record_key AS facility_id, r.payload
FROM hospital_data.reference_records r
JOIN hospital_data.reference_coverage c ON c.active_run_id = r.run_id
WHERE c.kind = 'hospital_coordinates' AND c.state = 'WY'
  AND r.payload->>'available' = 'false';
```

## Capacity assessment before nationwide import

After the two-state import, all application tables/indexes occupy about **4.2 MB**
(excluding the rest of the Supabase project's baseline storage). Active revisions
and failed/import-audit history can grow this footprint.

The five national financial CSVs contain 30,405 source rows in total. Our 900
stored financial rows use 2,183,662 compressed JSONB bytes. Extrapolating only this
payload to national five-year coverage gives about **73.8 MB**; it is not a total
database-size prediction. The current national primary-care HRSA layer reports
17,413 features. Its shape varies across states; the 513 imported features occupy
326,353 JSONB bytes, suggesting roughly 11 MB for that payload if the sample holds.

Indexes, tuple overhead, source inventories, other reference tables, retained
revisions and platform storage must also be budgeted. A first national 2020–2024
financial snapshot looks plausible within a 500 MB free database, but all years
and unlimited revisions are not guaranteed to fit. The next expansion should be
batched and measured, starting with financial reports, before importing every
historical year or all reference revisions. No national expansion was performed.

## Tests

`python -m pytest app/tests/reference_store_test.py app/tests/financial_store_test.py -q`
uses mocked database/network boundaries. Separate live checks disabled external
HTTP and successfully ran Mile Bluff's full investigation (including 2020–2024
financials) and Wyoming's statewide rural access analysis. Five-year financial
coverage for a Wyoming hospital was also verified. Live model text generation
was not part of these checks.
