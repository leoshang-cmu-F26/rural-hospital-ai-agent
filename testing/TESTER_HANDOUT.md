# Beta Test Script: Rural Hospital AI Agent

**App:** https://rural-hospital-ai-agent.onrender.com/demo/ (if the page is slow, wait about a minute and refresh)

You (the tester) type each question below into the chat box, in order. The developer only records results and does not help or change anything. After each answer, say in one sentence what you think of it.

| # | Type this | What it checks |
|---|---|---|
| 1 | `Find Mile Bluff Medical Center in Wisconsin.` | Hospital lookup |
| 2 | `Is it in financial distress?` (do not repeat the name) | Financial analysis and conversation context |
| 3 | `Show how its finances changed from 2020 to 2024 as a chart.` | Multi-year trend and chart |
| 4 | `Compare it with Reedsburg Area Medical Center in Wisconsin. Which is financially stronger?` | Two-hospital comparison |
| 5 | `Analyze healthcare access in Fremont County, Wyoming.` | County access (CMS + Census + HRSA) |
| 6 | `What does HPSA mean? Where does that definition come from?` | Methodology Q&A with sources (RAG) |
| 7 | `Find Mile Blf Medcal Center` | Misspelled input |
| 8 | `Analyze the finances of Springfield General Hospital in Texas.` | Unknown hospital / uncovered state |
| 9 | Any question of your own | Free exploration |
| 10 | Click **Clear chat**, then: `Is it in financial distress?` | Context reset |

At the end, tell the developer: the most useful part, the most frustrating part, and one thing you would change.
