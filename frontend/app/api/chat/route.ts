import { createGroq } from "@ai-sdk/groq";
import { convertToModelMessages, streamText, type UIMessage } from "ai";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

const GROQ_MODEL = process.env.GROQ_MODEL ?? "llama-3.3-70b-versatile";
const MAX_MESSAGES = 16;
const MAX_TEXT_LENGTH = 4_000;

export const SYSTEM_PROMPT = `
You are the in-app AI assistant for this product.

Answer clearly and concisely using the application documentation below as your primary source of truth.
If the documentation does not contain the answer, say what is missing and offer a practical next step.
Do not invent product capabilities, prices, contracts, operational limits, or compliance claims.

Paste your app documentation between the lines below.

---


---
`.trim();

type ChatBody = {
  messages?: UIMessage[];
};

function jsonError(message: string, status: number) {
  return Response.json(
    { error: message },
    {
      status,
      headers: {
        "Cache-Control": "no-store"
      }
    }
  );
}

function isAllowedOrigin(request: Request) {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");

  if (!origin || !host) {
    return true;
  }

  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

function sanitizeMessages(messages: UIMessage[]) {
  const safeMessages: UIMessage[] = [];

  for (const message of messages.slice(-MAX_MESSAGES)) {
    if (message.role !== "user" && message.role !== "assistant") {
      continue;
    }

    const textParts = message.parts
      .filter((part): part is Extract<UIMessage["parts"][number], { type: "text" }> => part.type === "text")
      .map((part) => ({
        type: "text" as const,
        text: part.text.slice(0, MAX_TEXT_LENGTH)
      }))
      .filter((part) => part.text.trim().length > 0);

    if (textParts.length > 0) {
      safeMessages.push({
        id: message.id,
        role: message.role,
        parts: textParts
      });
    }
  }

  return safeMessages;
}

export async function POST(request: Request) {
  if (!isAllowedOrigin(request)) {
    return jsonError("Cross-origin chat requests are not allowed.", 403);
  }

  const apiKey = process.env.GROQ_API_KEY ?? process.env.GROQ_API_TOKEN;
  if (!apiKey) {
    return jsonError("Groq is not configured. Add GROQ_API_KEY to Doppler for this app.", 500);
  }

  let body: ChatBody;
  try {
    body = (await request.json()) as ChatBody;
  } catch {
    return jsonError("Invalid JSON request body.", 400);
  }

  if (!Array.isArray(body.messages)) {
    return jsonError("Request body must include a messages array.", 400);
  }

  const messages = sanitizeMessages(body.messages);
  if (messages.length === 0) {
    return jsonError("Send at least one text message.", 400);
  }

  const groq = createGroq({ apiKey });
  const result = streamText({
    model: groq(GROQ_MODEL),
    system: SYSTEM_PROMPT,
    messages: await convertToModelMessages(messages),
    temperature: 0.2,
    maxOutputTokens: 700,
    abortSignal: request.signal
  });

  return result.toUIMessageStreamResponse({
    headers: {
      "Cache-Control": "no-store"
    },
    onError(error) {
      console.error("Groq chat route failed", error);
      return "The assistant could not respond right now.";
    }
  });
}
