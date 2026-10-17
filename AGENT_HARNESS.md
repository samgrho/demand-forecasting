# AGENT_HARNESS.md

## Purpose

This file is an execution harness for AI coding agents (including VS Code Copilot Chat) to build and extend the **demand-forecasting** project in structured phases.

The product predicts localized business demand (hotel pricing pressure, donut bulk-order likelihood) using public/local signals and produces **source-backed evidence reports**.

---

## Project Context

- Repository: `samgrho/demand-forecasting`
- Current stack:
  - Python 3.11+
  - FastAPI backend
  - Streamlit dashboard
  - PostgreSQL
  - XGBoost baseline model
  - Playwright/BeautifulSoup/httpx collectors
- Priority: **free to build and run** (avoid paid APIs)

---

## Guardrails (Non-Negotiable)

1. **Use free/open data sources only** unless explicitly approved.
2. **Respect robots.txt and Terms of Service** for every scraped source.
3. Add request throttling, retries, and caching for collectors.
4. Every forecast must be explainable with **evidence items**:
   - `source_name`
   - `source_url`
   - `observed_at`
   - `summary`
   - `relevance_score`
5. Never hardcode secrets. Use `.env` and document required variables in `.env.example`.
6. Keep all new logic typed, modular, and testable.

---

## Target Architecture

- `apps/api`:
  - Forecast endpoints
  - Evidence retrieval endpoints
- `apps/dashboard`:
  - Location/date input
  - Forecast result + confidence
  - Evidence cards and source links
- `data_pipeline/collectors`:
  - Events collector
  - Weather collector
  - Trends collector
- `data_pipeline/features`:
  - Feature assembly and validation
- `data_pipeline/training`:
  - Baseline training job
  - Model serialization and metrics artifact
- `data_pipeline/inference`:
  - Online inference from current signals
- `reports/templates`:
  - HTML/Markdown evidence report templates
- `db`:
  - ORM models and migrations

---

## Data Sources (Free-First)

Preferred sources:
- Open-Meteo (weather)
- Public city/tourism event pages (allowed scraping only)
- Public school/holiday calendars
- Google Trends via `pytrends`
- Optional: GDELT / public government event calendars

For each source, implement:
- adapter module
- normalization function
- source attribution metadata
- tests for parser stability

---

## Phase Plan (Execution Order)

### Phase 1 — Make the skeleton runnable
**Goal:** End-to-end demo with placeholder predictions.

Tasks:
1. Ensure API `/health` and `/forecast` run locally.
2. Ensure dashboard calls API and renders score/confidence.
3. Add basic logging and structured error handling.
4. Add Makefile commands:
   - `make dev-api`
   - `make dev-ui`
   - `make test`

Acceptance criteria:
- API + dashboard run without code edits after setup.
- A forecast request returns valid schema.

---

### Phase 2 — Implement real signal collectors
**Goal:** Replace placeholders with real data collection.

Tasks:
1. Implement `events.py` adapters for 1–2 allowed local sources.
2. Implement `weather.py` with Open-Meteo calls.
3. Implement `trends.py` using `pytrends`.
4. Add caching layer (file or DB) with TTL.

Acceptance criteria:
- Collectors return normalized outputs.
- Collector tests pass with mocked HTTP responses.

---

### Phase 3 — Feature engineering and model training
**Goal:** Produce reproducible baseline model artifacts.

Tasks:
1. Build canonical feature schema (event_count, trend_index, holiday/weekend, weather severity).
2. Add training script with train/validation split.
3. Save model + metadata (features list, version, metrics).
4. Add evaluation report (MAE/RMSE).

Acceptance criteria:
- Running training generates model artifact and metrics file.
- Inference uses same feature ordering as training.

---

### Phase 4 — Evidence-backed reporting
**Goal:** Explain “why” forecasts changed.

Tasks:
1. Persist source records used in each inference.
2. Implement report generator (Markdown or HTML).
3. Add endpoint to retrieve latest evidence report by location/date range.

Acceptance criteria:
- Each forecast can display associated source links and summaries.

---

### Phase 5 — Production hardening (lightweight)
**Goal:** Safe and maintainable deployment.

Tasks:
1. Add CI (lint, tests, type checks).
2. Add Alembic migrations.
3. Add `.env` validation on startup.
4. Add request rate limiting and timeout configs.

Acceptance criteria:
- CI passes on PRs.
- App starts with clear errors for missing required env vars.

---

## Coding Standards for Agent

- Use small pure functions where possible.
- Prefer explicit types and dataclasses/Pydantic models.
- Keep IO boundaries isolated from feature/model logic.
- Add docstrings for public functions.
- Write/update tests for every behavior change.
- Avoid breaking existing endpoint contracts.

---

## Definition of Done (per task)

A task is complete only if:
1. Code compiles and runs.
2. Tests added/updated and passing.
3. README or inline docs updated if behavior changed.
4. No secrets committed.
5. All new user-facing outputs include source attribution when relevant.

---

## Reusable VS Code Copilot Task Prompts

### Prompt A — Implement a collector safely

> Implement `data_pipeline/collectors/weather.py` using Open-Meteo free API. Add request timeout, retry (max 3), and normalized output with `weather_severity_index`. Add unit tests with mocked HTTP responses and edge cases. Do not modify unrelated files.

### Prompt B — Improve forecast endpoint with evidence

> Update `/forecast` endpoint to collect signals, build features, run inference, and return `evidence` items with source metadata. Keep response schema backward compatible. Add tests for valid and partial-data scenarios.

### Prompt C — Add model training pipeline

> Implement a reproducible training script under `data_pipeline/training/` that reads prepared feature rows, trains baseline XGBoost, computes MAE/RMSE, and saves model + metrics JSON. Add a CLI entrypoint and tests.

### Prompt D — Add report generation

> Build a report generator in `reports/templates` that outputs Markdown evidence reports with title, forecast summary, and cited source list. Add API endpoint to fetch report by location/date range.

---

## Single-Shot Bootstrap Prompt (for Copilot Chat)

> You are working in the `demand-forecasting` repository. Follow AGENT_HARNESS.md strictly. Execute Phase 1 fully: make API and dashboard run cleanly, add Makefile commands (`dev-api`, `dev-ui`, `test`), and improve error handling/logging without changing public schemas. Add/update tests for touched logic. Provide a concise summary of changes and any manual steps.

---

## Notes for Human Operator

- Start by running the bootstrap prompt above.
- Then run phases sequentially.
- Require PR reviews for each phase and keep commits scoped.
