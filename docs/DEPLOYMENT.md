# Deployment and Execution

There are three supported ways to run the beta. All of them serve the API and the chat UI from one process.

| Path | Use it for | URL after start |
|---|---|---|
| A. Hosted (Render) | Testers and end users | https://rural-hospital-ai-agent.onrender.com/demo/ |
| B. Local Python | Development | http://127.0.0.1:8000/demo/ |
| C. Docker | Reproducing the server on any machine | http://127.0.0.1:8000/demo/ |

## Configuration

Copy `.env.example` to `.env`. Only `OPENAI_API_KEY` is required.

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | yes | LLM agent and methodology embeddings |
| `OPENAI_MODEL` | no | Defaults to `gpt-5.6-terra` |
| `CENSUS_API_KEY` | no | County demographics. Without it, demographics are reported as unavailable. |
| `DATABASE_URL` | no | Supabase/PostgreSQL snapshots (financial, reference, vector RAG) |
| `FINANCIAL_DATA_MODE` / `REFERENCE_DATA_MODE` | no | Set to `database_only` to serve imported snapshots instead of live CMS/Census calls |
| `METHODOLOGY_RETRIEVAL_MODE` | no | `vector` (needs `DATABASE_URL`) or `lexical` (local, offline) |

Without `DATABASE_URL`, set `METHODOLOGY_RETRIEVAL_MODE=lexical`. The app then runs fully on live public APIs, but the first analyses are slower.

## A. Render

The repository contains a Render Blueprint (`render.yaml`).

1. On Render, choose **New → Blueprint** and select this repository.
2. When prompted, enter `OPENAI_API_KEY`, `CENSUS_API_KEY` and `DATABASE_URL`.
3. Render installs `requirements.lock`, starts uvicorn, and health-checks `/health`.
4. Every push to `main` redeploys automatically.

Free instances sleep after inactivity, and the first request afterwards takes about 50 seconds. Before a demo or test session, open `/health` once to wake the service.

## B. Local Python (3.12)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.lock   # pinned, reproducible; requirements.txt holds the ranges
cp .env.example .env               # then add your OPENAI_API_KEY
python -m uvicorn app.main:app --reload
```

## C. Docker

```bash
docker build -t rural-hospital-agent .
docker run --rm -p 8000:8000 --env-file .env rural-hospital-agent
```

## Database setup (optional)

Apply the SQL files in `supabase/migrations/` in filename order, then load the data:

```bash
python -m scripts.import_financial_history --help
python -m scripts.import_reference_data --help
python -m scripts.import_methodology_vectors --init-db
```

For details, see [financial_database.md](financial_database.md), [reference_database.md](reference_database.md) and [data_quality_and_rag.md](data_quality_and_rag.md).

## Verify a deployment

```bash
curl https://<host>/health                    # {"status":"healthy"}
curl "https://<host>/hospitals?state=WY"      # CMS lookup works
python -m pytest -q                           # offline suite, no keys needed
```

Then open `/demo/` and run the "Full hospital investigation" quick action.

## Updating dependencies

Edit the ranges in `requirements.txt`, install them into a clean venv, and run `pip freeze > requirements.lock`. Then run the tests before you commit.
