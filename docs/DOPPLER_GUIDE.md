# Doppler Guide

Use Doppler to inject the app's environment variables at runtime instead of keeping real secrets in `.env`.

The Doppler CLI is already installed on this machine:

```sh
doppler --version
```

## 1. Log In

From the repo root:

```sh
cd /Users/pantelis/Desktop/ETW
doppler login
```

This opens the browser and stores a local Doppler CLI token.

## 2. Connect This Repo To A Doppler Project

If the Doppler project already exists:

```sh
cd /Users/pantelis/Desktop/ETW
doppler setup
```

Choose the project and config, for example:

```text
project: bess-optimizer
config: dev
```

For non-interactive setup:

```sh
doppler setup --project bess-optimizer --config dev --no-interactive
```

Check what the repo is configured to use:

```sh
doppler configure debug
```

## 3. Add The Secrets This App Expects

The app reads these variables:

```text
ENTSOE_API_KEY
APP_AUTH_USERNAME
APP_AUTH_PASSWORD
APP_AUTH_ROLE
APP_AUTH_PASSWORD_HASH
APP_SECRET_KEY
APP_ENCRYPTION_KEY
APP_ALLOWED_ORIGINS
APP_ALLOWED_HOSTS
APP_COOKIE_SECURE
APP_RATE_LIMIT_REQUESTS
APP_RATE_LIMIT_WINDOW_SECONDS
APP_LOGIN_RATE_LIMIT_REQUESTS
APP_LOGIN_RATE_LIMIT_WINDOW_SECONDS
AZURE_TENANT_ID
AZURE_CLIENT_ID
AZURE_CLIENT_SECRET
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
APP_PUBLIC_URL
APP_FRONTEND_URL
OIDC_ALLOWED_DOMAINS
OIDC_DEFAULT_ROLE
NEXT_PUBLIC_API_URL
```

Minimum local development set:

```sh
doppler secrets set APP_AUTH_USERNAME=admin
doppler secrets set APP_AUTH_PASSWORD=use-a-real-password
doppler secrets set APP_AUTH_ROLE=admin
doppler secrets set APP_SECRET_KEY="$(openssl rand -base64 48)"
doppler secrets set APP_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
doppler secrets set APP_ALLOWED_HOSTS=127.0.0.1,localhost
doppler secrets set APP_COOKIE_SECURE=false
```

Optional live data:

```sh
doppler secrets set ENTSOE_API_KEY=your-entsoe-token
```

Optional encryption key:

```sh
doppler run -- ./venv/bin/python -c "from api.encryption import generate_key; print(generate_key())"
doppler secrets set APP_ENCRYPTION_KEY=the-generated-value
```

View configured secret names without printing values:

```sh
doppler secrets --only-names
```

## 4. Run The Whole App With Doppler

The launcher now wraps itself with Doppler automatically when the Doppler CLI is available:

```sh
cd /Users/pantelis/Desktop/ETW
./start_all.sh
```

Then open:

```text
http://127.0.0.1:3000
```

The frontend and API will both inherit Doppler-injected variables.

If you want to force Doppler and fail when the CLI is unavailable:

```sh
USE_DOPPLER=1 ./start_all.sh
```

If you need a specific Doppler project/config without saving local setup:

```sh
DOPPLER_RUN_ARGS="--project bess-optimizer --config dev" ./start_all.sh
```

## 5. Run Individual Services With Doppler

Backend only:

```sh
cd /Users/pantelis/Desktop/ETW
doppler run -- ./venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Frontend only:

```sh
cd /Users/pantelis/Desktop/ETW/frontend
doppler run -- npm run dev -- --hostname 127.0.0.1 --port 3000
```

Normally, prefer `./start_all.sh`; it will call `doppler run` for you.

## 6. Use A Specific Project Or Config

If you do not want to save local Doppler config:

```sh
DOPPLER_RUN_ARGS="--project bess-optimizer --config dev" ./start_all.sh
```

Common configs:

```sh
DOPPLER_RUN_ARGS="--project bess-optimizer --config dev" ./start_all.sh
DOPPLER_RUN_ARGS="--project bess-optimizer --config stg" ./start_all.sh
DOPPLER_RUN_ARGS="--project bess-optimizer --config prd" ./start_all.sh
```

## 7. Production Or CI Usage

For CI or deployment, use a Doppler service token:

```sh
DOPPLER_TOKEN=dp.st.xxxxx ./start_all.sh
```

Do not commit service tokens. Store them in the CI/CD platform's secret manager.

## 8. Offline/Fallback Mode

Create a local encrypted fallback cache:

```sh
doppler run --fallback .doppler.fallback.json -- ./start_all.sh
```

Run from the fallback only:

```sh
doppler run --fallback .doppler.fallback.json --fallback-only -- ./start_all.sh
```

Add `.doppler.fallback.json` to `.gitignore` if you use it.

## 9. Troubleshooting

Check the active Doppler project/config:

```sh
doppler configure debug
```

Check the app can see a secret:

```sh
doppler run -- printenv APP_AUTH_USERNAME
```

If the frontend loads but authentication fails, make sure these match the browser URL:

```text
APP_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
APP_ALLOWED_HOSTS=127.0.0.1,localhost
APP_COOKIE_SECURE=false
```

If `ENTSOE_API_KEY` is missing, the app can still run using cached/demo data, but live ENTSO-E data will not be available.

If you need to reset the local Doppler project/config:

```sh
doppler configure reset
doppler setup
```
