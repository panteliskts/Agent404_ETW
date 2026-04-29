"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getSession } from "@/lib/api";
import type { AuthUser } from "@/types/api";

const auditRows = [
  { time: "09:15", event: "Schedule exported", actor: "admin", status: "Complete" },
  { time: "09:02", event: "Optimization run", actor: "admin", status: "Complete" },
  { time: "08:56", event: "Scenario changed", actor: "admin", status: "Recorded" }
];

const apiScopes = ["Read forecasts", "Run optimization", "Export schedules", "SCADA dispatch handoff"];

export default function AccountPage() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function loadSession() {
      try {
        const session = await getSession();
        if (!cancelled) {
          setUser(session.user);
        }
      } catch {
        if (!cancelled) {
          setUser(null);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadSession();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="min-h-screen bg-[#f3f5f7] px-4 py-6 text-[#17202a] md:px-8">
      <div className="mx-auto max-w-7xl space-y-5">
        <header className="enterprise-panel rounded-lg p-5 md:p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-700">Account</div>
              <h1 className="mt-2 text-3xl font-semibold text-slate-950">Account, API, and compliance controls</h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
                Manage access, integration readiness, API keys, audit trails, and export controls for enterprise deployment.
              </p>
            </div>
            <nav className="flex flex-wrap gap-2 text-sm font-semibold">
              <Link className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-700 transition hover:border-teal-500 hover:text-teal-700" href="/">
                Dashboard
              </Link>
              <Link className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-700 transition hover:border-teal-500 hover:text-teal-700" href="/onboarding">
                Onboarding
              </Link>
            </nav>
          </div>
        </header>

        <section className="grid gap-5 lg:grid-cols-[0.8fr_1.2fr]">
          <div className="enterprise-panel rounded-lg p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">User session</div>
            <h2 className="mt-2 text-xl font-semibold text-slate-950">{isLoading ? "Checking session" : user?.username ?? "Not signed in"}</h2>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              Sessions use signed HttpOnly cookies and CSRF protection for authenticated state-changing requests.
            </p>
            {!user && !isLoading ? (
              <Link className="mt-5 inline-flex rounded-lg bg-[#17202a] px-4 py-3 text-sm font-semibold text-white transition hover:bg-teal-700" href="/">
                Return to login
              </Link>
            ) : null}
          </div>

          <div className="enterprise-panel rounded-lg p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">API-first design</div>
            <h2 className="mt-2 text-xl font-semibold text-slate-950">Programmatic dispatch integration</h2>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              API keys demonstrate that schedules can be consumed by reporting systems, trading workflows, or a future SCADA/control integration.
            </p>
            <div className="mt-5 rounded-lg border border-slate-200 bg-slate-50 p-4 font-mono text-sm text-slate-700">
              bess_live_sk_************************9234
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {apiScopes.map((scope) => (
                <span key={scope} className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-700">
                  {scope}
                </span>
              ))}
            </div>
          </div>
        </section>

        <section className="grid gap-5 lg:grid-cols-2">
          <div className="enterprise-panel rounded-lg p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">Audit logs</div>
            <h2 className="mt-2 text-xl font-semibold text-slate-950">Operational traceability</h2>
            <div className="mt-5 overflow-hidden rounded-lg border border-slate-200">
              {auditRows.map((row) => (
                <div key={`${row.time}-${row.event}`} className="grid grid-cols-[80px_1fr_90px] gap-3 border-b border-slate-200 bg-white px-4 py-3 text-sm last:border-b-0">
                  <div className="font-semibold text-slate-500">{row.time}</div>
                  <div>
                    <div className="font-semibold text-slate-950">{row.event}</div>
                    <div className="text-slate-500">{row.actor}</div>
                  </div>
                  <div className="text-right font-semibold text-teal-700">{row.status}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="enterprise-panel rounded-lg p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">Export controls</div>
            <h2 className="mt-2 text-xl font-semibold text-slate-950">Compliance-ready schedule outputs</h2>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              The optimization dashboard exports the active dispatch schedule to CSV. Enterprise deployments can add JSON, signed approvals, and automated delivery.
            </p>
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                <div className="text-sm font-semibold text-slate-950">CSV</div>
                <div className="mt-1 text-sm text-slate-500">96 interval reporting</div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                <div className="text-sm font-semibold text-slate-950">JSON</div>
                <div className="mt-1 text-sm text-slate-500">API handoff format</div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
