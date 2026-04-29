export type Source = "live" | "cache" | "demo" | "unknown";

export type Scenario = "Base" | "Mild Degradation" | "Severe Degradation";

export type AuthUser = {
  username: string;
};

export type AuthSessionResponse = {
  user: AuthUser;
  csrf_token?: string;
};

export type LoginRequest = {
  username: string;
  password: string;
};

export type LoginResponse = AuthSessionResponse & {
  csrf_token: string;
  session_expires_at: number;
};

export type LogoutResponse = {
  ok: boolean;
};

export type StatusResponse = {
  model_ready: boolean;
  model_status: "booting" | "training" | "ready" | "error" | string;
  model_error?: string | null;
  source: Source | string;
  data_rows: number;
};

export type ForecastResponse = {
  timestamps: string[];
  actual: Array<number | null>;
  q10: Array<number | null>;
  q50: Array<number | null>;
  q90: Array<number | null>;
};

export type OptimizeRequest = {
  capacity_mwh: number;
  power_mw: number;
  rte_pct: number;
  degradation_eur_per_mwh: number;
  initial_soc_pct: number;
  scenario: Scenario;
};

export type Kpis = {
  net_profit_eur: number;
  gross_revenue_eur: number;
  degradation_eur: number;
  cycles_used: number;
  idle_count: number;
  total_mtus: number;
};

export type ScheduleRow = {
  time: string;
  charge_mw: number;
  discharge_mw: number;
  net_mw: number;
  soc_mwh: number;
  is_idle: boolean;
};

export type OptimizeResponse = {
  kpis: Kpis;
  schedule: ScheduleRow[];
  source: Source | string;
};

export type FeatureImportanceResponse = {
  features: string[];
  gain: number[];
};
