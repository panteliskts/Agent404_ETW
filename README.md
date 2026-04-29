# ETW

## Quick Start

Run the full app from the repo root:

```sh
cd /Users/pantelis/Desktop/ETW
./start_all.sh
```

Then open `http://127.0.0.1:3000`.

Development login is `admin` / `admin` unless you set `APP_AUTH_USERNAME` and `APP_AUTH_PASSWORD` in `.env`.

Application pages:

- `/` - optimization dashboard
- `/onboarding` - asset setup, data integration hub, scenario sandbox, and portfolio workflow
- `/account` - session, API key, audit log, and export controls

The frontend lives in `frontend/`, so run `npm` commands there. The frontend also needs the FastAPI backend on port `8000`; starting only `npm run dev` will load the page but leave the app non-functional.

See [docs/RUNNING_APP.md](docs/RUNNING_APP.md) for startup instructions, [docs/ONBOARDING_GUIDE.md](docs/ONBOARDING_GUIDE.md) for the operator onboarding guide, and [docs/DOPPLER_GUIDE.md](docs/DOPPLER_GUIDE.md) for running the repo with Doppler-managed secrets.

## Install Python Requirements Manually

```sh
./venv/bin/pip install -r requirements.txt -r api/requirements.txt
```
