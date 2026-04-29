import type {
  FeatureImportanceResponse,
  ForecastResponse,
  OptimizeRequest,
  OptimizeResponse,
  StatusResponse
} from "@/types/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
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
    throw new Error(message);
  }

  return response.json() as Promise<T>;
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
