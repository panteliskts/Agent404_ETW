"use client";

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
import { getFeatureImportance, getForecast, getStatus, postOptimize } from "@/lib/api";
import type {
  FeatureImportanceResponse,
  ForecastResponse,
  OptimizeRequest,
  OptimizeResponse,
  Scenario,
  Source,
  StatusResponse
} from "@/types/api";

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
  primary: "#3b82f6",
  charge: "#22c55e",
  net: "#f97316",
  soc: "#14b8a6",
  idle: "rgba(156,163,175,0.35)",
  danger: "#ef4444",
  text: "#111827",
  actual: "#6b7280"
};

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

function asErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Unexpected error";
}

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
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (source === "cache") {
    return "border-yellow-200 bg-yellow-50 text-yellow-700";
  }
  if (source === "demo") {
    return "border-blue-200 bg-blue-50 text-blue-700";
  }
  return "border-slate-200 bg-slate-50 text-slate-600";
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
  const border = tone === "white" ? "border-white/40 border-t-white" : "border-blue-200 border-t-blue-600";
  return <span className={`inline-block h-4 w-4 animate-spin rounded-full border-2 ${border}`} />;
}

function MetricCard({
  label,
  value,
  tone = "default"
}: {
  label: string;
  value: string;
  tone?: "default" | "primary" | "warning";
}) {
  const valueClass =
    tone === "primary" ? "text-blue-600" : tone === "warning" ? "text-amber-600" : "text-slate-900";
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</div>
      <div className={`mt-3 text-2xl font-semibold ${valueClass}`}>{value}</div>
    </section>
  );
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

export default function DashboardPage() {
  const [params, setParams] = useState<OptimizeRequest>(DEFAULT_PARAMS);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [optimization, setOptimization] = useState<OptimizeResponse | null>(null);
  const [featureImportance, setFeatureImportance] = useState<FeatureImportanceResponse | null>(null);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const didBootstrap = useRef(false);
  const didOptimize = useRef(false);

  const source = optimization?.source ?? status?.source ?? "unknown";
  const modelReady = Boolean(status?.model_ready);
  const modelBusy = !modelReady && status?.model_status !== "error";
  const effectiveCapacity = params.capacity_mwh * DERATING[params.scenario].capFactor;

  const runOptimization = useCallback(async (nextParams: OptimizeRequest) => {
    setIsOptimizing(true);
    setError(null);
    try {
      const response = await postOptimize(nextParams);
      setOptimization(response);
      didOptimize.current = true;
    } catch (requestError) {
      setError(asErrorMessage(requestError));
    } finally {
      setIsOptimizing(false);
      setIsInitialLoading(false);
    }
  }, []);

  useEffect(() => {
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
          setError(response.model_error ?? "Model startup failed");
        }
        if (response.model_ready && timer) {
          clearInterval(timer);
        }
      } catch (requestError) {
        if (!cancelled) {
          setIsInitialLoading(false);
          setError(asErrorMessage(requestError));
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
  }, []);

  useEffect(() => {
    if (!modelReady || didBootstrap.current) {
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
          setError(asErrorMessage(requestError));
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
  }, [modelReady]);

  useEffect(() => {
    if (!modelReady || !didOptimize.current) {
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

  return (
    <div className="min-h-screen bg-[#f9fafb] text-[#111827]">
      <aside className="border-b border-slate-200 bg-white px-4 py-4 shadow-sm md:fixed md:inset-y-0 md:left-0 md:z-20 md:w-[260px] md:overflow-y-auto md:border-b-0 md:border-r md:px-5">
        <div className="flex items-start justify-between gap-3 md:block">
          <div>
            <h1 className="text-xl font-semibold text-slate-950">⚡ BESS Optimizer</h1>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${sourceClasses(source)}`}>
                {sourceLabel(source)}
              </span>
              <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-700">
                {modelBusy ? <Spinner /> : null}
                {modelReady ? "Model ready" : status?.model_status ?? "Booting"}
              </span>
            </div>
          </div>
          <div className="text-right text-xs text-slate-500 md:mt-3 md:text-left">
            {formatNumber(status?.data_rows ?? 0)} rows
          </div>
        </div>

        <div className="mt-6 space-y-6">
          <section>
            <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Battery Parameters</h2>
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
            <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Scenario</h2>
            <select
              className="mt-3 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-800 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:opacity-60"
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
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            type="button"
            disabled={!modelReady || isOptimizing}
            onClick={() => void runOptimization(params)}
          >
            {isOptimizing ? <Spinner tone="white" /> : null}
            Run Optimization
          </button>
        </div>
      </aside>

      <main className="px-4 py-5 md:pl-[292px] md:pr-8 md:pt-7">
        <div className="mx-auto max-w-7xl space-y-5">
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
                <MetricCard label="Net Profit" value={formatEuro(optimization?.kpis.net_profit_eur)} tone="primary" />
                <MetricCard label="Gross Revenue" value={formatEuro(optimization?.kpis.gross_revenue_eur)} />
                <MetricCard label="Degradation" value={formatEuro(optimization?.kpis.degradation_eur)} tone="warning" />
                <MetricCard label="Cycles Used" value={formatNumber(optimization?.kpis.cycles_used, 2)} />
              </section>

              <section className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm font-medium text-blue-900">
                Spread filter: {optimization?.kpis.idle_count}/{optimization?.kpis.total_mtus} MTUs marked low-confidence
                {" → "}forced idle. Threshold = degradation_cost + (1−√RTE) × mean_price
              </section>

              <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <h2 className="text-base font-semibold text-slate-950">Price Forecast — Q10 / Q50 / Q90</h2>
                  {isOptimizing ? <Spinner /> : null}
                </div>
                <div className="h-[340px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={forecastData} margin={{ top: 8, right: 20, left: 8, bottom: 8 }}>
                      <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" vertical={false} />
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

              <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <h2 className="mb-4 text-base font-semibold text-slate-950">
                  Dispatch Schedule <span className="font-normal text-slate-500">(grey = low-confidence idle)</span>
                </h2>
                <div className="h-[330px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={dispatchData} barCategoryGap="18%" margin={{ top: 8, right: 20, left: 8, bottom: 8 }}>
                      <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" vertical={false} />
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

              <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <h2 className="mb-4 text-base font-semibold text-slate-950">State of Charge Trajectory</h2>
                <div className="h-[310px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={dispatchData} margin={{ top: 8, right: 28, left: 8, bottom: 8 }}>
                      <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" vertical={false} />
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

              <details className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <summary className="cursor-pointer select-none text-base font-semibold text-slate-950">Feature Importance</summary>
                <div className="mt-4 h-[540px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart
                      data={featureData}
                      layout="vertical"
                      margin={{ top: 8, right: 24, left: 24, bottom: 8 }}
                    >
                      <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" horizontal={false} />
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
