# Tech Stack

## Data Pipeline (Python scripts)

| Purpose | Library / Tool | Version |
|---|---|---|
| Data manipulation | `pandas` | ≥ 2.1 |
| Numerical computing | `numpy` | ≥ 1.26 |
| ENTSO-E price data (Greece DA prices, load, generation) | `entsoe-py` | ≥ 0.6.10 |
| Fuel / commodity prices | `yfinance` | ≥ 0.2.40 |
| HTTP requests (weather & HENEX APIs) | `requests` | ≥ 2.31 |
| Fast columnar data storage | `pyarrow` (Parquet) | ≥ 15.0 |
| Progress bars | `tqdm` | ≥ 4.66 |
| Environment variable secrets | `python-dotenv` | ≥ 1.0 |
| Plotting / chart exports | `matplotlib` | ≥ 3.8 |

---

## Machine Learning (price forecasting)

| Purpose | Library / Tool | Version |
|---|---|---|
| Quantile regression price forecasting | `lightgbm` | ≥ 4.3 |
| Preprocessing, metrics, model utilities | `scikit-learn` | ≥ 1.4 |

---

## Optimisation (BESS dispatch)

| Purpose | Library / Tool | Version |
|---|---|---|
| Linear programming (charge/discharge scheduling) | `PuLP` | ≥ 2.8 |

---

## Backend API

| Purpose | Library / Tool |
|---|---|
| REST API framework | **FastAPI** |
| ASGI server | **Uvicorn** |
| API security / key auth | Custom `api/security.py` |

---

## Frontend

| Purpose | Library / Tool |
|---|---|
| React framework (SSR + routing) | **Next.js** (App Router) |
| Language | **TypeScript** |
| Styling | **Tailwind CSS** |
| HTTP client to backend | Native `fetch` via `frontend/lib/api.ts` |

---

## Streamlit Dashboard

| Purpose | Library / Tool |
|---|---|
| Interactive browser dashboard | **Streamlit** (`app.py`) |

---

## Infrastructure & DevOps

| Purpose | Tool |
|---|---|
| Reverse proxy / serving | **Nginx** (`nginx/`) |
| Service orchestration (local) | `start_all.sh` (Bash) |
| Python dependency management | `pip` + `requirements.txt` |
| Node dependency management | `npm` + `package.json` |
| Python environment isolation | `venv` |
| Version control | **Git** / GitHub |

---

## Data Storage

| Purpose | Format |
|---|---|
| Raw & processed time-series data | **Apache Parquet** (`.parquet`) |
| Trained model artefacts | **Pickle / Joblib** (`.pkl`, `.joblib`) — gitignored |

---

## Dev Tooling

| Purpose | Tool |
|---|---|
| Exploratory analysis | **Jupyter Notebooks** (`notebooks/`) |
| Secrets management | `.env` file (via `python-dotenv`) |
| Gitignore rules | `.gitignore` (excludes data, models, secrets, build artefacts) |