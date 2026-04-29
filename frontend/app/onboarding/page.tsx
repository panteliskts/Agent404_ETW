import Link from "next/link";

const dataFeeds = [
  { name: "HEnEx", detail: "Day-Ahead Market prices", status: "Connected" },
  { name: "IPTO", detail: "Grid load and RES forecast signals", status: "Ready" },
  { name: "Open-Meteo", detail: "Weather drivers for price forecasting", status: "Connected" },
  { name: "TTF / EEX", detail: "Gas and carbon market context", status: "Configured" }
];

const wizardSteps = [
  "Energy capacity in MWh",
  "Power rating in MW",
  "Round-trip efficiency",
  "Minimum and maximum SoC limits",
  "Cycle life and degradation cost",
  "Initial operating state of charge"
];

const workflow = [
  {
    title: "1. Plug in an asset",
    text: "Create a battery digital twin with hardware limits, degradation assumptions, and operating constraints."
  },
  {
    title: "2. Validate live context",
    text: "Check market, grid, weather, and fuel data feed health before trusting the schedule."
  },
  {
    title: "3. Run the optimizer",
    text: "Generate a 15-minute dispatch plan with charge, discharge, idle, and SoC instructions."
  },
  {
    title: "4. Export or integrate",
    text: "Download the schedule for reporting or use API keys to push instructions into downstream systems."
  }
];

export default function OnboardingPage() {
  return (
    <main className="min-h-screen bg-[#f3f5f7] px-4 py-6 text-[#17202a] md:px-8">
      <div className="mx-auto max-w-7xl space-y-5">
        <header className="enterprise-panel rounded-lg p-5 md:p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-700">Onboarding</div>
              <h1 className="mt-2 text-3xl font-semibold text-slate-950">Plug-and-play battery setup</h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
                Guide an energy company from asset definition to a live optimization schedule without code, notebooks, or manual data wrangling.
              </p>
            </div>
            <nav className="flex flex-wrap gap-2 text-sm font-semibold">
              <Link className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-700 transition hover:border-teal-500 hover:text-teal-700" href="/">
                Dashboard
              </Link>
              <Link className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-700 transition hover:border-teal-500 hover:text-teal-700" href="/account">
                Account & API
              </Link>
            </nav>
          </div>
        </header>

        <section className="grid gap-5 lg:grid-cols-[1fr_0.9fr]">
          <div className="enterprise-panel rounded-lg p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">Asset digital twin wizard</div>
            <h2 className="mt-2 text-xl font-semibold text-slate-950">Define the battery once, optimize immediately</h2>
            <div className="mt-5 grid gap-3 md:grid-cols-2">
              {wizardSteps.map((step) => (
                <div key={step} className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm font-semibold text-slate-700">
                  {step}
                </div>
              ))}
            </div>
          </div>

          <div className="enterprise-panel rounded-lg p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">Data integration hub</div>
            <h2 className="mt-2 text-xl font-semibold text-slate-950">Live context at a glance</h2>
            <div className="mt-5 space-y-3">
              {dataFeeds.map((feed) => (
                <div key={feed.name} className="flex items-center justify-between gap-4 rounded-lg border border-slate-200 bg-white p-4">
                  <div>
                    <div className="font-semibold text-slate-950">{feed.name}</div>
                    <div className="mt-1 text-sm text-slate-500">{feed.detail}</div>
                  </div>
                  <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">
                    {feed.status}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="enterprise-panel rounded-lg p-5">
          <div className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">SaaS operating flow</div>
          <div className="mt-5 grid gap-4 lg:grid-cols-4">
            {workflow.map((item) => (
              <div key={item.title} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                <div className="font-semibold text-slate-950">{item.title}</div>
                <p className="mt-2 text-sm leading-6 text-slate-600">{item.text}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="grid gap-5 lg:grid-cols-2">
          <div className="enterprise-panel rounded-lg p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">Scenario sandbox</div>
            <h2 className="mt-2 text-xl font-semibold text-slate-950">Test assumptions before committing</h2>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              Operators can simulate high solar curtailment, price collapse at noon, or elevated evening peaks, then compare how charge/discharge actions change.
            </p>
            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              {["Solar curtailment", "Evening scarcity", "High degradation cost"].map((scenario) => (
                <button
                  key={scenario}
                  className="rounded-lg border border-slate-300 bg-white px-3 py-3 text-sm font-semibold text-slate-700 transition hover:border-teal-500 hover:text-teal-700"
                  type="button"
                >
                  {scenario}
                </button>
              ))}
            </div>
          </div>

          <div className="enterprise-panel rounded-lg p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">Portfolio management</div>
            <h2 className="mt-2 text-xl font-semibold text-slate-950">Scale from one battery to a fleet</h2>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              The dashboard supports asset switching for named batteries and a fleet aggregate view, making the same workflow usable by developers, traders, and asset managers.
            </p>
            <div className="mt-5 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm font-semibold text-slate-700">
              Athens Battery 1 / Thessaloniki Battery 2 / Patras Battery 3 / Fleet Aggregate
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
