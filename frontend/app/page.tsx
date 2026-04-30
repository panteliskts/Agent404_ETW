import Link from "next/link";
import {
  Activity,
  ArrowRight,
  BatteryCharging,
  ChartNoAxesCombined,
  Database,
  KeyRound,
  PlugZap,
  ShieldCheck,
  Zap,
  type LucideIcon
} from "lucide-react";

const loginHref = "/login?next=/dashboard";

const navItems = [
  { label: "Platform", href: "#platform" },
  { label: "Operations", href: "#operations" },
  { label: "Security", href: "#security" }
];

const proofPoints = [
  { label: "Dispatch horizon", value: "48 MTUs" },
  { label: "Schedule interval", value: "15 min" },
  { label: "SoC envelope", value: "5-95%" }
];

const platformCards: Array<{ icon: LucideIcon; title: string; text: string }> = [
  {
    icon: ChartNoAxesCombined,
    title: "Price uncertainty view",
    text: "Q10, Q50, and Q90 curves make market-risk visible before an operator approves the daily schedule."
  },
  {
    icon: BatteryCharging,
    title: "Battery-aware optimizer",
    text: "Dispatch is constrained by capacity, power, round-trip efficiency, degradation cost, and SoC guardrails."
  },
  {
    icon: Database,
    title: "Greek market data stack",
    text: "HEnEx DAM prices, IPTO load and RES signals, Open-Meteo weather, TTF gas, and EUA carbon context stay in one workflow."
  }
];

const operatingSteps = [
  {
    step: "01",
    title: "Model the asset",
    text: "Set MWh capacity, MW power, efficiency, cycle cost, degradation scenario, and initial state of charge."
  },
  {
    step: "02",
    title: "Validate the inputs",
    text: "Check feed source, market row counts, model status, and forecast uncertainty before acting."
  },
  {
    step: "03",
    title: "Approve dispatch",
    text: "Review charge, discharge, idle bands, state of charge, profit, spread capture, and cycles used."
  },
  {
    step: "04",
    title: "Operationalize access",
    text: "Use role-scoped API keys, MFA, and audit logs to control downstream integrations."
  }
];

const securityItems = [
  { icon: ShieldCheck, label: "HttpOnly signed sessions" },
  { icon: KeyRound, label: "Role-scoped API keys" },
  { icon: Activity, label: "Audit log for operator actions" }
];

function ProductPreview() {
  return (
    <div className="rounded-lg border border-white/15 bg-white/10 p-4 shadow-2xl backdrop-blur-sm">
      <div className="flex items-center justify-between border-b border-white/10 pb-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-100">BESS dispatch workspace</div>
          <div className="mt-1 text-sm font-semibold text-white">Athens Battery 1</div>
        </div>
        <span className="rounded-full border border-emerald-300/40 bg-emerald-300/20 px-3 py-1 text-[11px] font-semibold text-emerald-100">
          Model ready
        </span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["Net profit", "EUR 18.4k"],
          ["Energy traded", "126 MWh"],
          ["Spread", "34.8 EUR/MWh"],
          ["Cycles", "0.72"]
        ].map(([label, value]) => (
          <div key={label} className="rounded-lg border border-white/10 bg-white/10 p-3">
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-300">{label}</div>
            <div className="mt-3 text-lg font-semibold text-white">{value}</div>
          </div>
        ))}
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-lg border border-white/10 bg-slate-950/40 p-4">
          <div className="flex h-40 items-end gap-2 border-b border-l border-white/10 px-3 pb-3">
            {[34, 46, 38, 56, 48, 72, 58, 86, 62, 94, 70, 82, 52, 64].map((height, index) => (
              <span
                key={`${height}-${index}`}
                className={`w-full rounded-t-sm ${index % 3 === 0 ? "bg-amber-400/80" : "bg-teal-300/80"}`}
                style={{ height: `${height}%` }}
              />
            ))}
          </div>
          <div className="mt-3 flex items-center justify-between text-[11px] font-semibold text-slate-300">
            <span>Charge</span>
            <span>Discharge</span>
            <span>Idle filter</span>
          </div>
        </div>

        <div className="rounded-lg border border-white/10 bg-white/10 p-4">
          <div className="flex items-center justify-between">
            <BatteryCharging aria-hidden="true" className="h-5 w-5 text-teal-100" />
            <span className="text-xs font-semibold text-white">SoC 76%</span>
          </div>
          <div className="mt-5 h-3 rounded-full bg-white/20">
            <div className="h-3 w-3/4 rounded-full bg-teal-300" />
          </div>
          <div className="mt-6 space-y-2">
            {["HEnEx connected", "Open-Meteo connected", "Audit active"].map((item) => (
              <div key={item} className="flex items-center gap-2 text-xs font-medium text-slate-200">
                <span className="h-2 w-2 rounded-full bg-emerald-300" />
                {item}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function IconBadge({ icon: Icon }: { icon: LucideIcon }) {
  return (
    <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-teal-100 bg-teal-50 text-teal-700">
      <Icon aria-hidden="true" className="h-5 w-5" />
    </span>
  );
}

export default function LandingPage() {
  return (
    <main className="min-h-screen bg-[#f3f5f7] text-[#17202a]">
      <section className="relative overflow-hidden bg-[#17202a] text-white">
        <div aria-hidden="true" className="absolute inset-0 bg-[linear-gradient(90deg,rgba(15,118,110,0.18)_1px,transparent_1px),linear-gradient(180deg,rgba(82,97,111,0.2)_1px,transparent_1px)] bg-[size:56px_56px] opacity-40" />
        <div aria-hidden="true" className="absolute inset-0 bg-[radial-gradient(circle_at_78%_32%,rgba(15,118,110,0.36),transparent_35%),linear-gradient(90deg,rgba(23,32,42,0.98),rgba(23,32,42,0.74)_52%,rgba(23,32,42,0.9))]" />

        <header className="relative z-10 mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
          <Link className="flex items-center gap-3" href="/" aria-label="LogicVolt home">
            <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-teal-500 text-white shadow-lg shadow-teal-950/30">
              <Zap aria-hidden="true" className="h-5 w-5" />
            </span>
            <span className="text-base font-semibold tracking-[0.02em]">LogicVolt</span>
          </Link>
          <nav className="hidden items-center gap-6 text-sm font-semibold text-slate-200 md:flex">
            {navItems.map((item) => (
              <Link key={item.href} className="transition hover:text-white" href={item.href}>
                {item.label}
              </Link>
            ))}
          </nav>
          <Link
            className="inline-flex items-center gap-2 rounded-lg border border-white/20 bg-white/10 px-3 py-2 text-sm font-semibold text-white backdrop-blur-sm transition hover:border-teal-200 hover:bg-teal-500"
            href={loginHref}
          >
            Sign in
            <ArrowRight aria-hidden="true" className="h-4 w-4" />
          </Link>
        </header>

        <div className="relative z-10 mx-auto grid min-h-[720px] max-w-7xl gap-10 px-4 pb-20 pt-14 sm:px-6 lg:grid-cols-[0.88fr_1.12fr] lg:items-center lg:px-8">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-teal-200/30 bg-teal-100/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-teal-100">
              <PlugZap aria-hidden="true" className="h-3.5 w-3.5" />
              BESS revenue operations
            </div>
            <h1 className="mt-6 text-5xl font-semibold leading-[1.02] text-white sm:text-6xl">Dispatch batteries with market confidence.</h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-slate-300">
              LogicVolt helps storage operators turn Greek day-ahead price forecasts, uncertainty bands, and battery constraints into auditable charge and discharge schedules.
            </p>
            <div className="mt-7 flex flex-col gap-3 sm:flex-row">
              <Link
                className="enterprise-button inline-flex items-center justify-center gap-2 rounded-lg px-5 py-3 text-sm font-semibold shadow-xl shadow-slate-950/20 transition"
                href={loginHref}
              >
                Sign in to workspace
                <ArrowRight aria-hidden="true" className="h-4 w-4" />
              </Link>
              <Link
                className="inline-flex items-center justify-center rounded-lg border border-white/25 bg-white/10 px-5 py-3 text-sm font-semibold text-white backdrop-blur-sm transition hover:border-teal-200 hover:bg-white/20"
                href="#platform"
              >
                See platform
              </Link>
            </div>
            <div className="mt-8 grid max-w-xl grid-cols-3 gap-3">
              {proofPoints.map((item) => (
                <div key={item.label} className="rounded-lg border border-white/15 bg-white/10 p-3 backdrop-blur-sm">
                  <div className="text-lg font-semibold text-white">{item.value}</div>
                  <div className="mt-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-300">{item.label}</div>
                </div>
              ))}
            </div>
          </div>

          <ProductPreview />
        </div>
      </section>

      <section id="platform" className="border-b border-slate-200 bg-white px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-7xl">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl">
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-700">Platform</div>
              <h2 className="mt-2 text-3xl font-semibold leading-tight text-slate-950">Purpose-built for storage dispatch reviews.</h2>
              <p className="mt-3 text-sm leading-6 text-slate-600">
                The interface is designed for repeated operator workflows: scan model readiness, inspect risk, approve a schedule, and keep governance close.
              </p>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-semibold text-slate-700">
              Forecast, optimize, audit, integrate
            </div>
          </div>

          <div className="mt-8 grid gap-4 lg:grid-cols-3">
            {platformCards.map((item) => (
              <article key={item.title} className="enterprise-panel rounded-lg p-5">
                <IconBadge icon={item.icon} />
                <h3 className="mt-5 text-lg font-semibold text-slate-950">{item.title}</h3>
                <p className="mt-3 text-sm leading-6 text-slate-600">{item.text}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="operations" className="px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto grid max-w-7xl gap-8 lg:grid-cols-[0.72fr_1.28fr] lg:items-start">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-700">Operations</div>
            <h2 className="mt-2 text-3xl font-semibold leading-tight text-slate-950">A controlled path from asset settings to dispatch output.</h2>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              LogicVolt keeps the operational sequence explicit, so commercial teams and asset managers can review the same source of truth.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {operatingSteps.map((item) => (
              <article key={item.step} className="enterprise-panel rounded-lg p-5">
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-amber-700">{item.step}</div>
                <h3 className="mt-4 text-lg font-semibold text-slate-950">{item.title}</h3>
                <p className="mt-3 text-sm leading-6 text-slate-600">{item.text}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="security" className="bg-[#17202a] px-4 py-16 text-white sm:px-6 lg:px-8">
        <div className="mx-auto grid max-w-7xl gap-8 lg:grid-cols-[1fr_0.9fr] lg:items-center">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-200">Security</div>
            <h2 className="mt-2 text-3xl font-semibold leading-tight">Application pages stay behind authenticated access.</h2>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">
              Operational routes are gated before they render. Backend APIs still enforce signed sessions, CSRF protection, role checks, and rate limits.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
            {securityItems.map((item) => (
              <div key={item.label} className="flex items-center gap-3 rounded-lg border border-white/10 bg-white/10 p-4">
                <item.icon aria-hidden="true" className="h-5 w-5 text-teal-200" />
                <span className="text-sm font-semibold text-slate-100">{item.label}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="border-t border-slate-200 bg-white px-4 py-10 sm:px-6 lg:px-8">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-700">Operator access</div>
            <h2 className="mt-2 text-2xl font-semibold text-slate-950">Continue to the secure LogicVolt workspace.</h2>
          </div>
          <Link
            className="enterprise-button inline-flex items-center justify-center gap-2 rounded-lg px-5 py-3 text-sm font-semibold transition"
            href={loginHref}
          >
            Sign in
            <ArrowRight aria-hidden="true" className="h-4 w-4" />
          </Link>
        </div>
      </section>
    </main>
  );
}
