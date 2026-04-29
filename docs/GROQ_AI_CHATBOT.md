# Groq AI Chatbot Widget

This project includes a native Next.js chatbot widget that floats in the bottom-right corner of the frontend and streams responses from Groq through the Vercel AI SDK.

## Files

| Purpose | File |
|---|---|
| Secure server route for Groq | `frontend/app/api/chat/route.ts` |
| Floating React widget | `frontend/components/chat-widget.tsx` |
| Global widget mount | `frontend/app/layout.tsx` |

## Dependencies

The frontend uses:

| Package | Purpose |
|---|---|
| `ai` | Vercel AI SDK core streaming APIs |
| `@ai-sdk/react` | `useChat` React hook |
| `@ai-sdk/groq` | Groq provider for the AI SDK |
| `lucide-react` | Widget icons |

## Doppler Secrets

Store the Groq API key in Doppler as:

```bash
GROQ_API_KEY=your_groq_api_key
```

Optional model override:

```bash
GROQ_MODEL=llama-3.1-8b-instant
```

If `GROQ_MODEL` is not set, the route defaults to `llama-3.1-8b-instant`.

## Running Locally

The Next.js server must be started through Doppler so `process.env.GROQ_API_KEY` is available to the API route:

```bash
cd /Users/pantelis/Desktop/ETW
./start_all.sh
```

If port `3000` is already in use:

```bash
FRONTEND_PORT=3002 ./start_all.sh
```

Open the matching local URL, for example:

```text
http://127.0.0.1:3002
```

## System Prompt

Paste the app documentation into the `SYSTEM_PROMPT` variable in:

```text
frontend/app/api/chat/route.ts
```

The route keeps the system prompt and Groq API key on the server. The browser only sends chat messages to `/api/chat`.

## Security Notes

- The Groq key is never exposed to the React client.
- The API route reads the key from server-side environment variables only.
- The route accepts same-origin requests only.
- Message history is trimmed before being sent to Groq.
- Only text message parts are forwarded to the model.

## Quick Verification

From `frontend/`, verify Doppler can inject the key without printing it:

```bash
doppler run -- node -e "console.log(Boolean(process.env.GROQ_API_KEY))"
```

Expected output:

```text
true
```

Then test the chat route:

```bash
curl -N -X POST http://localhost:3000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"id":"test","role":"user","parts":[{"type":"text","text":"Reply with OK."}]}]}'
```

If you started the app on another port, replace `3000` with that port.

## Troubleshooting

### `{"error":"Groq is not configured. Add GROQ_API_KEY to Doppler for this app."}`

The Next.js process cannot see `GROQ_API_KEY`.

Fix:

```bash
cd /Users/pantelis/Desktop/ETW
./start_all.sh
```

Do not use plain `npm run dev` unless `GROQ_API_KEY` is also present in the shell environment.

### Doppler Shows The Key But The App Still Fails

Check that the browser is opened to the Doppler-backed server. It is common to have an old plain Next.js server still running on `localhost:3000`.

Use a fresh port:

```bash
FRONTEND_PORT=3002 ./start_all.sh
```

Then open:

```text
http://127.0.0.1:3002
```

### Route Returns 404

Make sure this file exists:

```text
frontend/app/api/chat/route.ts
```

Then restart the Next.js dev server.
