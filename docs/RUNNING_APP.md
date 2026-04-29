# Running The App

This repo has two web pieces:

- API backend: FastAPI from the repo root on `http://127.0.0.1:8000`
- Frontend: Next.js from `frontend/` on `http://127.0.0.1:3000`

The frontend can load by itself, but it will not be functional until the API is also running.

## Fastest Start

From the repo root:

```sh
cd /Users/pantelis/Desktop/ETW
./start_all.sh
```

The launcher automatically re-runs itself through Doppler when the Doppler CLI is available, so the API and frontend both receive the same secrets, including `GROQ_API_KEY`.

Then open:

```text
http://127.0.0.1:3000
```

Default development login:

```text
Username: admin
Password: admin
```

For a real password, set `APP_AUTH_PASSWORD` and `APP_SECRET_KEY` in Doppler.

Keep that terminal open. Press `Ctrl-C` in that terminal to stop the services started by the launcher.

The launcher will:

- inject Doppler secrets automatically when Doppler is configured
- create `venv/` if it does not exist
- install missing Python dependencies from `requirements.txt` and `api/requirements.txt`
- install frontend dependencies if `frontend/node_modules/` is missing
- start the API on port `8000`
- start the frontend on port `3000`
- write logs to `.logs/api.log` and `.logs/frontend.log`

If Doppler is unavailable and you intentionally want to run with local environment variables only:

```sh
USE_DOPPLER=0 REQUIRE_GROQ_KEY=0 ./start_all.sh
```

## Where To Run NPM

Run `npm` commands inside the frontend folder:

```sh
cd /Users/pantelis/Desktop/ETW/frontend
npm run dev
```

That only starts the frontend. For the app to actually work, the backend must also be running.

## Manual Start

Terminal 1, from the repo root:

```sh
cd /Users/pantelis/Desktop/ETW
./venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Terminal 2, from the frontend folder:

```sh
cd /Users/pantelis/Desktop/ETW/frontend
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Open:

```text
http://127.0.0.1:3000
```

Use the same hostname consistently in the browser. For example, if you open `http://localhost:3000`, the frontend will call `http://localhost:8000`; if you open `http://127.0.0.1:3000`, it will call `http://127.0.0.1:8000`. Keeping those hostnames aligned lets the browser send the login cookie.

Check the API directly:

```text
http://127.0.0.1:8000/health
```

The `/status`, `/forecast`, `/optimize`, and `/feature-importance` API routes require a browser login session.

For the operator workflow, chart interpretation, and review checklist, see [ONBOARDING_GUIDE.md](ONBOARDING_GUIDE.md).

## Troubleshooting

If the frontend loads but charts/buttons do not work, check the API first:

```sh
curl http://127.0.0.1:8000/health
```

If port `3000` or `8000` is already in use, stop the old process or run with different ports:

```sh
API_PORT=8010 FRONTEND_PORT=3010 ./start_all.sh
```

Then open `http://127.0.0.1:3010`.

The launcher does not reuse existing services by default because an old plain `npm run dev` process will not have Doppler secrets. If you know the existing services were already started through Doppler:

```sh
REUSE_EXISTING_SERVICES=1 ./start_all.sh
```

If Python dependencies are missing:

```sh
cd /Users/pantelis/Desktop/ETW
./venv/bin/pip install -r requirements.txt -r api/requirements.txt
```

If frontend dependencies are missing:

```sh
cd /Users/pantelis/Desktop/ETW/frontend
npm install
```

## Security Settings

The app includes:

- cookie-based login sessions with HttpOnly session cookies
- CSRF validation for authenticated POST/PUT/PATCH/DELETE requests
- FastAPI CORS restricted to the configured frontend origins
- trusted host checks for local hosts
- API and login rate limiting
- security headers on both the API and Next.js frontend

Set these in `.env` before sharing the app beyond local development:

```sh
APP_AUTH_USERNAME=admin
APP_AUTH_PASSWORD=use-a-real-password
APP_SECRET_KEY=use-a-long-random-secret
APP_ALLOWED_ORIGINS=http://127.0.0.1:3000
APP_ALLOWED_HOSTS=127.0.0.1,localhost
APP_COOKIE_SECURE=false
```
