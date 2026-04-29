# METLEN BESS Optimizer Onboarding Guide

## Purpose

The METLEN BESS Optimizer is a secure decision-support workspace for reviewing battery energy storage dispatch scenarios. It combines market price forecasting, degradation-aware optimization, state-of-charge guardrails, and operational KPIs in one dashboard.

Use it to answer:

- What is the forecasted dispatch value over the active horizon?
- When should the battery charge, discharge, or remain idle?
- How sensitive is the schedule to battery degradation assumptions?
- Does the recommended schedule stay within the operating envelope?
- Which market and weather features are influencing the forecast?

## Start The Application

From the repository root:

```sh
cd /Users/pantelis/Desktop/ETW
./start_all.sh
```

Open:

```text
http://127.0.0.1:3000
```

Default local credentials:

```text
Username: admin
Password: admin
```

For a presentation or shared environment, configure a real password in `.env`:

```sh
APP_AUTH_USERNAME=admin
APP_AUTH_PASSWORD=use-a-real-password
APP_SECRET_KEY=use-a-long-random-secret
```

## First-Time User Workflow

1. Sign in.

   Use the authorized credentials. If the session expires, the app returns to the login page.

2. Confirm model readiness.

   In the left sidebar, check that the model status says `Model ready`. Also check the data source label and loaded row count.

3. Set asset assumptions.

   Adjust:

   - Capacity in MWh
   - Power in MW
   - Round-trip efficiency
   - Degradation cost
   - Initial state of charge

4. Select degradation scenario.

   Use `Base`, `Mild Degradation`, or `Severe Degradation` to compare how reduced capacity and efficiency affect dispatch value.

5. Review executive KPIs.

   The top KPI row summarizes:

   - Net Profit
   - Gross Revenue
   - Degradation Cost
   - Cycles Used

6. Review forecast uncertainty.

   The price forecast chart shows Q10, Q50, and Q90 forecasts. A wider band means higher uncertainty.

7. Review dispatch schedule.

   Positive MW means discharge. Negative MW means charge. Grey regions indicate low-confidence intervals where the optimizer forced the battery idle.

8. Confirm state-of-charge compliance.

   The SoC chart shows whether the recommended schedule stays between the 5% and 95% guardrails.

9. Inspect feature importance.

   Open `Feature Importance` to see which model features most influenced the Q50 forecast.

## How To Interpret The Dashboard

### Net Profit

Estimated dispatch value after degradation cost. This is the primary objective value for the active forecast horizon.

### Gross Revenue

Market spread capture before degradation cost.

### Degradation

Estimated cost from battery throughput. Higher degradation cost makes the optimizer more selective.

### Cycles Used

Equivalent full discharge cycles used during the horizon.

### Spread Filter

The spread filter blocks low-confidence intervals. If uncertainty is not large enough to compensate for degradation and efficiency losses, the optimizer keeps the battery idle.

### Price Forecast

- `Q50` is the central forecast used for optimization.
- `Q10-Q90` is the uncertainty band.
- `Actual prices` are shown when available for context.

### Dispatch Schedule

- Charging is shown below zero.
- Discharging is shown above zero.
- Net MW shows the combined power position.
- Grey bands are risk-controlled idle intervals.

### State Of Charge

The SoC trajectory should remain inside the min/max operating envelope. If it rides against limits for long periods, review capacity, power, and initial SoC assumptions.

## Recommended Operating Review

Before using an output in a business discussion:

- Confirm the data source is expected.
- Confirm model status is ready.
- Check whether many intervals were forced idle.
- Compare at least two degradation scenarios.
- Verify SoC does not violate operational guardrails.
- Treat the output as decision support, not an automated trading instruction.

## Security And Access

The app includes:

- Login-gated dashboard access
- HttpOnly signed session cookies
- CSRF protection for authenticated state-changing requests
- API and login rate limiting
- CORS restricted to configured frontend origins
- Trusted host checks
- Browser and API security headers

For shared or production-like use:

```sh
APP_COOKIE_SECURE=true
APP_ALLOWED_ORIGINS=https://your-frontend-domain
APP_ALLOWED_HOSTS=your-api-domain
```

Use HTTPS when `APP_COOKIE_SECURE=true`.

## Troubleshooting

### The frontend loads but says `Authentication required`

Hard-refresh the browser and sign in again. Also keep the hostname consistent:

- If you open `http://127.0.0.1:3000`, the API should be `http://127.0.0.1:8000`.
- If you open `http://localhost:3000`, the API should be `http://localhost:8000`.

The frontend now follows the browser hostname automatically unless `NEXT_PUBLIC_API_URL` is explicitly set.

### The dashboard keeps loading

Check the API:

```sh
curl http://127.0.0.1:8000/health
```

Then check logs:

```sh
tail -n 80 .logs/api.log
tail -n 80 .logs/frontend.log
```

### Model status says training

Wait for training to finish, then refresh. If saved models exist in `models/`, startup should normally become ready quickly.

### Login fails too many times

The login route is rate limited. Wait for the rate-limit window to reset, then try again.
