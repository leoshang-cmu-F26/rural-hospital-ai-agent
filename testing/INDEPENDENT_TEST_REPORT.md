# Independent Test Report: Rural Hospital AI Agent Beta

## 1. Summary

A tester outside the development team ran the core chat workflow on the hosted beta, using a 9-step script: lookup → financial distress → trend chart → comparison → county access → methodology → misspelling → unknown hospital → context reset. No code or configuration was changed during the session.

All scripted steps returned an answer. Response times were **2–17 s**. Conversation context, typo handling and context reset worked as intended. The session surfaced **1 major (P1), 2 minor (P2) and 3 cosmetic (P3)** defects. The P1, one P2 and one P3 were fixed after the session, each with a regression test. The other P2 (a wording issue with no data-integrity impact) and two P3s are deferred or documented as known limitations.

## 2. Test setup

| Item | Value |
|---|---|
| Tester | Carrie, CMU student outside the development team, unfamiliar with the project |
| Date | November 16, 2026 |
| Environment | Hosted beta, https://rural-hospital-ai-agent.onrender.com/demo/, desktop browser |
| Build under test | `main` @ `02675b0` (fixes delivered afterwards on branch `beta-fixes`) |
| Method | Tester typed the scripted questions ([TESTER_HANDOUT.md](TESTER_HANDOUT.md)); the developer recorded outputs and response times without intervening |
| Code freeze | No code, data or configuration changes during the session |

## 3. Results

| # | Step | Time | Outcome | Observation |
|---|---|---|---|---|
| 1 | Find Mile Bluff Medical Center (WI) | 3 s | ✅ Pass | Correct CCN 520109, Mauston, Juneau County, rural 2024. Snapshot date disclosed. |
| 2 | "Is it in financial distress?" (follow-up) | 3 s | ✅ Pass · D-03, D-04 | Context kept without repeating the name. 2024 indicators, five-year operating-margin series, and a balanced conclusion ("stress, not proof of closure risk"). Four verbose notices appeared before the answer. |
| 3 | Trend chart 2020–2024 | 5 s | ✅ Pass · D-03, D-04 | Four metric charts with a data table and fiscal periods. Trend card mislabeled "Partial data". |
| 4 | Compare with Reedsburg | 17 s | ✅ Pass · D-03, D-06 | Aligned fiscal periods, difference table, a clear verdict (Reedsburg comparatively stronger, both loss-making) and access context. 12 notices before the answer. |
| 5 | Fremont County, WY access | 10 s | ✅ Pass · D-05 | One rural hospital (SageWest), nearest alternative 43.7 mi, ACS figures with MOEs, AHRF workforce, HPSA evidence. Said "five" HPSAs but listed two. |
| 6 | HPSA definition and source | 8 s | ⚠️ Degraded · **D-01** | The definition was correct, but the RAG index was reported "missing or stale", so there was no verified citation. The system disclosed this honestly instead of inventing a source. |
| 7 | Misspelled "Mile Blf Medcal Center" | 5 s | ✅ Pass | Suggested the correct hospital and CCN, and did not auto-assume it. |
| 8 | Springfield General Hospital, TX | 7 s | ⚠️ Pass with issue · D-02 | Did not invent data. The message ("directory lookup was unavailable") read like an outage, not "Texas is not covered". |
| 9 | Clear chat → follow-up | 2 s | ✅ Pass | Correctly asked which hospital, so no stale context leaked. |

**Completion:** 9 of 9 steps answered without developer help (7 pass, 2 pass with an issue or degraded). Median response time was 5 s.

**Tester feedback (Carrie):** Responses were very fast, and the answers were well illustrated with charts and tables, which suited the questions. However, some unnecessary information was displayed, and it obscured the main message.

The second point matches what we observed in Q2–Q4, where up to 12 repeated notices appeared before the answer. It is addressed by D-03 and D-04.

## 4. Defects

Full details are in [DEFECT_LOG.md](DEFECT_LOG.md).

| ID | Sev. | Summary | Status |
|---|---|---|---|
| D-01 | P1 | Methodology RAG unavailable in production (CRLF/LF fingerprint mismatch) | Fixed on `beta-fixes` ([`b08a515`](https://github.com/leoshang-cmu-F26/rural-hospital-ai-agent/commit/b08a515)); production re-import pending |
| D-02 | P2 | Uncovered state reported as "lookup unavailable" | Deferred |
| D-03 | P2 | Repetitive, model-facing notice panel | Fixed on `beta-fixes` ([`a12c2c3`](https://github.com/leoshang-cmu-F26/rural-hospital-ai-agent/commit/a12c2c3)) |
| D-04 | P3 | Complete trend labeled "Partial data" | Fixed on `beta-fixes` ([`a12c2c3`](https://github.com/leoshang-cmu-F26/rural-hospital-ai-agent/commit/a12c2c3)) |
| D-05 | P3 | HPSA count inconsistent with list | Deferred |
| D-06 | P3 | 18 hospitals lack coordinates for distance ranking | Known limitation |

## 5. Resolution of the highest-priority defects

**D-01 (P1): Methodology RAG unavailable.**
*Root cause:* The repository uses `core.autocrlf=true`. The vector import ran on Windows, where `corpus.json` is checked out with CRLF line endings, and its SHA-256 was stored as the corpus fingerprint. The Render host checks out LF, computes a different hash, and therefore treats the index as stale. We confirmed this locally: the working-copy hash is `be6e1b67…` and the git blob hash is `e948672c…`.
*Fix:* `methodology_vectors.corpus_digest()` normalizes CRLF to LF before hashing, and `.gitattributes` pins reference JSON to LF. Embeddings are cached by passage text, so re-running `python -m scripts.import_methodology_vectors` publishes the corrected fingerprint without new embedding calls.
*Commit:* [`b08a515`](https://github.com/leoshang-cmu-F26/rural-hospital-ai-agent/commit/b08a515).
*Verification:* regression test `test_fingerprint_ignores_checkout_line_endings` passes. The production vector re-import is a scheduled operational step and is pending; Q6 will be re-run on the hosted beta afterwards.

**D-03 / D-04 (P2/P3): Notice overload.** Per-metric trend-reversal notices are merged into one plain-language line per hospital ("Values rose and fell over the years for operating margin, occupancy rate…"). Panels with more than two notes collapse behind a summary line, and model-facing instructions are no longer shown. Source cards no longer count these notes as missing data. Commit: [`a12c2c3`](https://github.com/leoshang-cmu-F26/rural-hospital-ai-agent/commit/a12c2c3); regression test `frontend_warnings_test.cjs`.

**Delivery:** All fixes are on branch [`beta-fixes`](https://github.com/leoshang-cmu-F26/rural-hospital-ai-agent/tree/beta-fixes). The hosted demo tracks `main` and is unchanged until the branch is merged.

**Regression status after fixes:** 239 offline Python tests and 3 frontend suites pass. New tests: 1 Python, 1 frontend.

## 6. Deferred items and known limitations

- **D-02:** Requests for states outside the imported data are answered safely (no invented data, and the app asks for clarification), but the wording sounds like an outage. Deferred as a wording issue. Coverage is stated in the User Guide; an explicit "not covered yet" reason is planned.
- **D-05:** LLM list summarization can drop items. Planned fix: a prompt rule plus a check that the number of listed items matches the stated count.
- **D-06:** Some CMS addresses fail Census geocoding. This is disclosed in every answer; coordinates will be backfilled.
- Imported coverage is CA, WI and WY for 2020–2024. Free hosting adds about 50 s on a cold start. There is no authentication or rate limiting yet (invited beta).

## 7. Conclusion

A user outside the team completed the full core workflow on the hosted beta without assistance, and every answer came with sources and coverage disclosures. The one Must Have failure found (methodology citations) was traced to a deployment-environment root cause and fixed, along with the most visible usability issues. Next steps: merge `beta-fixes` to deploy D-03/D-04, run the vector re-import to restore cited methodology answers (D-01), then re-run Q6 to confirm.
