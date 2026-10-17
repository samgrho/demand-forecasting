# Demand Forecasting

Local demand forecasting and evidence reporting for hospitality and food businesses.

## What this project does

This project ingests localized public signals (events, weather, trends), builds forecast features, and produces demand predictions with source-backed evidence reports.

## Stack

- Python 3.11+
- FastAPI (API)
- Streamlit (dashboard)
- PostgreSQL (storage)
- XGBoost (baseline model)
- Playwright + BeautifulSoup + httpx (collection)

## Quick start

### 1) Clone and setup

```bash
git clone https://github.com/samgrho/demand-forecasting.git
cd demand-forecasting
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2) Configure env

```bash
cp .env.example .env
# edit .env values
```

### 3) Run API

```bash
uvicorn apps.api.main:app --reload --port 8000
```

### 4) Run dashboard

```bash
streamlit run apps/dashboard/app.py
```

## Docker (optional)

```bash
docker compose up --build
```

## Project layout

```text
demand-forecasting/
  apps/
    api/
    dashboard/
  data_pipeline/
    collectors/
    features/
    training/
    inference/
  reports/
    templates/
  db/
    migrations/
  tests/
```

## Notes

- Use only sources that allow access and respect robots.txt/ToS.
- Keep source URL + timestamp metadata for all evidence artifacts.
