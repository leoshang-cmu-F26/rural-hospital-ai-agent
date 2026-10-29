# Data quality, rural reminders and methodology RAG

## Interpretation rules

Numeric source values remain traceable. `blocked_metrics` means that a computed
ratio must not be ranked, described as improvement, or used for a direct financial
difference. Missing/non-finite/nonpositive denominators, invalid utilization and
invalid source values receive deterministic warnings. Non-finite computed values
are returned as null. Missing fields remain separate from present zero values.

Fiscal dates are reviewed as actual dates, not dataset-year labels. Periods outside
330–400 inclusive days trigger a project-defined annual-period review (this is a
heuristic, not a CMS rule). Between trend records, overlap, missing/invalid dates
or period lengths differing by more than 31 days withhold simple direction and
change labels. Material step reversals use `mixed`; blocked ratios use
`requires_review`. Step thresholds are the existing project trend thresholds.
These rules are application interpretations, not official risk ratings.

Two-hospital differences still require the same dataset year and identical fiscal
periods. Metrics flagged as blocked, or reports flagged for fiscal review, do not
produce differences. Other usable metrics/sections remain available.

## Rural classification

Resolved hospital tool results and access-only hospital requests attach the dated
CMS cost-report classification. Financial tools use the report already retrieved;
identity/access tools reuse the existing cost-report lookup and its caches.
`U` produces an urban/non-rural notice; `R` is rural; unavailable/unrecognized is
unknown. An urban classification is not a reason to refuse analysis. The notice
includes the dataset year and fiscal dates and does not assert current geographic
rural status under all definitions. Historical clinic IDs are never promoted to
hospital financial identifiers. Ambiguous names are clarified before this lookup.

## Visible notices

`ToolProgressHandler` emits `warnings` frames independently of answer generation.
The browser deduplicates notices per hospital/code/metric/year and displays them
above the answer, outside collapsible source details. Notices identify the issue
and next verification step. Census/HRSA/distance failures, coordinate exclusions,
ACS uncertainty without MOEs and financial alignment are explicitly surfaced.
Warnings are text DOM nodes; source/model HTML is never executed.

## Vector retrieval-augmented generation

The default backend is OpenAI embeddings plus Supabase PostgreSQL `pgvector`.
The former SQLite FTS5/BM25 backend is retained only as an explicitly selected
legacy option (`METHODOLOGY_RETRIEVAL_MODE=lexical`). There is no silent fallback.

1. Reviewed official snapshots remain versioned in
   `data/reference/methodology/corpus.json`. Source content hashes, URLs, retrieval
   dates, exact passage offsets and PDF pages are preserved.
2. `python -m scripts.import_methodology_vectors --init-db` enables pgvector and
   creates private `hospital_data.methodology_corpora`, `methodology_passages`,
   and `methodology_active` tables. It splits text into 900-character passages
   with 100-character overlap, embedding title + topic + exact excerpt.
3. Embeddings default to `text-embedding-3-small`, fixed at 1536 dimensions.
   `text-embedding-3-large` is also supported at 1536 dimensions. Changing models
   requires an explicit import; document and query models must match.
4. Input hash/model matching reuses stored document vectors. A corpus fingerprint
   includes source bytes, model, dimensions and chunk/input recipe. Unchanged
   imports skip embedding calls. Complete versions publish in one transaction;
   failed embedding or database work cannot replace the active corpus.
5. At runtime `search_methodology_documents` delegates to vector retrieval. It
   verifies local source checksums and the active fingerprint before embedding
   the question, then searches that exact corpus with pgvector cosine distance.
   This small corpus uses exact vector nearest-neighbor search, not an HNSW or
   IVFFlat approximate index. PostgreSQL scans the version's small passage set.
6. By default up to three passages return (maximum four), after a configurable
   minimum cosine similarity of 0.30. The threshold is a heuristic, not calibrated
   factual confidence. Stored excerpts/metadata must still match reviewed source
   spans; provenance mismatches fail closed.
7. The Agent receives passage text, source URLs/pages/dates and similarity. It
   must check that passages support its claims and cite them. An empty result is
   distinct from an unavailable API/database or stale corpus. Numeric hospital
   facts and calculations still come from structured tools.

Repeated query embeddings are cached in bounded process memory for one hour
(maximum 256 queries). Each uncached methodology question calls the embedding API;
normal answer-generation tokens also apply. This change targets semantic matching,
including cross-language wording, and does not guarantee lower latency. Only
retrieval questions/public document chunks are embedded; hospital tables are not
bulk-converted into vectors. Query requests never create tables or re-embed docs.

Configuration:

```dotenv
METHODOLOGY_RETRIEVAL_MODE=vector
METHODOLOGY_EMBEDDING_MODEL=text-embedding-3-small
METHODOLOGY_MIN_SIMILARITY=0.30
```

Existing private `DATABASE_URL` and `OPENAI_API_KEY` are required. The local
configuration and shared Supabase corpus have been migrated. Render still needs
updated code/environment settings; it does not run the import on startup. A newer
corpus activated in the shared database will reject stale deployed corpus bytes
rather than silently serving a mismatched version. Old corpus versions are kept;
no automatic history deletion or background refresh has been configured.

### Sources and scope

- CMS Cost Reports: provenance and disclaimer.
- CMS Hospital Provider Cost Report Data Dictionary (10 reviewed table definitions
  with page references): fiscal dates, rural/urban source worksheet, available bed
  days, assets/liabilities, revenue, service income, net income and cost-to-charge.
- HRSA What Is Shortage Designation?: geographic, population and facility HPSAs.
- Census ACS Statistical Testing Tool: uncertainty/MOE and statistical comparisons.

The dictionary describes underlying worksheet numeric rural codes; the structured
API implementation currently recognizes `R`/`U`. Do not replace the mapping based
solely on a prose retrieval result. Publication dates are unknown unless provided;
retrieval dates must never be presented as publication dates or fresh policy checks.
HRSA direct HTTP download returned 403 during ingestion. Its reviewed excerpt was
checked against the official page through web retrieval; this fallback and its
original review date are recorded explicitly. This small corpus is not a tribal
financial-report library and cannot explain hospital-specific causes of distress.

### Refresh and verification

- `python scripts/build_methodology_corpus.py` refreshes allowlisted HTML sources
  and merges the versioned dictionary excerpts; layout/content checks fail closed.
- Dictionary refresh: replace the official PDF, run
  `python scripts/extract_cost_dictionary.py` with developer-only `pdfplumber`,
  visually check extracted rows/pages, then rebuild the corpus. Runtime does not
  require PDF parsing packages.
- HRSA fallback refresh: recheck the official page and update the reviewed excerpt,
  review date and checksum; do not silently stamp an old excerpt with today's date.
- After refreshing/reviewing the source corpus, run
  `python -m scripts.import_methodology_vectors` to activate its vector version.
- `python -m pytest app/tests/data_quality_test.py app/tests/methodology_test.py app/tests/methodology_vectors_test.py -q`.
  Legacy lexical tests explicitly select lexical mode; vector tests mock the
  database/embedding API and verify bounds, caching, provenance, mismatch failures
  and no silent fallback.
- `node app/tests/frontend_comparison_test.cjs frontend` verifies visible notices
  along with safe Markdown and conversation switching.

### Manual prompts after restarting/redeploying

- Investigate [known urban hospital name] in [county, state].
  Expect a dated non-rural notice and continued analysis; no assumption from name.
- What is the difference between a population HPSA and a geographic HPSA?
  Expect a supporting HRSA citation.
- How is Net Patient Revenue defined in the CMS cost report dictionary?
  Expect the dictionary citation with page 9.
- Can I say one county has a statistically higher elderly population percentage?
  Expect discussion of estimates/MOEs and no significance claim without testing.
- Explain the role of extraterrestrial subsidies in hospital distress.
  Expect insufficient evidence in this corpus, not an invented source.

### Migration verification (2026-10-28)

The private Supabase project enabled pgvector 0.8.2 and imported all 16 passages
using `text-embedding-3-small` at 1536 dimensions. Direct live retrieval verified
HRSA HPSA, Chinese ACS uncertainty, CMS Net Patient Revenue definition and a
no-match unrelated question. Re-import returned `unchanged` without new document
embedding calls. These checks establish retrieval behavior for those examples,
not broad retrieval accuracy or generation faithfulness.

Official implementation references:

- [OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings)
- [Supabase pgvector](https://supabase.com/docs/guides/database/extensions/pgvector)
