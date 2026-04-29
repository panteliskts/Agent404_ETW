import type {
  AuthSessionResponse,
  FeatureImportanceResponse,
  ForecastResponse,
  LoginRequest,
  LoginResponse,
  LogoutResponse,
  OptimizeRequest,
  OptimizeResponse,
  StatusResponse
} from "@/types/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const CSRF_COOKIE = "bess_csrf";
const CSRF_HEADER = "X-CSRF-Token";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
let csrfToken = "";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function isUnauthorizedError(error: unknown) {
  return error instanceof ApiError && error.status === 401;
}

function apiBase() {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL;
  }
  if (typeof window !== "undefined") {
    return `http://${window.location.hostname}:8000`;
  }
  return API_BASE;
}

function readCookie(name: string) {
  if (typeof document === "undefined") {
    return "";
  }

  const prefix = `${name}=`;
  return (
    document.cookie
      .split(";")
      .map((cookie) => cookie.trim())
      .find((cookie) => cookie.startsWith(prefix))
      ?.slice(prefix.length) ?? ""
  );
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers = new Headers(init?.headers);

  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const activeCsrfToken = csrfToken || readCookie(CSRF_COOKIE);
  if (UNSAFE_METHODS.has(method) && activeCsrfToken && !headers.has(CSRF_HEADER)) {
    headers.set(CSRF_HEADER, activeCsrfToken);
  }

  const response = await fetch(`${apiBase()}${path}`, {
    ...init,
    credentials: "include",
    headers
  });

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        message = body.detail;
      }
    } catch {
      // Keep the HTTP status message.
    }
    throw new ApiError(message, response.status);
  }

  return response.json() as Promise<T>;
}

export function login(payload: LoginRequest) {
  return requestJson<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload)
  }).then((response) => {
    csrfToken = response.csrf_token;
    return response;
  });
}

export function logout() {
  return requestJson<LogoutResponse>("/auth/logout", { method: "POST" }).finally(() => {
    csrfToken = "";
  });
}

export function getSession() {
  return requestJson<AuthSessionResponse>("/auth/me", { cache: "no-store" }).then((response) => {
    csrfToken = response.csrf_token ?? csrfToken;
    return response;
  });
}

export function getStatus() {
  return requestJson<StatusResponse>("/status", { cache: "no-store" });
}

export function getForecast() {
  return requestJson<ForecastResponse>("/forecast", { cache: "no-store" });
}

export function postOptimize(payload: OptimizeRequest) {
  return requestJson<OptimizeResponse>("/optimize", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getFeatureImportance() {
  return requestJson<FeatureImportanceResponse>("/feature-importance", { cache: "no-store" });
}
