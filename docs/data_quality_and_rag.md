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

## Initial retrieval-augmented generation

1. Reviewed government source snapshots are tracked in
   `data/reference/methodology/corpus.json` with title, URL, retrieval date, content
   checksum, extraction method, and PDF page where applicable.
2. The runtime creates an ignored `data/methodology.db` SQLite FTS5 index. Corpus
   checksums drive atomic rebuilds; runtime retrieval does not download pages.
3. Questions retrieve up to three 900-character passages by default (maximum four),
   using lexical BM25 and a small bilingual query-expansion vocabulary.
4. The agent uses `search_methodology_documents` for explanatory questions and
   cites supporting sources. Structured tools remain authoritative for hospital
   identities and numeric observations. Matching text is not proof of entailment;
   the agent is instructed to disclose unsupported questions and avoid invented
   citations. A failed index/source is distinguished from no lexical match.

This is lexical RAG, not vector/embedding retrieval. It adds no embedding API or
external vector-database cost; normal answer-generation tokens still apply.
Retrieval is tested deterministically; generation faithfulness still needs live
model evaluation. Chinese expansion covers selected terms, not arbitrary semantic
translation. Document content is evidence and must never override instructions.

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
- `python -m pytest app/tests/data_quality_test.py app/tests/methodology_test.py -q`.
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
