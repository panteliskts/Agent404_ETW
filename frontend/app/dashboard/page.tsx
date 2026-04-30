"use client";

import type { FormEvent, ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import {
  getFeatureImportance,
  getForecast,
  getSession,
  getStatus,
  isUnauthorizedError,
  login as loginRequest,
  logout as logoutRequest,
  postOptimize,
  verifyMfa
} from "@/lib/api";
import { GENERIC_ERROR_MESSAGE, toUserErrorMessage } from "@/lib/errors";
import type {
  AuthUser,
  FeatureImportanceResponse,
  ForecastResponse,
  LoginResponse,
  OptimizeRequest,
  OptimizeResponse,
  Scenario,
  Source,
  StatusResponse
} from "@/types/api";

const SCENARIO_PRESETS: Record<string, Partial<OptimizeRequest>> = {
  "solar-curtailment": { scenario: "Mild Degradation", initial_soc_pct: 25 },
  "evening-scarcity": { scenario: "Base", initial_soc_pct: 70 },
  "high-degradation": { scenario: "Severe Degradation", degradation_eur_per_mwh: 12 }
};

const DEFAULT_PARAMS: OptimizeRequest = {
  capacity_mwh: 100,
  power_mw: 50,
  rte_pct: 90,
  degradation_eur_per_mwh: 5,
  initial_soc_pct: 50,
  scenario: "Base"
};

const SCENARIOS: Scenario[] = ["Base", "Mild Degradation", "Severe Degradation"];

const DERATING: Record<Scenario, { etaFactor: number; capFactor: number }> = {
  Base: { etaFactor: 1, capFactor: 1 },
  "Mild Degradation": { etaFactor: 0.97, capFactor: 0.97 },
  "Severe Degradation": { etaFactor: 0.92, capFactor: 0.85 }
};

const COLORS = {
  primary: "#0f766e",
  secondary: "#1f3a5f",
  charge: "#15803d",
  net: "#b45309",
  soc: "#0e7490",
  idle: "rgba(148,163,184,0.30)",
  danger: "#b91c1c",
  text: "#17202a",
  actual: "#52616f",
  grid: "#d8dee6"
};

const OPERATING_NOTES = [
  "Q10/Q50/Q90 curves show price uncertainty over the active dispatch horizon.",
  "Grey intervals are withheld from dispatch when the forecast spread does not compensate degradation risk.",
  "SoC guardrails keep the battery inside the configured 5%-95% operating envelope."
];

type ForecastPoint = {
  time: string;
  ts: number;
  actual: number | null;
  q10: number | null;
  q50: number | null;
  q90: number | null;
  spread: number | null;
};

type DispatchPoint = {
  time: string;
  ts: number;
  charge_mw: number;
  charge_negative_mw: number;
  discharge_mw: number;
  net_mw: number;
  soc_mwh: number;
  is_idle: boolean;
};

type FeaturePoint = {
  feature: string;
  gain: number;
};

type ChartTooltipProps = {
  active?: boolean;
  label?: string | number;
  payload?: Array<{
    color?: string;
    dataKey?: string;
    name?: string;
    value?: string | number | null;
    payload?: Record<string, unknown>;
  }>;
};

function formatEuro(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "€ 0";
  }
  return `€ ${new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value)}`;
}

function formatNumber(value?: number, digits = 0) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "0";
  }
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  }).format(value);
}

function formatTick(value: string | number) {
  const date = new Date(Number(value));
  const options: Intl.DateTimeFormatOptions =
    date.getHours() === 0
      ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }
      : { hour: "2-digit", minute: "2-digit", hour12: false };
  return new Intl.DateTimeFormat(undefined, options).format(date);
}

function formatTooltipTime(value: string | number | undefined) {
  if (value === undefined) {
    return "";
  }
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date(Number(value)));
}

function sourceClasses(source?: string) {
  if (source === "live") {
    return "border-emerald-200 bg-emerald-50 text-emerald-800";
  }
  if (source === "cache") {
    return "border-amber-200 bg-amber-50 text-amber-800";
  }
  if (source === "demo") {
    return "border-cyan-200 bg-cyan-50 text-cyan-800";
  }
  return "border-slate-200 bg-slate-50 text-slate-700";
}

function sourceLabel(source?: string) {
  const normalized = (source ?? "unknown") as Source;
  if (normalized === "live") {
    return "Live API";
  }
  if (normalized === "cache") {
    return "Cache";
  }
  if (normalized === "demo") {
    return "Demo synthetic";
  }
  return "Source pending";
}

function Spinner({ tone = "blue" }: { tone?: "blue" | "white" }) {
  const border = tone === "white" ? "border-white/40 border-t-white" : "border-teal-200 border-t-teal-700";
  return <span className={`inline-block h-4 w-4 animate-spin rounded-full border-2 ${border}`} />;
}

function MetricCard({
  label,
  value,
  helper,
  tone = "default"
}: {
  label: string;
  value: string;
  helper?: string;
  tone?: "default" | "primary" | "warning";
}) {
  const valueClass =
    tone === "primary" ? "text-teal-700" : tone === "warning" ? "text-amber-700" : "text-slate-950";
  return (
    <section className="enterprise-panel rounded-lg p-4">
      <div className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</div>
      <div className={`mt-3 text-2xl font-semibold ${valueClass}`}>{value}</div>
      {helper ? <div className="mt-2 text-xs font-medium text-slate-500">{helper}</div> : null}
    </section>
  );
}

function SectionHeader({
  title,
  eyebrow,
  action
}: {
  title: string;
  eyebrow?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        {eyebrow ? <div className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">{eyebrow}</div> : null}
        <h2 className="mt-1 text-base font-semibold text-slate-950">{title}</h2>
      </div>
      {action}
    </div>
  );
}

function StatusPill({
  children,
  tone = "neutral"
}: {
  children: ReactNode;
  tone?: "neutral" | "ready" | "warning";
}) {
  const toneClass =
    tone === "ready"
      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
      : tone === "warning"
        ? "border-amber-200 bg-amber-50 text-amber-800"
        : "border-slate-200 bg-white text-slate-700";
  return <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold ${toneClass}`}>{children}</span>;
}

function SliderControl({
  label,
  value,
  min,
  max,
  step,
  unit,
  onChange,
  disabled
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  onChange: (value: number) => void;
  disabled: boolean;
}) {
  return (
    <label className="block">
      <div className="mb-2 flex items-center justify-between gap-3 text-sm">
        <span className="font-medium text-slate-700">{label}</span>
        <span className="tabular-nums text-slate-900">
          {formatNumber(value, step < 1 ? 1 : 0)} {unit}
        </span>
      </div>
      <input
        className="range-input h-2 w-full cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function ForecastTooltip({ active, label, payload }: ChartTooltipProps) {
  if (!active || !payload?.length) {
    return null;
  }
  const point = payload[0]?.payload as ForecastPoint | undefined;
  return (
    <div className="chart-tooltip rounded-lg p-3 text-xs text-slate-700">
      <div className="mb-2 font-semibold text-slate-900">{formatTooltipTime(label)}</div>
      <div>Q10: {formatNumber(point?.q10 ?? undefined, 1)} €/MWh</div>
      <div>Q50: {formatNumber(point?.q50 ?? undefined, 1)} €/MWh</div>
      <div>Q90: {formatNumber(point?.q90 ?? undefined, 1)} €/MWh</div>
      <div>Actual: {formatNumber(point?.actual ?? undefined, 1)} €/MWh</div>
    </div>
  );
}

function DispatchTooltip({ active, label, payload }: ChartTooltipProps) {
  if (!active || !payload?.length) {
    return null;
  }
  const point = payload[0]?.payload as DispatchPoint | undefined;
  return (
    <div className="chart-tooltip max-w-xs rounded-lg p-3 text-xs text-slate-700">
      <div className="mb-2 font-semibold text-slate-900">{formatTooltipTime(label)}</div>
      <div>Charge: {formatNumber(point?.charge_mw, 1)} MW</div>
      <div>Discharge: {formatNumber(point?.discharge_mw, 1)} MW</div>
      <div>Net: {formatNumber(point?.net_mw, 1)} MW</div>
      {point?.is_idle ? (
        <div className="mt-2 rounded-md bg-slate-100 px-2 py-1 text-slate-700">
          Low-confidence MTU: spread below threshold, battery forced idle.
        </div>
      ) : null}
    </div>
  );
}

function SocTooltip({ active, label, payload }: ChartTooltipProps) {
  if (!active || !payload?.length) {
    return null;
  }
  const point = payload[0]?.payload as DispatchPoint | undefined;
  return (
    <div className="chart-tooltip rounded-lg p-3 text-xs text-slate-700">
      <div className="mb-2 font-semibold text-slate-900">{formatTooltipTime(label)}</div>
      <div>SoC: {formatNumber(point?.soc_mwh, 1)} MWh</div>
    </div>
  );
}

function SkeletonDashboard() {
  return (
    <div className="space-y-5">
      <div className="grid gap-4 lg:grid-cols-4">
        {[0, 1, 2, 3].map((item) => (
          <div key={item} className="h-28 animate-pulse rounded-lg border border-slate-200 bg-white" />
        ))}
      </div>
      <div className="h-14 animate-pulse rounded-lg bg-slate-200/80" />
      {[0, 1, 2].map((item) => (
        <div key={item} className="h-80 animate-pulse rounded-lg border border-slate-200 bg-white" />
      ))}
    </div>
  );
}

function LoginPage({
  error,
  isCheckingAuth,
  isSubmitting,
  mfaChallenge,
  onLogin,
  onVerifyMfa,
  onCancelMfa
}: {
  error: string | null;
  isCheckingAuth: boolean;
  isSubmitting: boolean;
  mfaChallenge: { mfa_token: string } | null;
  onLogin: (username: string, password: string) => Promise<void>;
  onVerifyMfa: (totp_code: string) => Promise<void>;
  onCancelMfa: () => void;
}) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onLogin(username, password);
  }

  async function handleMfaSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onVerifyMfa(totpCode);
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#f3f5f7] px-4 py-8 text-slate-950">
      <section className="grid w-full max-w-5xl overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xl lg:grid-cols-[1.05fr_0.95fr]">
        <div className="bg-[#17202a] p-8 text-white lg:p-10">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-teal-200">LogicVolt</div>
          <h1 className="mt-8 max-w-md text-4xl font-semibold leading-tight">Battery dispatch intelligence for energy storage operations.</h1>
          <p className="mt-5 max-w-md text-sm leading-6 text-slate-300">
            Secure access to forecast, optimization, degradation, and operating envelope views for BESS scenario planning.
          </p>
          <div className="mt-10 grid gap-3 text-sm text-slate-200">
            <div className="border-l-2 border-teal-300 pl-4">Forecast uncertainty and market price visibility</div>
            <div className="border-l-2 border-teal-300 pl-4">Constrained dispatch with degradation-aware idle periods</div>
            <div className="border-l-2 border-teal-300 pl-4">Scenario controls for energy transition investment reviews</div>
          </div>
        </div>
        <div className="p-6 sm:p-8 lg:p-10">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">Secure workspace</p>
          <h2 className="mt-3 text-2xl font-semibold text-slate-950">Sign in</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">Use your authorized application credentials to access the optimizer.</p>
        </div>

        {mfaChallenge ? (
          <form className="mt-6 space-y-4" onSubmit={(event) => void handleMfaSubmit(event)}>
            <div className="rounded-lg border border-teal-200 bg-teal-50 px-3 py-2 text-sm font-medium text-teal-800">
              Multi-factor required. Enter the 6-digit code from your authenticator.
            </div>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">TOTP code</span>
              <input
                className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-center text-lg tabular-nums tracking-[0.6em] text-slate-950 shadow-sm outline-none transition focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                autoComplete="one-time-code"
                inputMode="numeric"
                maxLength={6}
                value={totpCode}
                disabled={isSubmitting}
                onChange={(event) => setTotpCode(event.target.value.replace(/[^0-9]/g, ""))}
              />
            </label>

            {error ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
                {error}
              </div>
            ) : null}

            <button
              className="enterprise-button flex w-full items-center justify-center gap-2 rounded-lg px-4 py-3 text-sm font-semibold shadow-sm transition disabled:cursor-not-allowed"
              type="submit"
              disabled={isSubmitting || totpCode.length !== 6}
            >
              {isSubmitting ? <Spinner tone="white" /> : null}
              Verify and continue
            </button>
            <button
              className="block w-full text-center text-xs font-semibold text-slate-500 transition hover:text-slate-800"
              type="button"
              onClick={onCancelMfa}
            >
              Cancel
            </button>
          </form>
        ) : (
          <form className="mt-6 space-y-4" onSubmit={(event) => void handleSubmit(event)}>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Username</span>
              <input
                className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-950 shadow-sm outline-none transition focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                autoComplete="username"
                value={username}
                disabled={isCheckingAuth || isSubmitting}
                onChange={(event) => setUsername(event.target.value)}
              />
            </label>

            <label className="block">
              <span className="text-sm font-medium text-slate-700">Password</span>
              <input
                className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-950 shadow-sm outline-none transition focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                autoComplete="current-password"
                type="password"
                value={password}
                disabled={isCheckingAuth || isSubmitting}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>

            {error ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
                {error}
              </div>
            ) : null}

            <button
              className="enterprise-button flex w-full items-center justify-center gap-2 rounded-lg px-4 py-3 text-sm font-semibold shadow-sm transition disabled:cursor-not-allowed"
              type="submit"
              disabled={isCheckingAuth || isSubmitting}
            >
              {isCheckingAuth || isSubmitting ? <Spinner tone="white" /> : null}
              Sign in
            </button>
          </form>
        )}
        </div>
      </section>
    </main>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [selectedAsset, setSelectedAsset] = useState("Athens Battery 1");
  const [params, setParams] = useState<OptimizeRequest>(DEFAULT_PARAMS);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [optimization, setOptimization] = useState<OptimizeResponse | null>(null);
  const [featureImportance, setFeatureImportance] = useState<FeatureImportanceResponse | null>(null);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [mfaChallenge, setMfaChallenge] = useState<{ mfa_token: string } | null>(null);
  const didBootstrap = useRef(false);
  const didOptimize = useRef(false);

  const source = optimization?.source ?? status?.source ?? "unknown";
  const modelReady = Boolean(status?.model_ready);
  const modelBusy = !modelReady && status?.model_status !== "error";
  const effectiveCapacity = params.capacity_mwh * DERATING[params.scenario].capFactor;

  const resetDashboard = useCallback(() => {
    setParams(DEFAULT_PARAMS);
    setStatus(null);
    setForecast(null);
    setOptimization(null);
    setFeatureImportance(null);
    setIsInitialLoading(true);
    setIsOptimizing(false);
    setError(null);
    didBootstrap.current = false;
    didOptimize.current = false;
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function checkSession() {
      try {
        const response = await getSession();
        if (!cancelled) {
          setAuthUser(response.user);
        }
      } catch {
        if (!cancelled) {
          setAuthUser(null);
        }
      } finally {
        if (!cancelled) {
          setIsCheckingAuth(false);
        }
      }
    }

    void checkSession();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogin = useCallback(
    async (username: string, password: string) => {
      setIsLoggingIn(true);
      setLoginError(null);
      try {
        const response = await loginRequest({ username, password });
        if (response.mfa_required) {
          setMfaChallenge({ mfa_token: response.mfa_token });
          return;
        }
        resetDashboard();
        setMfaChallenge(null);
        setAuthUser(response.user);
      } catch (requestError) {
        setLoginError(toUserErrorMessage(requestError));
      } finally {
        setIsLoggingIn(false);
        setIsCheckingAuth(false);
      }
    },
    [resetDashboard]
  );

  const handleVerifyMfa = useCallback(
    async (totp_code: string) => {
      if (!mfaChallenge) return;
      setIsLoggingIn(true);
      setLoginError(null);
      try {
        const response = await verifyMfa({ mfa_token: mfaChallenge.mfa_token, totp_code });
        resetDashboard();
        setMfaChallenge(null);
        setAuthUser(response.user);
      } catch (requestError) {
        setLoginError(toUserErrorMessage(requestError));
      } finally {
        setIsLoggingIn(false);
        setIsCheckingAuth(false);
      }
    },
    [mfaChallenge, resetDashboard]
  );

  const handleCancelMfa = useCallback(() => {
    setMfaChallenge(null);
    setLoginError(null);
  }, []);

  const handleLogout = useCallback(async () => {
    setIsLoggingOut(true);
    try {
      await logoutRequest();
    } catch {
      // Clearing local state is still the right browser-side outcome.
    } finally {
      resetDashboard();
      setAuthUser(null);
      setMfaChallenge(null);
      setIsLoggingOut(false);
      router.replace("/login");
    }
  }, [resetDashboard, router]);

  const handleAuthExpired = useCallback(
    (message = "Please sign in again.") => {
      resetDashboard();
      setAuthUser(null);
      setLoginError(message);
      router.replace("/login?next=/dashboard");
    },
    [resetDashboard, router]
  );

  const runOptimization = useCallback(async (nextParams: OptimizeRequest) => {
    setIsOptimizing(true);
    setError(null);
    try {
      const response = await postOptimize(nextParams);
      setOptimization(response);
      didOptimize.current = true;
    } catch (requestError) {
      if (isUnauthorizedError(requestError)) {
        handleAuthExpired();
      } else {
        setError(toUserErrorMessage(requestError));
      }
    } finally {
      setIsOptimizing(false);
      setIsInitialLoading(false);
    }
  }, [handleAuthExpired]);

  useEffect(() => {
    if (!authUser) {
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;

    async function pollStatus() {
      try {
        const response = await getStatus();
        if (cancelled) {
          return;
        }
        setStatus(response);
        if (response.model_status === "error") {
          setIsInitialLoading(false);
          setError(GENERIC_ERROR_MESSAGE);
        }
        if (response.model_ready && timer) {
          clearInterval(timer);
        }
      } catch (requestError) {
        if (!cancelled) {
          if (isUnauthorizedError(requestError)) {
            handleAuthExpired();
          } else {
            setIsInitialLoading(false);
            setError(toUserErrorMessage(requestError));
          }
        }
      }
    }

    void pollStatus();
    timer = setInterval(() => {
      void pollStatus();
    }, 3000);

    return () => {
      cancelled = true;
      if (timer) {
        clearInterval(timer);
      }
    };
  }, [authUser, handleAuthExpired]);

  useEffect(() => {
    if (!authUser || !modelReady || didBootstrap.current) {
      return;
    }

    let cancelled = false;
    didBootstrap.current = true;
    setIsInitialLoading(true);
    setError(null);

    async function bootstrap() {
      try {
        const [forecastResponse, optimizeResponse, importanceResponse] = await Promise.all([
          getForecast(),
          postOptimize(DEFAULT_PARAMS),
          getFeatureImportance()
        ]);
        if (cancelled) {
          return;
        }
        setForecast(forecastResponse);
        setOptimization(optimizeResponse);
        setFeatureImportance(importanceResponse);
        didOptimize.current = true;
      } catch (requestError) {
        if (!cancelled) {
          if (isUnauthorizedError(requestError)) {
            handleAuthExpired();
          } else {
            setError(toUserErrorMessage(requestError));
          }
        }
      } finally {
        if (!cancelled) {
          setIsInitialLoading(false);
        }
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [authUser, handleAuthExpired, modelReady]);

  useEffect(() => {
    if (!authUser || !modelReady || !didOptimize.current) {
      return;
    }

    const timer = setTimeout(() => {
      void runOptimization(params);
    }, 400);

    return () => clearTimeout(timer);
  }, [
    params.capacity_mwh,
    params.power_mw,
    params.rte_pct,
    params.degradation_eur_per_mwh,
    params.initial_soc_pct,
    authUser,
    modelReady,
    runOptimization
  ]);

  const forecastData = useMemo<ForecastPoint[]>(() => {
    if (!forecast) {
      return [];
    }
    return forecast.timestamps.map((time, index) => {
      const q10 = forecast.q10[index];
      const q90 = forecast.q90[index];
      return {
        time,
        ts: new Date(time).getTime(),
        actual: forecast.actual[index],
        q10,
        q50: forecast.q50[index],
        q90,
        spread: q10 === null || q90 === null ? null : q90 - q10
      };
    });
  }, [forecast]);

  const dispatchData = useMemo<DispatchPoint[]>(() => {
    if (!optimization) {
      return [];
    }
    return optimization.schedule.map((row) => ({
      ...row,
      ts: new Date(row.time).getTime(),
      charge_negative_mw: -row.charge_mw
    }));
  }, [optimization]);

  const featureData = useMemo<FeaturePoint[]>(() => {
    if (!featureImportance) {
      return [];
    }
    return featureImportance.features.map((feature, index) => ({
      feature,
      gain: featureImportance.gain[index] ?? 0
    }));
  }, [featureImportance]);

  const intervalMs = dispatchData.length > 1 ? dispatchData[1].ts - dispatchData[0].ts : 60 * 60 * 1000;
  const totalEnergyTradedMwh = dispatchData.reduce(
    (total, point) => total + Math.abs(point.net_mw) * (intervalMs / (60 * 60 * 1000)),
    0
  );
  const spreadCaptured = totalEnergyTradedMwh > 0 ? (optimization?.kpis.gross_revenue_eur ?? 0) / totalEnergyTradedMwh : 0;
  const dispatchLimit = Math.max(
    10,
    Math.ceil(Math.max(params.power_mw, ...dispatchData.map((point) => Math.abs(point.net_mw))) / 10) * 10
  );
  const dashboardReady = Boolean(forecast && optimization);

  function updateParam<K extends keyof OptimizeRequest>(key: K, value: OptimizeRequest[K]) {
    setParams((current) => ({ ...current, [key]: value }));
  }

  function handleScenarioChange(value: Scenario) {
    const nextParams = { ...params, scenario: value };
    setParams(nextParams);
    if (modelReady && didOptimize.current) {
      void runOptimization(nextParams);
    }
  }

  function exportSchedule() {
    if (!dispatchData.length) {
      return;
    }

    const header = ["time", "charge_mw", "discharge_mw", "net_mw", "soc_mwh", "is_idle"];
    const rows = dispatchData.map((row) =>
      [row.time, row.charge_mw, row.discharge_mw, row.net_mw, row.soc_mwh, row.is_idle].join(",")
    );
    const blob = new Blob([[header.join(","), ...rows].join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${selectedAsset.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-dispatch-schedule.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  if (!authUser) {
    return (
      <LoginPage
        error={loginError}
        isCheckingAuth={isCheckingAuth}
        isSubmitting={isLoggingIn}
        mfaChallenge={mfaChallenge}
        onLogin={handleLogin}
        onVerifyMfa={handleVerifyMfa}
        onCancelMfa={handleCancelMfa}
      />
    );
  }

  return (
    <div className="min-h-screen bg-[#f3f5f7] text-[#17202a]">
      <aside className="sidebar-scroll border-b border-slate-200 bg-white px-4 py-4 shadow-sm md:fixed md:inset-y-0 md:left-0 md:z-20 md:w-[300px] md:overflow-y-auto md:border-b-0 md:border-r md:px-5">
        <div className="rounded-lg bg-[#17202a] p-5 text-white">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-teal-200">LogicVolt</div>
          <h1 className="mt-3 text-xl font-semibold leading-tight">Energy Storage Optimizer</h1>
          <p className="mt-3 text-xs leading-5 text-slate-300">Dispatch planning workspace for BESS forecast, risk, and revenue review.</p>
        </div>

        <nav className="mt-4 grid gap-2 text-sm font-semibold">
          <Link className="rounded-lg bg-slate-100 px-3 py-2 text-slate-950" href="/dashboard">
            Optimization Dashboard
          </Link>
          <Link className="rounded-lg px-3 py-2 text-slate-600 transition hover:bg-slate-100 hover:text-slate-950" href="/onboarding">
            Onboarding
          </Link>
          <Link className="rounded-lg px-3 py-2 text-slate-600 transition hover:bg-slate-100 hover:text-slate-950" href="/account">
            Account & API
          </Link>
        </nav>

        <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Session</div>
              <div className="mt-1 text-sm font-semibold text-slate-950">{authUser.username}</div>
            </div>
            <button
              className="text-xs font-semibold text-slate-600 transition hover:text-teal-700 disabled:cursor-not-allowed disabled:text-slate-300"
              type="button"
              disabled={isLoggingOut}
              onClick={() => void handleLogout()}
            >
              {isLoggingOut ? "Signing out" : "Sign out"}
            </button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${sourceClasses(source)}`}>
              {sourceLabel(source)}
            </span>
            <StatusPill tone={modelReady ? "ready" : "warning"}>
              {modelBusy ? <Spinner /> : null}
              {modelReady ? "Model ready" : status?.model_status ?? "Booting"}
            </StatusPill>
          </div>
          <div className="mt-3 text-xs font-medium text-slate-500">{formatNumber(status?.data_rows ?? 0)} market rows loaded</div>
        </div>

        <div className="mt-6 space-y-6">
          <section>
            <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Portfolio asset</h2>
            <select
              className="mt-3 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-800 shadow-sm outline-none transition focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
              value={selectedAsset}
              onChange={(event) => setSelectedAsset(event.target.value)}
            >
              <option>Athens Battery 1</option>
              <option>Thessaloniki Battery 2</option>
              <option>Patras Battery 3</option>
              <option>Fleet Aggregate</option>
            </select>
          </section>

          <section>
            <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Asset assumptions</h2>
            <div className="mt-4 space-y-4">
              <SliderControl
                label="Capacity"
                value={params.capacity_mwh}
                min={1}
                max={200}
                step={1}
                unit="MWh"
                disabled={!modelReady}
                onChange={(value) => updateParam("capacity_mwh", value)}
              />
              <SliderControl
                label="Power"
                value={params.power_mw}
                min={1}
                max={100}
                step={1}
                unit="MW"
                disabled={!modelReady}
                onChange={(value) => updateParam("power_mw", value)}
              />
              <SliderControl
                label="Round-trip efficiency"
                value={params.rte_pct}
                min={70}
                max={99}
                step={0.5}
                unit="%"
                disabled={!modelReady}
                onChange={(value) => updateParam("rte_pct", value)}
              />
              <SliderControl
                label="Degradation cost"
                value={params.degradation_eur_per_mwh}
                min={0.5}
                max={20}
                step={0.5}
                unit="€/MWh"
                disabled={!modelReady}
                onChange={(value) => updateParam("degradation_eur_per_mwh", value)}
              />
              <SliderControl
                label="Initial SoC"
                value={params.initial_soc_pct}
                min={5}
                max={95}
                step={5}
                unit="%"
                disabled={!modelReady}
                onChange={(value) => updateParam("initial_soc_pct", value)}
              />
            </div>
          </section>

          <section>
            <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Degradation scenario</h2>
            <select
              className="mt-3 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-800 shadow-sm outline-none transition focus:border-teal-600 focus:ring-2 focus:ring-teal-100 disabled:opacity-60"
              value={params.scenario}
              disabled={!modelReady}
              onChange={(event) => handleScenarioChange(event.target.value as Scenario)}
            >
              {SCENARIOS.map((scenario) => (
                <option key={scenario} value={scenario}>
                  {scenario}
                </option>
              ))}
            </select>
          </section>

          <button
            className="enterprise-button flex w-full items-center justify-center gap-2 rounded-lg px-4 py-3 text-sm font-semibold shadow-sm transition disabled:cursor-not-allowed"
            type="button"
            disabled={!modelReady || isOptimizing}
            onClick={() => void runOptimization(params)}
          >
            {isOptimizing ? <Spinner tone="white" /> : null}
            Run Optimization
          </button>
        </div>
      </aside>

      <main className="px-4 py-5 md:pl-[332px] md:pr-8 md:pt-7">
        <div className="mx-auto max-w-7xl space-y-5">
          <section className="enterprise-panel rounded-lg p-5 md:p-6">
            <div className="grid gap-5 lg:grid-cols-[1fr_360px] lg:items-start">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-700">BESS Dispatch Workspace</div>
                <h2 className="mt-2 text-3xl font-semibold leading-tight text-slate-950">Enterprise battery optimization and market-risk view</h2>
                <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
                  Review forecast uncertainty, degradation-aware dispatch, state-of-charge compliance, and operational KPIs from one controlled workspace.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">Horizon</div>
                  <div className="mt-1 font-semibold text-slate-950">{forecastData.length || 48} MTUs</div>
                </div>
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">Data source</div>
                  <div className="mt-1 font-semibold text-slate-950">{sourceLabel(source)}</div>
                </div>
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">Asset</div>
                  <div className="mt-1 font-semibold text-slate-950">{selectedAsset}</div>
                </div>
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">Scenario</div>
                  <div className="mt-1 font-semibold text-slate-950">{params.scenario}</div>
                </div>
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">Status</div>
                  <div className="mt-1 font-semibold text-slate-950">{modelReady ? "Ready" : status?.model_status ?? "Booting"}</div>
                </div>
              </div>
            </div>
          </section>

          <section className="enterprise-panel rounded-lg p-5">
            <SectionHeader title="Decision Checks" eyebrow="Before approving output" />
            <div className="grid gap-3 lg:grid-cols-3">
              {OPERATING_NOTES.map((note) => (
                <div key={note} className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-600">
                  {note}
                </div>
              ))}
            </div>
          </section>

          {error ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
              {error}
            </div>
          ) : null}

          {isInitialLoading || !dashboardReady ? (
            <SkeletonDashboard />
          ) : (
            <>
              <section className="grid gap-4 lg:grid-cols-4">
                <MetricCard
                  label="Daily Profit"
                  value={formatEuro(optimization?.kpis.daily_profit_eur ?? optimization?.kpis.net_profit_eur)}
                  helper="LogicVolt-optimized dispatch"
                  tone="primary"
                />
                <MetricCard
                  label="Annualized Revenue"
                  value={formatEuro(optimization?.kpis.annualized_revenue_eur)}
                  helper="Daily profit × 365"
                />
                <MetricCard
                  label="Uplift vs Naive"
                  value={`${formatEuro(optimization?.kpis.uplift_eur_day)} / day`}
                  helper={`${formatEuro(optimization?.kpis.annualized_uplift_eur)} / yr vs peak-shave heuristic`}
                  tone="warning"
                />
                <MetricCard
                  label="Walk-forward Capture"
                  value={`${formatNumber((optimization?.kpis.model_capture_ratio ?? 0.8743) * 100, 1)} %`}
                  helper="vs perfect foresight, 30-day mean"
                />
              </section>

              <section className="grid gap-4 lg:grid-cols-4">
                <MetricCard label="Total Energy Traded" value={`${formatNumber(totalEnergyTradedMwh, 1)} MWh`} helper="Absolute scheduled throughput" />
                <MetricCard
                  label="Spread Captured"
                  value={`${formatNumber(spreadCaptured, 1)} €/MWh`}
                  helper="Gross revenue per traded MWh"
                />
                <MetricCard label="Cycles Used" value={formatNumber(optimization?.kpis.cycles_used, 2)} helper="vs 1.5 / day cap" />
                <MetricCard
                  label="Naive Baseline"
                  value={`${formatEuro(optimization?.kpis.naive_daily_eur)} / day`}
                  helper="Charge 02-06, discharge 18-22 (no model)"
                />
              </section>

              <section className="rounded-lg border border-teal-100 bg-teal-50 px-4 py-3 text-sm font-medium text-teal-950">
                Spread filter: {optimization?.kpis.idle_count}/{optimization?.kpis.total_mtus} MTUs marked low-confidence
                {" → "}forced idle. Threshold = degradation_cost + (1−√RTE) × mean_price
              </section>

              <section className="enterprise-panel rounded-lg p-5">
                <SectionHeader
                  title="Price Forecast - Q10 / Q50 / Q90"
                  eyebrow="Market signal"
                  action={isOptimizing ? <Spinner /> : null}
                />
                <div className="h-[340px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={forecastData} margin={{ top: 8, right: 20, left: 8, bottom: 8 }}>
                      <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" vertical={false} />
                      <XAxis
                        dataKey="ts"
                        type="number"
                        scale="time"
                        domain={["dataMin", "dataMax"]}
                        tickFormatter={formatTick}
                        tick={{ fontSize: 12, fill: "#64748b" }}
                        minTickGap={28}
                      />
                      <YAxis
                        tick={{ fontSize: 12, fill: "#64748b" }}
                        tickFormatter={(value: number) => `${value}`}
                        label={{ value: "€/MWh", angle: -90, position: "insideLeft", fill: "#64748b" }}
                      />
                      <Tooltip content={<ForecastTooltip />} />
                      <Legend verticalAlign="bottom" height={28} />
                      <Area
                        dataKey="q10"
                        stackId="forecast-band"
                        stroke="transparent"
                        fill="transparent"
                        isAnimationActive={false}
                      />
                      <Area
                        dataKey="spread"
                        name="Q10-Q90 band"
                        stackId="forecast-band"
                        stroke="transparent"
                        fill={COLORS.primary}
                        fillOpacity={0.15}
                        isAnimationActive={false}
                      />
                      <Area
                        dataKey="q50"
                        name="Q50 forecast"
                        type="monotone"
                        stroke={COLORS.primary}
                        strokeWidth={2}
                        fill="transparent"
                        dot={false}
                        activeDot={{ r: 4 }}
                        isAnimationActive={false}
                      />
                      <Area
                        dataKey="actual"
                        name="Actual prices"
                        type="monotone"
                        stroke={COLORS.actual}
                        strokeWidth={1.5}
                        strokeDasharray="5 5"
                        fill="transparent"
                        dot={false}
                        isAnimationActive={false}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </section>

              <section className="enterprise-panel rounded-lg p-5">
                <SectionHeader
                  title="Dispatch Schedule"
                  eyebrow="Charge / discharge plan"
                  action={
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="text-xs font-semibold text-slate-500">Grey bands = low-confidence idle</span>
                      <button
                        className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 transition hover:border-teal-500 hover:text-teal-700"
                        type="button"
                        onClick={exportSchedule}
                      >
                        Export CSV
                      </button>
                    </div>
                  }
                />
                <div className="h-[330px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={dispatchData} barCategoryGap="18%" margin={{ top: 8, right: 20, left: 8, bottom: 8 }}>
                      <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" vertical={false} />
                      <XAxis
                        dataKey="ts"
                        type="number"
                        scale="time"
                        domain={["dataMin", "dataMax"]}
                        tickFormatter={formatTick}
                        tick={{ fontSize: 12, fill: "#64748b" }}
                        minTickGap={28}
                      />
                      <YAxis
                        domain={[-dispatchLimit, dispatchLimit]}
                        tick={{ fontSize: 12, fill: "#64748b" }}
                        label={{ value: "MW", angle: -90, position: "insideLeft", fill: "#64748b" }}
                      />
                      <Tooltip content={<DispatchTooltip />} />
                      <Legend verticalAlign="bottom" height={28} />
                      {dispatchData.map((point, index) =>
                        point.is_idle ? (
                          <ReferenceArea
                            key={point.time}
                            x1={point.ts}
                            x2={dispatchData[index + 1]?.ts ?? point.ts + intervalMs}
                            y1={-dispatchLimit}
                            y2={dispatchLimit}
                            fill={COLORS.idle}
                            strokeOpacity={0}
                          />
                        ) : null
                      )}
                      <Bar dataKey="charge_negative_mw" name="Charging" fill={COLORS.charge} radius={[3, 3, 0, 0]} />
                      <Bar dataKey="discharge_mw" name="Discharging" fill={COLORS.primary} radius={[3, 3, 0, 0]} />
                      <Area
                        dataKey="net_mw"
                        name="Net MW"
                        type="monotone"
                        stroke={COLORS.net}
                        strokeWidth={2}
                        fill="transparent"
                        dot={false}
                        isAnimationActive={false}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </section>

              <section className="enterprise-panel rounded-lg p-5">
                <SectionHeader title="State of Charge Trajectory" eyebrow="Operating envelope" />
                <div className="h-[310px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={dispatchData} margin={{ top: 8, right: 28, left: 8, bottom: 8 }}>
                      <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" vertical={false} />
                      <XAxis
                        dataKey="ts"
                        type="number"
                        scale="time"
                        domain={["dataMin", "dataMax"]}
                        tickFormatter={formatTick}
                        tick={{ fontSize: 12, fill: "#64748b" }}
                        minTickGap={28}
                      />
                      <YAxis
                        domain={[0, Math.max(effectiveCapacity, ...dispatchData.map((point) => point.soc_mwh)) * 1.05]}
                        tick={{ fontSize: 12, fill: "#64748b" }}
                        label={{ value: "MWh", angle: -90, position: "insideLeft", fill: "#64748b" }}
                      />
                      <Tooltip content={<SocTooltip />} />
                      <ReferenceLine
                        y={effectiveCapacity * 0.05}
                        stroke={COLORS.danger}
                        strokeDasharray="6 6"
                        label={{ value: "Min SoC (5%)", position: "insideBottomRight", fill: COLORS.danger, fontSize: 12 }}
                      />
                      <ReferenceLine
                        y={effectiveCapacity * 0.95}
                        stroke={COLORS.danger}
                        strokeDasharray="6 6"
                        label={{ value: "Max SoC (95%)", position: "insideTopRight", fill: COLORS.danger, fontSize: 12 }}
                      />
                      <Area
                        dataKey="soc_mwh"
                        name="SoC"
                        type="monotone"
                        stroke={COLORS.soc}
                        strokeWidth={2.5}
                        fill={COLORS.soc}
                        fillOpacity={0.18}
                        dot={false}
                        isAnimationActive={false}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </section>

              <details className="enterprise-panel rounded-lg p-5">
                <summary className="cursor-pointer select-none text-base font-semibold text-slate-950">Feature Importance</summary>
                <div className="mt-4 h-[540px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart
                      data={featureData}
                      layout="vertical"
                      margin={{ top: 8, right: 24, left: 24, bottom: 8 }}
                    >
                      <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" horizontal={false} />
                      <XAxis type="number" tick={{ fontSize: 12, fill: "#64748b" }} />
                      <YAxis
                        dataKey="feature"
                        type="category"
                        width={220}
                        tick={{ fontSize: 12, fill: "#475569" }}
                        interval={0}
                      />
                      <Tooltip
                        formatter={(value: unknown) => [formatNumber(Number(value), 0), "Gain"]}
                        labelStyle={{ color: COLORS.text, fontWeight: 600 }}
                      />
                      <Bar dataKey="gain" name="Gain" fill={COLORS.primary} radius={[0, 4, 4, 0]} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </details>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
