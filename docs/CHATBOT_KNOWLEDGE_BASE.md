# LogicVolt Groq Chatbot Knowledge Base

Use this file as the documentation source for the in-app Groq chatbot. The chatbot should answer from this knowledge base first. If a user asks for something not covered here, the chatbot should say what information is missing and suggest a practical next step instead of guessing.

## Assistant Behavior Rules

- Be concise, accurate, and practical.
- Treat the app as decision support for battery energy storage operations, not as an automated trading system.
- Do not invent product features, prices, contracts, integrations, performance claims, compliance certifications, or operational limits.
- When explaining charts or KPIs, use the definitions in this file.
- When troubleshooting, ask the user to check the app status, API health, logs, or authentication state before assuming a code issue.
- Never reveal or request secrets such as `GROQ_API_KEY`, API keys, passwords, session cookies, or MFA secrets.
- For local development credentials, only mention that the default username/password is `admin` / `admin` when the user is clearly asking about local development.

## Product Summary

LogicVolt is an enterprise SaaS platform for battery energy storage system dispatch planning. It combines market price forecasting, degradation-aware optimization, state-of-charge guardrails, scenario comparison, data feed context, and enterprise access controls in a web dashboard.

The app helps operators, traders, developers, and asset managers answer:

- What is the forecasted dispatch value over the active horizon?
- When should the battery charge, discharge, or remain idle?
- How sensitive is the schedule to degradation and efficiency assumptions?
- Does the recommended schedule stay within the operating envelope?
- Which market and weather features are influencing the forecast?
- Is the data/model layer ready for a schedule review?

The app should be described as a secure decision-support workspace. It is not a live trading engine and does not automatically dispatch physical assets.

## Main Pages

### `/` - Optimization Dashboard

The dashboard is the main operating page. It includes login, model/data status, asset controls, scenario controls, forecasts, optimization results, dispatch charts, state-of-charge charts, and feature importance.

Key dashboard functions:

- Secure sign-in.
- Session check and logout.
- Model readiness status.
- Data source status: live API, cache, demo synthetic, or pending.
- Asset selection, including named batteries and a fleet aggregate view.
- Battery assumption sliders.
- Scenario presets.
- Forecast review using Q10, Q50, Q90, and actual prices.
- Dispatch optimization.
- KPI review.
- State-of-charge compliance review.
- Feature importance inspection.

The login screen describes the app as "LogicVolt" for battery dispatch intelligence. It highlights forecast uncertainty, constrained dispatch, degradation-aware idle periods, and scenario controls.

### `/onboarding` - Plug-and-Play Battery Setup

The onboarding page explains the SaaS setup workflow for a battery asset.

Sections:

- Asset digital twin wizard.
- Data integration hub.
- SaaS operating flow.
- Scenario sandbox.
- Portfolio management.

Asset digital twin inputs:

- Energy capacity in MWh.
- Power rating in MW.
- Round-trip efficiency.
- Minimum and maximum SoC limits.
- Cycle life and degradation cost.
- Initial operating state of charge.

Data feed cards:

- HEnEx: Day-Ahead Market prices.
- IPTO: Grid load and renewable forecast signals.
- Open-Meteo: Weather drivers for price forecasting.
- TTF / EEX: Gas and carbon market context.

Operating flow:

1. Plug in an asset with hardware limits, degradation assumptions, and operating constraints.
2. Validate market, grid, weather, and fuel data feed health.
3. Run the optimizer to generate a 15-minute dispatch plan.
4. Export or integrate the schedule for reporting or downstream systems.

Scenario sandbox examples:

- Solar curtailment.
- Evening scarcity.
- High degradation cost.

Portfolio examples:

- Athens Battery 1.
- Thessaloniki Battery 2.
- Patras Battery 3.
- Fleet Aggregate.

### `/account` - Account, API, and Compliance Controls

The account page manages access, integrations, audit trails, MFA, and API keys.

Sections:

- User session.
- Multi-factor authentication.
- API key management.
- Audit log.

Security concepts shown on the page:

- Signed HttpOnly cookies.
- Double-submit CSRF protection.
- Per-IP rate limits.
- TOTP MFA compatible with Google Authenticator, 1Password, and Authy.
- Argon2id-hashed API keys.
- API key plaintext is shown only once on creation.
- Audit entries are appended through a SQLite WORM-style authorizer that blocks update/delete at the driver level.

API key roles:

- Viewer: forecast and status only.
- Operator: can run optimizations.
- Admin: full management access.

## Authentication and Access

The app requires login for protected dashboard/API routes. In local development, the default credentials are:

```text
Username: admin
Password: admin
```

In shared or production-like use, set a real password and secret:

```sh
APP_AUTH_USERNAME=admin
APP_AUTH_PASSWORD=use-a-real-password
APP_SECRET_KEY=use-a-long-random-secret
```

If MFA is enabled, login requires a 6-digit TOTP code after username/password verification.

If the app says authentication is required:

- Sign in again.
- Hard-refresh the browser if needed.
- Keep hostnames consistent. For example, use `127.0.0.1` for both frontend and API, or `localhost` for both.

## Running the App

The repo has two web pieces:

- FastAPI backend from the repo root on `http://127.0.0.1:8000`.
- Next.js frontend from `frontend/` on `http://127.0.0.1:3000`.

Fastest local start:

```sh
./start_all.sh
```

Then open:

```text
http://127.0.0.1:3000
```

The launcher:

- Uses Doppler automatically when available.
- Injects secrets such as `GROQ_API_KEY` into the API and frontend processes.
- Creates `venv/` if needed.
- Installs Python dependencies from `requirements.txt` and `api/requirements.txt` if missing.
- Installs frontend dependencies if `frontend/node_modules/` is missing.
- Starts the API on port `8000`.
- Starts the frontend on port `3000`.
- Writes logs to `.logs/api.log` and `.logs/frontend.log`.

If Doppler is unavailable and local environment variables are intentional:

```sh
USE_DOPPLER=0 REQUIRE_GROQ_KEY=0 ./start_all.sh
```

If ports are already in use:

```sh
API_PORT=8010 FRONTEND_PORT=3010 ./start_all.sh
```

Then open:

```text
http://127.0.0.1:3010
```

The launcher does not reuse existing services by default, because an old plain `npm run dev` process might not have Doppler secrets. If the user knows the existing services were already started correctly:

```sh
REUSE_EXISTING_SERVICES=1 ./start_all.sh
```

Manual API start:

```sh
./venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Manual frontend start:

```sh
cd frontend
npm run dev -- --hostname 127.0.0.1 --port 3000
```

The frontend can load by itself, but the app will not be functional until the API is also running.

## Groq Chatbot

The app includes a native Next.js chatbot widget in the bottom-right corner of the frontend. It streams responses from Groq through the Vercel AI SDK.

Relevant files:

- `frontend/app/api/chat/route.ts`: secure server route for Groq.
- `frontend/components/chat-widget.tsx`: floating React widget.
- `frontend/app/layout.tsx`: global widget mount.

The Groq key must be available server-side as:

```sh
GROQ_API_KEY=your_groq_api_key
```

Optional model override:

```sh
GROQ_MODEL=llama-3.1-8b-instant
```

The browser sends chat messages only to `/api/chat`. The Groq API key stays on the server and is never exposed to the client.

If the chat route returns:

```json
{"error":"Groq is not configured. Add GROQ_API_KEY to Doppler for this app."}
```

then the Next.js server cannot see `GROQ_API_KEY`. Start through `./start_all.sh` or ensure the key exists in the shell environment.

## Dashboard Controls

Default optimization parameters:

- Capacity: `100 MWh`.
- Power: `50 MW`.
- Round-trip efficiency: `90%`.
- Degradation cost: `5 EUR/MWh`.
- Initial SoC: `50%`.
- Scenario: `Base`.

Scenario options:

- Base.
- Mild Degradation.
- Severe Degradation.

Scenario derating:

- Base: capacity factor `1.00`, efficiency factor `1.00`.
- Mild Degradation: capacity factor `0.97`, efficiency factor `0.97`.
- Severe Degradation: capacity factor `0.85`, efficiency factor `0.92`.

Scenario preset examples:

- Solar curtailment: Mild Degradation with lower initial SoC.
- Evening scarcity: Base with higher initial SoC.
- High degradation: Severe Degradation with higher degradation cost.

Operational guardrails:

- Minimum SoC: `5%`.
- Maximum SoC: `95%`.
- Initial SoC input range: `5%` to `95%`.
- Max cycles per day in the backend battery request: `1.5`.

## Forecasts

The forecast chart shows:

- `Q10`: lower quantile price forecast.
- `Q50`: central price forecast used for optimization.
- `Q90`: upper quantile price forecast.
- Actual prices when available.

The API forecast window uses the latest 48 complete rows. The dashboard describes the optimization as a 15-minute dispatch plan, so users should interpret each row as a market time unit over the active horizon.

A wider Q10-Q90 band means higher forecast uncertainty.

## Dispatch Schedule

The optimizer produces:

- Charge MW.
- Discharge MW.
- Net MW.
- State of charge in MWh.
- Low-confidence idle flag.

Chart interpretation:

- Positive net MW means discharge.
- Negative net MW means charge.
- Grey bands indicate low-confidence market time units where the optimizer forced the battery idle.
- The SoC chart should remain inside the configured 5%-95% guardrails.

The optimizer is degradation-aware. It subtracts degradation cost from gross dispatch value.

The spread filter blocks low-confidence intervals. If the forecast spread is not large enough to compensate for degradation and efficiency losses, the optimizer keeps the battery idle.

## KPIs

Estimated Daily Profit:

- Net dispatch value after degradation cost.
- This is the main objective-style business KPI for the active horizon.

Gross Revenue:

- Revenue from forecasted price times net dispatch position before degradation cost.

Degradation:

- Estimated cost from battery throughput.
- Higher degradation cost makes the optimizer more selective.

Total Energy Traded:

- Total scheduled charge plus discharge movement over the active horizon.

Spread Captured:

- Gross revenue divided by traded energy, expressed in EUR/MWh.

Cycles Used:

- Equivalent full discharge cycles used during the horizon.

Idle Count:

- Number of market time units forced idle by the low-confidence spread filter.

## Feature Importance

The Feature Importance section ranks the top model inputs influencing the Q50 forecast. The backend returns the top 20 LightGBM features by gain importance.

Use feature importance to explain model drivers, not to claim causal proof.

## API Endpoints

Public health:

- `GET /health`: returns `{"ok": true}`.

Authentication:

- `POST /auth/login`: verifies username/password and creates a session, or returns MFA challenge when MFA is enabled.
- `POST /auth/mfa/verify`: verifies MFA challenge and creates a session.
- `GET /auth/me`: returns current user and CSRF token.
- `POST /auth/logout`: clears auth cookies.
- `GET /auth/mfa/setup`: provisions MFA secret and QR code.
- `GET /auth/mfa/status`: returns MFA enabled status.
- `POST /auth/mfa/enable`: enables MFA after TOTP verification.
- `POST /auth/mfa/disable`: disables MFA.

Dashboard data:

- `GET /status`: model readiness, model status, source, data rows, and model error.
- `GET /forecast`: timestamps, actual prices, Q10, Q50, Q90.
- `POST /optimize`: runs battery dispatch optimization for the selected assumptions.
- `GET /data-feeds`: data source health for HEnEx/ENTSO-E, Open-Meteo, IPTO, and TTF/EUA-style fuel context.
- `GET /feature-importance`: top Q50 feature importance values.

Admin/account:

- `GET /api-keys`: list API keys.
- `POST /api-keys`: create an API key.
- `DELETE /api-keys/{key_id}`: revoke an API key.
- `GET /audit`: query audit log entries.

Authorization rules:

- Viewer can access forecast/status-style read routes.
- Operator can run optimization.
- Admin can manage API keys and audit-related controls.

## Data Sources

The app can load market data from:

- Live APIs.
- Cached data.
- Demo synthetic data.

Data source labels in the UI:

- `Live API`.
- `Cache`.
- `Demo synthetic`.
- `Source pending`.

Data feed concepts:

- HEnEx / ENTSO-E DAM: day-ahead market clearing prices in EUR/MWh.
- Open-Meteo Weather: temperature, wind, irradiance for Greek zones.
- IPTO Load & RES: demand and renewable forecast signals.
- TTF / EUA Fuels: gas and carbon market context for SRMC.

## Model Lifecycle

At startup, the API:

1. Loads market data.
2. Engineers features.
3. Loads saved quantile models if available.
4. If saved models are missing, trains quantile models in the background.

Model statuses:

- `booting`: app startup is still in progress.
- `training`: model training is running.
- `ready`: models are available.
- `error`: startup or training failed.

If status says training, wait and refresh. If saved models exist in `models/`, startup should usually become ready quickly.

If the app cannot produce a forecast, possible reasons include:

- Market data is still loading.
- Models are still training.
- Model startup failed.
- Feature matrix is missing required model columns.
- There are not enough complete rows for a 48-row forecast window.

## Troubleshooting

Frontend loads but charts/buttons do not work:

1. Check API health:

   ```sh
   curl http://127.0.0.1:8000/health
   ```

2. Check logs:

   ```sh
   tail -n 80 .logs/api.log
   tail -n 80 .logs/frontend.log
   ```

3. Confirm the user is signed in.

4. Confirm the browser hostname matches the API hostname pattern.

Dashboard keeps loading:

- Check `/health`.
- Check `.logs/api.log`.
- Check `.logs/frontend.log`.
- Check model status.

Login fails too many times:

- The login route is rate limited.
- Wait for the rate-limit window to reset, then try again.

Groq chatbot does not respond:

- Confirm the app was started through `./start_all.sh`.
- Confirm the Next.js process can read `GROQ_API_KEY`.
- If an old server is already on port `3000`, start on a fresh port such as:

  ```sh
  FRONTEND_PORT=3002 ./start_all.sh
  ```

Route returns 404 for chat:

- Confirm `frontend/app/api/chat/route.ts` exists.
- Restart the Next.js dev server.

## Recommended Operating Review

Before using an output in a business discussion:

- Confirm the data source is expected.
- Confirm model status is ready.
- Check whether many intervals were forced idle.
- Compare at least two degradation scenarios.
- Verify SoC does not violate operational guardrails.
- Treat the output as decision support, not an automated trading instruction.

## What Not To Claim

The chatbot should not claim:

- The system executes live trades.
- The system controls physical assets automatically.
- The system has guaranteed profit.
- The system has formal compliance certification unless explicitly added later.
- All listed integrations are production live unless the UI/API status says they are available.
- Forecasts are certain.
- Feature importance proves causality.
- API keys, secrets, passwords, or MFA secrets can be recovered after creation.
