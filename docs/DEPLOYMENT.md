# LogicVolt Deployment

This repo deploys as two services:

- Vercel: Next.js frontend from `frontend/`
- Render: FastAPI backend from the repo root

## Vercel

Create a Vercel project for the frontend with these settings:

```text
Framework Preset: Next.js
Root Directory: frontend
Install Command: npm install
Build Command: npm run build
Output Directory: .next
```

Set these Vercel environment variables:

```text
INTERNAL_API_URL=https://YOUR_RENDER_SERVICE.onrender.com
GROQ_API_KEY=...
GROQ_MODEL=llama-3.1-8b-instant
```

`GROQ_MODEL` is optional. The app uses `llama-3.1-8b-instant` when it is not set.

Do not set `NEXT_PUBLIC_API_URL` for the normal Vercel + Render deployment. Leaving it unset makes the browser call same-origin Vercel paths, and Next.js rewrites those requests to Render with `INTERNAL_API_URL`. This keeps the auth cookies working on the Vercel domain.

## Render

Create a Render Blueprint from `render.yaml`, or create a Web Service manually:

```text
Runtime: Python
Root Directory: repo root
Build Command: pip install -r requirements.txt -r api/requirements.txt
Start Command: uvicorn api.main:app --host 0.0.0.0 --port $PORT
Health Check Path: /health
```

Set these Render environment variables after you know the Vercel and Render URLs:

```text
APP_COOKIE_SECURE=true
APP_ALLOWED_ORIGINS=https://YOUR_VERCEL_PROJECT.vercel.app
APP_ALLOWED_HOSTS=YOUR_RENDER_SERVICE.onrender.com
APP_PUBLIC_URL=https://YOUR_RENDER_SERVICE.onrender.com
APP_FRONTEND_URL=https://YOUR_VERCEL_PROJECT.vercel.app
APP_AUTH_USERNAME=...
APP_AUTH_PASSWORD=...
APP_SECRET_KEY=...
APP_ENCRYPTION_KEY=...
ENTSOE_API_KEY=...
```

`ENTSOE_API_KEY` is optional for demo/cache data, but needed for live ENTSO-E data.

Use comma-separated values for `APP_ALLOWED_ORIGINS` and `APP_ALLOWED_HOSTS` if you have production and preview domains. For example:

```text
APP_ALLOWED_ORIGINS=https://logicvolt.com,https://logicvolt.vercel.app
APP_ALLOWED_HOSTS=logicvolt-api.onrender.com
```

## Deployment Order

1. Deploy the Render API first.
2. Put the Render URL in Vercel as `INTERNAL_API_URL`.
3. Deploy the Vercel frontend.
4. Put the Vercel URL in Render as `APP_ALLOWED_ORIGINS` and `APP_FRONTEND_URL`.
5. Redeploy Render so CORS, cookies, and redirects use the final frontend URL.
