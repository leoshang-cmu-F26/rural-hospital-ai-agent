# Independent Test Report

Rural Hospital AI Agent (beta)

Test date: November 16, 2026. Tester: Carrie. Build: `main` at commit `02675b0`.

## 1. Overview

Carrie is a CMU student who is not on our team and had never seen the project before. On November 16 she tested the hosted beta by typing nine scripted questions into the chat page herself. One of us sat with her to write down the answers and response times. We did not help her during the session, and we did not change any code, data or settings while she was testing.

Every question got an answer, and response times ranged from 2 to 17 seconds. We found six problems: one major, two minor and three cosmetic. After the session we fixed the major problem and two of the smaller ones, and added a test for each fix. The remaining three are listed in section 6, either as deferred items or as known limitations.

## 2. How we ran the test

| | |
|---|---|
| Tester | Carrie, a CMU student outside the development team who was unfamiliar with the project |
| Date | November 16, 2026 |
| Where | Hosted beta at https://rural-hospital-ai-agent.onrender.com/demo/, desktop browser |
| Build | `main` at `02675b0` |
| Method | Carrie typed the questions from [TESTER_HANDOUT.md](TESTER_HANDOUT.md) in order and said what she thought of each answer. A developer recorded the output and timing without stepping in. |
| Changes during the test | None |

## 3. What happened

| # | Question | Time | Result | Notes |
|---|---|---|---|---|
| 1 | Find Mile Bluff Medical Center in Wisconsin | 3 s | Pass | Returned the correct CCN (520109), the city (Mauston), the county, and its rural status. |
| 2 | "Is it in financial distress?" | 3 s | Pass | Remembered which hospital we meant. Gave the 2024 figures and five years of operating margins. Four long warning notes appeared first (D-03, D-04). |
| 3 | Chart of finances, 2020 to 2024 | 5 s | Pass | Four charts, each with a data table and fiscal periods. The trend card was wrongly labeled "Partial data" (D-04). |
| 4 | Compare with Reedsburg Area Medical Center | 17 s | Pass | Clear comparison table and a reasonable verdict. Twelve warning notes appeared above the answer (D-03). |
| 5 | Healthcare access in Fremont County, WY | 10 s | Pass | Covered the hospital, the nearest alternatives, census and workforce figures, and shortage areas. It said "five" shortage areas but listed only two (D-05). |
| 6 | What does HPSA mean, and where is that from? | 8 s | Partly | The definition was correct, but the document index was unavailable, so there was no citation (D-01). |
| 7 | "Find Mile Blf Medcal Center" (misspelled) | 5 s | Pass | Asked "Did you mean Mile Bluff Medical Center?" and did not guess on its own. |
| 8 | A hospital that does not exist, in Texas | 7 s | Pass, with issue | Did not make anything up, but the wording sounded like a system outage (D-02). |
| 9 | Clear chat, then "Is it in financial distress?" | 2 s | Pass | Asked which hospital we meant. No old context was carried over. |

The things we were most worried about all worked. Follow-up questions picked up the hospital from the previous turn, the misspelled name led to a sensible suggestion, and Clear chat really did reset the conversation. The comparison was the slowest question at 17 seconds, because it pulls financial, census and HRSA data for two hospitals.

**Carrie's feedback.** She said the responses were very fast, and that the mix of charts and tables suited the questions well. Her main complaint was that some of the extra information on screen got in the way of the main answer. We had noticed the same thing: in question 4, twelve warning notes appeared above the actual answer.

## 4. Problems found

More detail is in [DEFECT_LOG.md](DEFECT_LOG.md).

| ID | Severity | Problem | Status |
|---|---|---|---|
| D-01 | Major | The methodology documents could not be searched in production, so answers had no citations | Code fixed; production index still needs a rebuild |
| D-02 | Minor | The message for an unsupported state reads like an outage | Deferred |
| D-03 | Minor | Too many repeated warning notes push the answer down | Fixed |
| D-04 | Cosmetic | A complete five-year trend was labeled "Partial data" | Fixed |
| D-05 | Cosmetic | The stated count of shortage areas did not match the list | Deferred |
| D-06 | Cosmetic | 18 hospitals have no coordinates and are left out of distance ranking | Known limitation |

## 5. Fixes

**D-01: no citations for methodology questions.** In question 6 the app said its document index was "missing or stale". Cited methodology answers are one of our Must Have features, so we rated this as major.

The cause was line endings. Our Git setup converts files to Windows line endings (CRLF) on checkout, and we built the document index on a Windows machine. The index is keyed by a hash of `corpus.json`. The stored hash was therefore computed from the CRLF version of the file, while the Linux server reads the LF version and computes a different hash. We confirmed this by hashing both versions of the file.

The fix normalizes line endings before hashing. It also adds a `.gitattributes` rule so the file is always checked out with LF (commit `b08a515`, with a new unit test). The production index still has to be rebuilt once with the import script. This does not call the embedding API again, because embeddings are cached by passage text.

**D-03 and D-04: too much on screen.** This is the issue Carrie pointed out. Every indicator whose value went up and down over the five years produced its own warning. Each warning also displayed a line that was really meant as an instruction to the model. We now combine these warnings into one short line per hospital and collapse the panel when there are more than two notes. A complete five-year trend is no longer labeled "Partial data" (commit `a12c2c3`, with a new frontend test).

After the fixes, all 239 offline Python tests and all 3 frontend test suites pass. The fixes are on the `beta-fixes` branch. The hosted demo runs `main`, so it will pick them up once the branch is merged.

## 6. Not fixed yet

- **D-02.** For a state outside our data, the app answers safely and asks for more detail, but the message reads like an outage. We left it because it is a wording problem only. The User Guide already lists which states are covered.
- **D-05.** The model sometimes shortens a list but keeps the original count. We plan to add a prompt rule for this.
- **D-06.** The Census geocoder cannot place some hospital addresses. The app already says this in its answers, and we plan to fill in the missing coordinates later.
- **General limits of the beta.** Stored financial history covers only California, Wisconsin and Wyoming for 2020 to 2024. The free hosting plan takes about 50 seconds to wake up after a period of inactivity. There is no login or rate limiting yet.

## 7. Conclusion

Someone outside the team was able to get through the whole core workflow on the live site without help, and the answers she got were sourced and easy to read. The biggest problem, the missing citations, came from how we deployed the index rather than from the retrieval logic, and the code fix is in place. The next steps are to merge `beta-fixes`, rebuild the production index, and run question 6 again to confirm the fix.
