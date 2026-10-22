# LoanOps Intelligence

An AI-assisted investigation layer for loan-operations exceptions between an upstream origination system (simulated nCino) and a downstream servicing system (simulated Finastra Loan IQ).

> **Proof of concept.** All banking systems, loan records, mappings, agreements, and historical cases are synthetic. Nothing connects to a real banking environment.

## Current status: Phase 7 (end-to-end evaluation)

| Phase | Delivers |
|---|---|
| 0 | FastAPI backend, React + TypeScript frontend, `GET /api/health` |
| 1 | Simulated nCino and Loan IQ feeds, normalization, versioned ingestion, reference data in SQLite, read APIs |
| 2 | 12 deterministic validation rules, configurable severity, exception records with stable IDs, controlled status lifecycle with history |
| 3 | Evidence registry with stable IDs (EV-00001…), per-exception retrieval with relevance reasons and gaps, traceability check |
| 4 | Local LLM investigation through Ollama: controlled prompt, schema-enforced report, evidence-ID verification, bounded retry, full audit |
| 5 | Operations Workbench (React): dashboard, exception detail, record comparison, evidence with traceability, AI report with clickable evidence, status controls, resolution form, audit trail |
| 6 | Analyst resolution workflow (AI recommendation stored separately from the confirmed outcome), feedback of confirmed cases into history, recurrence detection, unified audit trail |
| 7 | Evaluation runner: all 11 scenarios through the shared investigation core, scored against expected behaviour, quality metrics, manual vs AI-assisted time **estimate**. Isolated from operational data. |

See `docs/PROJECT_LOG.md` for architecture, decisions, the scenario catalogue, and the roadmap.

## Prerequisites

| Tool | Version tested |
|---|---|
| Python | 3.13 |
| Node.js | 22.x |
| npm | 10.x |
| Ollama | 0.40 (not used until Phase 4) |

## Setup (Windows, Command Prompt)

Use a folder path **without spaces**, for example `D:\loanops-intelligence`.

### Backend

```bat
cd D:\loanops-intelligence\backend
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

Run the tests. They use an in-memory database and never touch your data file.

```bat
pytest -v
```

Load the synthetic data into `backend\data\loanops.db`:

```bat
python -m app.scripts.seed --reset
```

Running it again without `--reset` is safe: nothing is duplicated.

Run validation to raise exceptions:

```bat
python -m app.scripts.validate
```

Validation can also be re-run safely. Existing exceptions are re-detected rather than duplicated. Thresholds and severity live in `backend\config\validation_rules.json`.

### AI investigation (Ollama)

Make sure Ollama is running and that a model is pulled. Set `LOANOPS_OLLAMA_MODEL` in `backend\.env` to one of the models shown by `ollama list`.

```bat
ollama pull qwen2.5:7b
python -m app.scripts.ai_check
python -m app.scripts.investigate EXC-00001 --by analyst.yourname
```

The automated tests use a scripted fake model, so `pytest` does not need Ollama.

### Evaluation (Phase 7)

```bat
python -m app.scripts.evaluate --estimate-only
python -m app.scripts.evaluate --only S01
python -m app.scripts.evaluate
```

- `--estimate-only` prints the time comparison instantly, with no model calls.
- `--only S01` runs a single scenario (about 4 minutes) as a smoke test.
- With no options, all 11 scenarios run, taking roughly 45–60 minutes on CPU. Leave it running.

Each scenario runs through exactly the same evidence, prompt, validation and retry logic as the workbench. Results go to the `evaluation_runs` and `evaluation_results` tables and to `backend\data\evaluations\EVAL-xxxxx.json`. They are also served at `GET /api/evaluations/{run_id}`.

**Exception statuses, AI investigation history and the audit trail are not touched.** Resolved exceptions are still evaluated.

The analyst-time figures are **estimates**, set in `backend\config\manual_baseline_estimates.json`. Only the model time is measured.

Start the API (leave this window open):

```bat
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- Interactive API docs: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/api/health

### Frontend

Open a **second** Command Prompt:

```bat
cd D:\loanops-intelligence\frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173 to reach the **Operations Workbench**.

1. Enter your analyst ID in the header, e.g. `analyst.yourname`. This is a POC, so there is no login; the ID is recorded on every action you take.
2. Open an exception from the dashboard. The tabs are:
   - **Overview:** the deterministic discrepancy, an upstream/downstream comparison, and status controls.
   - **Evidence:** the package the AI sees, plus the platform's gaps. Click an evidence ID to open the snapshot and its live traceability check.
   - **AI investigation:** run the local model and read the report. Every claim sits next to clickable evidence IDs.
   - **Resolution:** record your confirmed root cause. It's shown next to what the AI suggested, never merged with it.
   - **Audit trail:** every event, labelled Analyst, Platform, AI model or AI service.

Visual language:
- **Slate:** deterministic platform facts.
- **Violet, dashed:** AI-generated, not confirmed.
- **Green:** analyst-confirmed.

### PowerShell instead of Command Prompt

Activate the virtual environment with `.venv\Scripts\Activate.ps1`. If PowerShell blocks the script, run this once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## API (Phase 1)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness and version |
| GET | `/api/mock/ncino/loans` | Raw simulated upstream feed |
| GET | `/api/mock/loaniq/loans` | Raw simulated downstream feed |
| POST | `/api/ingestion/run?source=ALL` | Pull the feeds and ingest them (`ALL`, `NCINO_SIM`, `LOANIQ_SIM`) |
| GET | `/api/ingestion/batches` | Ingestion batch history |
| GET | `/api/ingestion/raw-records?outcome=REJECTED` | Raw payloads with their ingestion outcome |
| GET | `/api/loans` | Current upstream/downstream pair for each loan |
| GET | `/api/loans/{loan_id}` | One loan with its full version history |
| GET | `/api/reference/mapping-rules?version=PRODMAP-v1` | Product mapping configuration |
| GET | `/api/reference/clauses?loan_id=LN-1003` | Agreement and amendment clauses |
| GET | `/api/reference/historical-exceptions?category=PRODUCT_MISMATCH` | Past cases |
| POST | `/api/validation/run` | Validate all current loan records |
| GET | `/api/validation/runs` | Validation run history |
| GET | `/api/validation/rules` | Rule catalogue with configured severity |
| GET | `/api/exceptions?status=&severity=&category=&loan_id=&active_only=` | Exception list |
| GET | `/api/exceptions/summary` | Counts by status, severity and category |
| GET | `/api/exceptions/{exception_id}` | Exception detail, evaluated records, status history |
| PATCH | `/api/exceptions/{exception_id}/status` | Analyst status change: `{"to_status", "actor", "reason"}` |
| GET | `/api/exceptions/{exception_id}/evidence` | Evidence package (items, relevance, gaps) |
| GET | `/api/evidence/{evidence_id}` | Evidence snapshot plus traceability (CURRENT / SOURCE_CHANGED / SOURCE_MISSING) |
| GET | `/api/ai/status` | Ollama reachable? Configured model installed? |
| POST | `/api/exceptions/{exception_id}/investigations` | Run an AI investigation: `{"requested_by": "analyst.x"}` |
| GET | `/api/exceptions/{exception_id}/investigations` | Investigation history for an exception |
| GET | `/api/investigations/{investigation_id}` | Full audit: report, evidence snapshot, raw output, validation errors |

AI investigation errors return `{"detail": {"error_code", "message", "investigation_id"}}`:

| Status | Error code |
|---|---|
| 503 | `OLLAMA_UNAVAILABLE`, `MODEL_NOT_FOUND` |
| 504 | `TIMEOUT` |
| 502 | `INVALID_OUTPUT`, `LLM_RESPONSE_ERROR` |
| 409 | Exception is RESOLVED or REJECTED |

### Resolution and audit (Phase 6)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/resolution/options` | Values and labels for decision, root-cause category, record in error, outcome |
| POST | `/api/exceptions/{exception_id}/resolution` | Record the analyst's resolution (moves the exception to RESOLVED) |
| GET | `/api/exceptions/{exception_id}/resolution` | The resolution, including a snapshot of the AI recommendation reviewed |
| GET | `/api/resolutions?analyst_decision=&root_cause_category=` | All resolutions (Phase 7 metrics) |
| GET | `/api/exceptions/{exception_id}/audit` | Chronological audit trail with actor types |

To resolve, the exception must be UNDER_INVESTIGATION, RECOMMENDATION_GENERATED or ESCALATED. Resolving never changes loan records or mappings. Each resolution is added to historical cases as `ANALYST_CONFIRMED`, using the analyst's text only, so future investigations on other loans can retrieve it.

Amounts are returned as strings (for example `"10000000.0"`) to avoid floating-point loss. All timestamps are UTC.

## Project layout

```
loanops-intelligence/
├── backend/
│   ├── app/
│   │   ├── main.py              # app factory, routers, lifespan (creates tables)
│   │   ├── config.py            # LOANOPS_* settings
│   │   ├── schemas.py           # API response models
│   │   ├── api/                 # health, mock_sources, ingestion, loans, reference
│   │   ├── db/                  # engine/session, ORM models
│   │   ├── integration/         # vocab, normalizers, sources, ingestion
│   │   ├── reference/loader.py  # mapping rules, clauses, historical cases
│   │   ├── validation/          # pure rules, config, severity, mapping index; runner (DB)
│   │   ├── exception_engine/    # status machine (pure), persistence service
│   │   ├── evidence/            # package & relevance (pure), retrieval, content, traceability
│   │   ├── ai/                  # Ollama client, report schema, prompt, validation, policy, service
│   │   ├── resolution/          # vocab (pure), resolution service, audit trail
│   │   ├── evaluation/          # scenarios, scoring, baseline estimate (pure); runner
│   │   └── scripts/             # seed.py, validate.py, ai_check.py, investigate.py
│   ├── config/validation_rules.json  # tolerances and severity rules
│   ├── seed_data/               # synthetic JSON feeds and reference data
│   ├── tests/                   # pytest (in-memory SQLite)
│   ├── requirements.txt
│   └── .env.example
├── frontend/src/
│   ├── api/                     # typed client (timeouts, error parsing) and response types
│   ├── lib/                     # hooks (loading, hash routing), formatting, analyst ID context
│   ├── components/              # badges, comparison, evidence + drawer, AI report, status, resolution, audit
│   ├── pages/                   # dashboard, exception detail
│   └── styles.css
├── docs/PROJECT_LOG.md
└── README.md
```
