# Financial charts in chat

The `/demo/` frontend renders financial charts from the `create_financial_chart`
tool. It uses native responsive SVG, with no plotting CDN, external image service
or additional runtime package. The model resolves hospital identities and chooses
the tool; deterministic financial services provide every plotted number.

## Examples

```text
Show a financial trend line chart for Mile Bluff Medical Center in Mauston,
Wisconsin, from 2020 to 2024.
```

```text
Show financial comparison bar charts for Mile Bluff Medical Center in Mauston,
Wisconsin, and Reedsburg Area Medical Center in Reedsburg, Wisconsin. Use the
latest retrieved common CMS report year.
```

Line charts support one to five hospitals and at most ten dataset years (default
five). Bar charts support two to five hospitals and one common dataset year,
specified or searched newest-first among available years. Resolve names and
locations before passing CCNs. This is a financial-only request: no population,
HPSA, coordinate or healthcare-access lookup is needed.

The metric selector includes operating margin, liabilities/assets, bed occupancy
and cost/charge ratio. The first three use percent; cost/charge is a plain ratio.
Each hospital has a distinct color, CCN legend and point tooltip. The data table
retains exact values, dataset years, actual fiscal dates and available source
retrieval timestamps. Missing or blocked values are never converted to zero.

## Interpretation safeguards

- Missing years break lines. Invalid/non-finite metrics are not plotted.
- Trend fiscal-period review shows isolated points without connecting lines.
- Different, missing or nonannual fiscal periods withhold comparison bars;
  source values remain accessible in a table. No mixed-year comparison is made.
- The shared fiscal-date parser accepts CMS CSV `MM/DD/YYYY` and ISO dates.
  This also fixes erroneous review warnings on imported annual reports.
- Bars include a zero baseline, including negative operating margins.
- Charts describe historical reports, not risk scores or predictions of closure.

## Delivery and context

Tool completion emits a request-local `charts` event through the existing NDJSON
stream. The browser collects these payloads and attaches the charts to the final
reply, with metric switching and source notes. Text labels use DOM text nodes;
neither model HTML nor executable chart specifications are evaluated.

Charts are display-only: full points are not added to conversation history.
One hospital updates the active identity; two hospitals update the existing pair
context. Three-to-five targets clear the single/pair banner to avoid incorrectly
selecting the last hospital. Those larger groups remain in bounded recent
dialogue, not a new persistent multi-hospital memory. Restate names for long-gap
follow-ups. The nonstreaming text endpoint remains text-only.

## Verification

```text
python -m pytest app/tests/financial_charts_test.py -q
node app/tests/frontend_charts_test.cjs
node app/tests/frontend_comparison_test.cjs frontend
```

Tests cover period alignment, equivalent CSV/ISO dates, missing/blocked metrics,
common-year selection, negative and zero bars, safe labels, stream delivery and
metric switching. Direct Supabase checks run with external HTTP blocked; live
LLM tool selection requires manual chat testing. No new data import is needed.
