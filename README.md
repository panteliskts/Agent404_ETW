# LogicVolt

Battery energy storage dispatch optimisation — Greek DAM / ENTSO-E edition

## Live demo

[https://logicvolt.vardalas.com/](https://logicvolt.vardalas.com/)

![QR code — logicvolt.vardalas.com](docs/assets/qr_logicvolt.png)

| Field    | Value                              |
| -------- | ---------------------------------- |
| URL      | <https://logicvolt.vardalas.com/>  |
| Username | `admin`                            |
| Password | `admin`                            |

---

## Quick start (local)

Run the full stack from the repo root:

```sh
cd /Users/pantelis/Desktop/ETW
./start_all.sh
```

The launcher wraps itself with Doppler when the CLI is present, injecting `GROQ_API_KEY` and other secrets automatically. Without Doppler the chatbot is disabled but everything else works.

Then open <http://127.0.0.1:3000>.

Default local login: `admin` / `admin` (override with `APP_AUTH_USERNAME` / `APP_AUTH_PASSWORD`).

### Pages

| Path          | Description                                                |
| ------------- | ---------------------------------------------------------- |
| `/`           | Landing page                                               |
| `/dashboard`  | Optimisation dashboard — forecast, dispatch schedule, KPIs |
| `/onboarding` | Asset setup, data integration hub, scenario sandbox        |
| `/account`    | Session, MFA, API keys, billing tiers, webhooks, audit log |
| `/pricing`    | Public subscription and pricing page                       |

---

## Install Python dependencies manually

```sh
./venv/bin/pip install -r requirements.txt -r api/requirements.txt
```

---

## Documentation

| Doc                                                                | Purpose                            |
| ------------------------------------------------------------------ | ---------------------------------- |
| [docs/RUNNING\_APP.md](docs/RUNNING_APP.md)                        | Full startup instructions          |
| [docs/ONBOARDING\_GUIDE.md](docs/ONBOARDING_GUIDE.md)              | Operator onboarding guide          |
| [docs/DOPPLER\_GUIDE.md](docs/DOPPLER_GUIDE.md)                    | Secret management with Doppler     |
| [docs/CHATBOT\_KNOWLEDGE\_BASE.md](docs/CHATBOT_KNOWLEDGE_BASE.md) | In-app AI assistant knowledge base |
