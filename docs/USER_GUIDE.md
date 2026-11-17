# User Guide

For analysts, students and rural-health staff. No programming is needed.

## Open the app

1. Go to **https://rural-hospital-ai-agent.onrender.com/demo/**
2. If the page is slow to appear, wait about a minute. The free hosting tier sleeps when no one is using it.
3. Type a question in the box at the bottom and press **Send** (or Enter).

## What you can ask

| Goal | Example question |
|---|---|
| Find a hospital | `Find Reedsburg Area Medical Center in Sauk County, WI.` |
| Check financial distress | `Analyze the financial condition of Mile Bluff Medical Center in Juneau County, Wisconsin.` |
| Follow up on that hospital | `Is it getting better or worse since 2020?` |
| Draw a trend chart | `Show a financial trend line chart for Mile Bluff Medical Center from 2020 to 2024.` |
| Compare hospitals | `Compare Mile Bluff Medical Center and Reedsburg Area Medical Center in Wisconsin.` |
| Look at healthcare access | `Analyze healthcare access around rural hospitals in Fremont County, Wyoming.` |
| Ask about the method | `What is a geographic HPSA versus a population HPSA?` |

The **quick action** buttons fill in tested examples. Use **Hide quick actions** to get more room, and use **Clear chat** to start a new topic.

## Reading the answer

- **Progress steps** show which data sources are being checked. A full investigation can take 1–3 minutes.
- **Source / coverage cards** show the dataset, report year and retrieval date behind each number.
- **Data-quality notices** (yellow) mark unreliable ratios, mismatched fiscal periods or missing data. Read them before you draw conclusions.
- **Charts**: you can switch the metric with the selector above the chart. Gaps mean that year has no report.

## Coverage and limits

- Historical financial data is loaded for **California, Wisconsin and Wyoming, 2020–2024**. For other states, the app either fetches the data live (slower) or tells you the data is not covered.
- Answers use only public CMS, Census ACS and HRSA data. They are **not** closure predictions or financial advice.
- Conversation memory is short: only the last few messages are kept. Name the hospital again if the app loses track.

## If something goes wrong

| What you see | What to do |
|---|---|
| Page does not load | Wait 60 seconds and refresh. The server is waking up. |
| "Sorry, something went wrong…" | Press Send again. If it repeats, rephrase your question or add the state. |
| Wrong hospital picked | Add the county or city, or use the 6-digit CMS CCN. |
| "Not covered" / missing data | This is expected outside the loaded states and years. |
