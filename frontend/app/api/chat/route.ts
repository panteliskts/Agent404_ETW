import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { createGroq } from "@ai-sdk/groq";
import { convertToModelMessages, streamText, type UIMessage } from "ai";
import { GENERIC_ERROR_MESSAGE } from "@/lib/errors";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 30;

const GROQ_MODEL = process.env.GROQ_MODEL ?? "llama-3.1-8b-instant";
const MAX_MESSAGES = 16;
const MAX_TEXT_LENGTH = 4_000;
const KNOWLEDGE_BASE_PATHS = [
  path.resolve(process.cwd(), "..", "docs", "CHATBOT_KNOWLEDGE_BASE.md"),
  path.resolve(process.cwd(), "docs", "CHATBOT_KNOWLEDGE_BASE.md")
];

// Allowed origins: same-host is always OK; additionally any origin explicitly
// listed in CHAT_ALLOWED_ORIGINS (comma-separated) or derivable from
// NEXT_PUBLIC_API_URL / APP_ALLOWED_ORIGINS (the FastAPI CORS list).
function buildAllowedOriginSet(): Set<string> {
  const raw = [
    process.env.CHAT_ALLOWED_ORIGINS ?? "",
    process.env.APP_ALLOWED_ORIGINS ?? "",
    process.env.NEXT_PUBLIC_API_URL ?? "",
  ]
    .join(",")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const hosts = new Set<string>();
  for (const entry of raw) {
    try {
      hosts.add(new URL(entry).host);
    } catch {
      // not a URL — ignore
    }
  }
  return hosts;
}

const EXTRA_ALLOWED_HOSTS = buildAllowedOriginSet();

function loadKnowledgeBase() {
  const knowledgePath = KNOWLEDGE_BASE_PATHS.find((candidate) => existsSync(candidate));
  if (!knowledgePath) {
    return "Knowledge base file not found. Ask the user to verify docs/CHATBOT_KNOWLEDGE_BASE.md exists.";
  }
  return readFileSync(knowledgePath, "utf8");
}

const SYSTEM_PROMPT = `
You are the in-app AI assistant for this product.

Answer clearly and concisely using the application documentation below as your primary source of truth.
If the documentation does not contain the answer, say what is missing and offer a practical next step.
Do not invent product capabilities, prices, contracts, operational limits, or compliance claims.

---
${loadKnowledgeBase()}
---
`.trim();

type ChatBody = {
  messages?: UIMessage[];
};

function jsonError(message: string, status: number) {
  if (status >= 500) {
    console.error(message);
  }
  return Response.json(
    { error: GENERIC_ERROR_MESSAGE },
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

  if (!origin) {
    return true; // server-to-server or same-origin fetch without origin header
  }

  let originHost: string;
  try {
    originHost = new URL(origin).host;
  } catch {
    return false;
  }

  // Same host as the Next.js server — always OK.
  if (host && originHost === host) {
    return true;
  }

  // Explicitly configured allowed origins (production domains, etc.).
  return EXTRA_ALLOWED_HOSTS.has(originHost);
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
      return GENERIC_ERROR_MESSAGE;
    }
  });
}
