"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  createApiKey,
  createWebhook,
  deleteWebhook,
  disableMfa,
  enableMfa,
  getAuditLog,
  getMfaStatus,
  getSession,
  listApiKeys,
  listBillingKeys,
  listBillingTiers,
  listWebhooks,
  revokeApiKey,
  setKeyTier,
  startMfaSetup,
  testWebhook
} from "@/lib/api";
import { toUserErrorMessage } from "@/lib/errors";
import type {
  ApiKey,
  AuditEntry,
  AuthUser,
  BillingKey,
  BillingTier,
  MfaSetupResponse,
  Webhook
} from "@/types/api";

const ROLES: Array<{ value: "viewer" | "operator" | "admin"; label: string; helper: string }> = [
  { value: "viewer", label: "Viewer", helper: "Forecast + status only" },
  { value: "operator", label: "Operator", helper: "Run optimizations" },
  { value: "admin", label: "Admin", helper: "Full management access" }
];

function formatTimestamp(value: number | null | undefined) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value * 1000));
}

function actionTone(action: string) {
  if (action.includes("failed") || action.includes("revoked")) {
    return "text-amber-700";
  }
  if (action.includes("login") || action.includes("api_key_created") || action.includes("mfa_enabled")) {
    return "text-teal-700";
  }
  return "text-slate-700";
}

export default function AccountPage() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isCheckingSession, setIsCheckingSession] = useState(true);

  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [keysError, setKeysError] = useState<string | null>(null);
  const [isLoadingKeys, setIsLoadingKeys] = useState(true);
  const [keyLabel, setKeyLabel] = useState("");
  const [keyRole, setKeyRole] = useState<"viewer" | "operator" | "admin">("viewer");
  const [isCreatingKey, setIsCreatingKey] = useState(false);
  const [revealedKey, setRevealedKey] = useState<{ key: string; label: string } | null>(null);

  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [isLoadingAudit, setIsLoadingAudit] = useState(true);

  const [mfaEnabled, setMfaEnabled] = useState<boolean | null>(null);
  const [mfaSetup, setMfaSetup] = useState<MfaSetupResponse | null>(null);
  const [mfaCode, setMfaCode] = useState("");
  const [mfaError, setMfaError] = useState<string | null>(null);
  const [isMfaWorking, setIsMfaWorking] = useState(false);

  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [knownEvents, setKnownEvents] = useState<string[]>([]);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookLabel, setWebhookLabel] = useState("");
  const [webhookEvent, setWebhookEvent] = useState("optimize.completed");
  const [webhookError, setWebhookError] = useState<string | null>(null);
  const [revealedSecret, setRevealedSecret] = useState<{ secret: string; label: string } | null>(null);
  const [isWebhookBusy, setIsWebhookBusy] = useState(false);

  const [tiers, setTiers] = useState<BillingTier[]>([]);
  const [billingKeys, setBillingKeys] = useState<BillingKey[]>([]);
  const [billingError, setBillingError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const session = await getSession();
        if (!cancelled) setUser(session.user);
      } catch {
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setIsCheckingSession(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshKeys = useCallback(async () => {
    setIsLoadingKeys(true);
    try {
      const response = await listApiKeys();
      setApiKeys(response.keys);
      setKeysError(null);
    } catch (error) {
      setKeysError(toUserErrorMessage(error));
    } finally {
      setIsLoadingKeys(false);
    }
  }, []);

  const refreshAudit = useCallback(async () => {
    setIsLoadingAudit(true);
    try {
      const response = await getAuditLog({ limit: 50 });
      setAudit(response.entries);
      setAuditError(null);
    } catch (error) {
      setAuditError(toUserErrorMessage(error));
    } finally {
      setIsLoadingAudit(false);
    }
  }, []);

  const refreshMfa = useCallback(async () => {
    try {
      const status = await getMfaStatus();
      setMfaEnabled(status.enabled);
      setMfaError(null);
    } catch (error) {
      setMfaError(toUserErrorMessage(error));
    }
  }, []);

  const refreshWebhooks = useCallback(async () => {
    try {
      const response = await listWebhooks();
      setWebhooks(response.webhooks);
      setKnownEvents(response.known_events);
      setWebhookError(null);
    } catch (error) {
      setWebhookError(toUserErrorMessage(error));
    }
  }, []);

  const refreshBilling = useCallback(async () => {
    try {
      const [tiersResponse, keysResponse] = await Promise.all([
        listBillingTiers(),
        listBillingKeys()
      ]);
      setTiers(tiersResponse.tiers);
      setBillingKeys(keysResponse.keys);
      setBillingError(null);
    } catch (error) {
      setBillingError(toUserErrorMessage(error));
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    void refreshKeys();
    void refreshAudit();
    void refreshMfa();
    void refreshWebhooks();
    void refreshBilling();
  }, [user, refreshKeys, refreshAudit, refreshMfa, refreshWebhooks, refreshBilling]);

  async function handleCreateWebhook() {
    if (!webhookUrl.trim()) return;
    setIsWebhookBusy(true);
    setWebhookError(null);
    try {
      const response = await createWebhook({
        url: webhookUrl.trim(),
        events: [webhookEvent],
        label: webhookLabel.trim() || undefined
      });
      setRevealedSecret({ secret: response.secret, label: response.metadata.label || "(unnamed)" });
      setWebhookUrl("");
      setWebhookLabel("");
      await refreshWebhooks();
      await refreshAudit();
    } catch (error) {
      setWebhookError(toUserErrorMessage(error));
    } finally {
      setIsWebhookBusy(false);
    }
  }

  async function handleDeleteWebhook(id: string) {
    try {
      await deleteWebhook(id);
      await refreshWebhooks();
      await refreshAudit();
    } catch (error) {
      setWebhookError(toUserErrorMessage(error));
    }
  }

  async function handleTestWebhook(id: string) {
    try {
      await testWebhook(id);
      await refreshWebhooks();
    } catch (error) {
      setWebhookError(toUserErrorMessage(error));
    }
  }

  async function handleChangeTier(keyId: string, tier: BillingTier["name"]) {
    try {
      await setKeyTier(keyId, tier);
      await refreshBilling();
      await refreshAudit();
    } catch (error) {
      setBillingError(toUserErrorMessage(error));
    }
  }

  async function handleCreateKey() {
    setIsCreatingKey(true);
    try {
      const response = await createApiKey({ label: keyLabel || "(unnamed)", role: keyRole });
      setRevealedKey({ key: response.key, label: response.metadata.label });
      setKeyLabel("");
      setKeysError(null);
      await refreshKeys();
      await refreshAudit();
    } catch (error) {
      setKeysError(toUserErrorMessage(error));
    } finally {
      setIsCreatingKey(false);
    }
  }

  async function handleRevoke(id: string) {
    try {
      await revokeApiKey(id);
      await refreshKeys();
      await refreshAudit();
    } catch (error) {
      setKeysError(toUserErrorMessage(error));
    }
  }

  async function handleStartMfa() {
    setIsMfaWorking(true);
    setMfaError(null);
    try {
      const setup = await startMfaSetup();
      setMfaSetup(setup);
    } catch (error) {
      setMfaError(toUserErrorMessage(error));
    } finally {
      setIsMfaWorking(false);
    }
  }

  async function handleEnableMfa() {
    if (!mfaCode.trim()) return;
    setIsMfaWorking(true);
    setMfaError(null);
    try {
      await enableMfa(mfaCode.trim());
      setMfaSetup(null);
      setMfaCode("");
      await refreshMfa();
      await refreshAudit();
    } catch (error) {
      setMfaError(toUserErrorMessage(error));
    } finally {
      setIsMfaWorking(false);
    }
  }

  async function handleDisableMfa() {
    setIsMfaWorking(true);
    try {
      await disableMfa();
      await refreshMfa();
      await refreshAudit();
    } catch (error) {
      setMfaError(toUserErrorMessage(error));
    } finally {
      setIsMfaWorking(false);
    }
  }

  if (isCheckingSession) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f3f5f7] px-4 text-[#17202a]">
        <section className="enterprise-panel w-full max-w-md rounded-lg p-6 text-center">
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-700">Account</div>
          <h1 className="mt-2 text-2xl font-semibold text-slate-950">Checking session</h1>
          <p className="mt-3 text-sm leading-6 text-slate-600">Verifying your authenticated workspace access.</p>
        </section>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f3f5f7] px-4 text-[#17202a]">
        <section className="enterprise-panel w-full max-w-md rounded-lg p-6 text-center">
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-700">Protected page</div>
          <h1 className="mt-2 text-2xl font-semibold text-slate-950">Sign in required</h1>
          <p className="mt-3 text-sm leading-6 text-slate-600">Account and API controls are only available inside an authenticated LogicVolt session.</p>
          <Link className="enterprise-button mt-5 inline-flex rounded-lg px-4 py-3 text-sm font-semibold transition" href="/login?next=/account">
            Go to sign in
          </Link>
        </section>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#f3f5f7] px-4 py-6 text-[#17202a] md:px-8">
      <div className="mx-auto max-w-7xl space-y-5">
        <header className="enterprise-panel rounded-lg p-5 md:p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-700">Account</div>
              <h1 className="mt-2 text-3xl font-semibold text-slate-950">Account, API, and compliance controls</h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
                Manage access, integrations, audit trails, MFA, and API keys for downstream LogicVolt dispatch consumers.
              </p>
            </div>
            <nav className="flex flex-wrap gap-2 text-sm font-semibold">
              <Link className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-700 transition hover:border-teal-500 hover:text-teal-700" href="/dashboard">
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
            <h2 className="mt-2 text-xl font-semibold text-slate-950">
              {isCheckingSession ? "Checking session" : user?.username ?? "Not signed in"}
            </h2>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              Signed HttpOnly cookies, double-submit CSRF and per-IP rate limits protect your session.
            </p>
            {!user && !isCheckingSession ? (
              <Link className="mt-5 inline-flex rounded-lg bg-[#17202a] px-4 py-3 text-sm font-semibold text-white transition hover:bg-teal-700" href="/login?next=/account">
                Return to login
              </Link>
            ) : null}
          </div>

          <div className="enterprise-panel rounded-lg p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">Multi-factor authentication</div>
                <h2 className="mt-2 text-xl font-semibold text-slate-950">
                  TOTP {mfaEnabled === null ? "(checking)" : mfaEnabled ? "enabled" : "disabled"}
                </h2>
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  Adds a second factor (RFC 6238) to credential login. Compatible with Google Authenticator, 1Password, Authy.
                </p>
              </div>
              <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${mfaEnabled ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"}`}>
                {mfaEnabled ? "Active" : "Off"}
              </span>
            </div>

            {mfaError ? (
              <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700">{mfaError}</div>
            ) : null}

            {!mfaEnabled && !mfaSetup ? (
              <button
                className="enterprise-button mt-4 inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed"
                type="button"
                disabled={isMfaWorking || !user}
                onClick={() => void handleStartMfa()}
              >
                {isMfaWorking ? "Generating…" : "Set up authenticator"}
              </button>
            ) : null}

            {mfaSetup ? (
              <div className="mt-4 space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
                <p className="text-sm font-medium text-slate-700">Scan the QR with your authenticator app, then enter the 6-digit code below.</p>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                  {mfaSetup.qr_svg ? (
                    <div className="h-32 w-32 rounded-lg border border-slate-200 bg-white p-1" dangerouslySetInnerHTML={{ __html: mfaSetup.qr_svg }} />
                  ) : null}
                  <div className="text-xs font-mono text-slate-700">
                    Secret: <span className="break-all">{mfaSetup.secret}</span>
                  </div>
                </div>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <input
                    className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm tabular-nums tracking-[0.4em] outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                    placeholder="123456"
                    inputMode="numeric"
                    maxLength={6}
                    value={mfaCode}
                    onChange={(event) => setMfaCode(event.target.value.replace(/[^0-9]/g, ""))}
                  />
                  <button
                    className="enterprise-button rounded-lg px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed"
                    type="button"
                    disabled={isMfaWorking || mfaCode.length !== 6}
                    onClick={() => void handleEnableMfa()}
                  >
                    {isMfaWorking ? "Verifying…" : "Verify and enable"}
                  </button>
                  <button
                    className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-400"
                    type="button"
                    onClick={() => {
                      setMfaSetup(null);
                      setMfaCode("");
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : null}

            {mfaEnabled ? (
              <button
                className="mt-4 inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-amber-500 hover:text-amber-700 disabled:cursor-not-allowed"
                type="button"
                disabled={isMfaWorking}
                onClick={() => void handleDisableMfa()}
              >
                {isMfaWorking ? "Updating…" : "Disable MFA"}
              </button>
            ) : null}
          </div>
        </section>

        <section className="enterprise-panel rounded-lg p-5">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">API key management</div>
              <h2 className="mt-2 text-xl font-semibold text-slate-950">Programmatic access for downstream systems</h2>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                Argon2id-hashed API keys. The plaintext is shown <strong>once</strong> on creation — copy it immediately.
              </p>
            </div>
            <button
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-teal-500 hover:text-teal-700"
              type="button"
              onClick={() => void refreshKeys()}
            >
              {isLoadingKeys ? "Refreshing…" : "Refresh"}
            </button>
          </div>

          <div className="mt-5 grid gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4 sm:grid-cols-[1fr_180px_auto]">
            <input
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
              placeholder="Key label (e.g. SCADA prod)"
              value={keyLabel}
              onChange={(event) => setKeyLabel(event.target.value)}
            />
            <select
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
              value={keyRole}
              onChange={(event) => setKeyRole(event.target.value as "viewer" | "operator" | "admin")}
            >
              {ROLES.map((role) => (
                <option key={role.value} value={role.value}>
                  {role.label} — {role.helper}
                </option>
              ))}
            </select>
            <button
              className="enterprise-button rounded-lg px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed"
              type="button"
              disabled={isCreatingKey}
              onClick={() => void handleCreateKey()}
            >
              {isCreatingKey ? "Creating…" : "Generate key"}
            </button>
          </div>

          {keysError ? (
            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700">{keysError}</div>
          ) : null}

          {revealedKey ? (
            <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-[0.12em] text-amber-700">New API key — copy now</div>
              <div className="mt-2 text-sm text-amber-900">Label: {revealedKey.label}</div>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
                <code className="flex-1 break-all rounded-md bg-white px-3 py-2 text-xs text-amber-900 ring-1 ring-amber-200">{revealedKey.key}</code>
                <button
                  className="rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-semibold text-amber-700 transition hover:bg-amber-100"
                  type="button"
                  onClick={() => {
                    void navigator.clipboard?.writeText(revealedKey.key);
                  }}
                >
                  Copy
                </button>
                <button
                  className="rounded-lg bg-amber-700 px-3 py-2 text-xs font-semibold text-white transition hover:bg-amber-800"
                  type="button"
                  onClick={() => setRevealedKey(null)}
                >
                  Done
                </button>
              </div>
            </div>
          ) : null}

          <div className="mt-5 overflow-hidden rounded-lg border border-slate-200">
            <div className="grid grid-cols-[1.1fr_0.9fr_0.7fr_0.9fr_0.9fr_0.6fr] gap-3 bg-slate-100 px-4 py-2 text-xs font-semibold uppercase tracking-[0.1em] text-slate-500">
              <div>Prefix</div>
              <div>Label</div>
              <div>Role</div>
              <div>Created</div>
              <div>Last used</div>
              <div className="text-right">Action</div>
            </div>
            {apiKeys.length === 0 && !isLoadingKeys ? (
              <div className="px-4 py-6 text-center text-sm text-slate-500">No API keys yet.</div>
            ) : null}
            {apiKeys.map((key) => (
              <div
                key={key.id}
                className="grid grid-cols-[1.1fr_0.9fr_0.7fr_0.9fr_0.9fr_0.6fr] items-center gap-3 border-t border-slate-200 bg-white px-4 py-3 text-sm"
              >
                <code className="truncate font-mono text-slate-700">{key.prefix}</code>
                <div className="truncate text-slate-700">{key.label || "—"}</div>
                <div className="text-slate-700">{key.role}</div>
                <div className="text-slate-500">{formatTimestamp(key.created_at)}</div>
                <div className="text-slate-500">{formatTimestamp(key.last_used)}</div>
                <div className="text-right">
                  {key.revoked ? (
                    <span className="text-xs font-semibold text-slate-400">Revoked</span>
                  ) : (
                    <button
                      className="text-xs font-semibold text-amber-700 transition hover:text-amber-900"
                      type="button"
                      onClick={() => void handleRevoke(key.id)}
                    >
                      Revoke
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="enterprise-panel rounded-lg p-5">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">API plans &amp; usage</div>
              <h2 className="mt-2 text-xl font-semibold text-slate-950">Subscription tiers for downstream consumers</h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
                Attach any API key to a plan. Free is for evaluation; Pay-as-you-go gives full API access billed per optimize call with no monthly commitment; Pro and Enterprise add webhooks, higher rate limits, and volume quotas.
              </p>
            </div>
            <button
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-teal-500 hover:text-teal-700"
              type="button"
              onClick={() => void refreshBilling()}
            >
              Refresh
            </button>
          </div>

          {billingError ? (
            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700">{billingError}</div>
          ) : null}

          <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {tiers.map((tier) => {
              const isHighlighted = tier.name === "payg" || tier.name === "pro";
              return (
                <div
                  key={tier.name}
                  className={`relative flex flex-col rounded-lg border p-4 ${
                    tier.name === "payg"
                      ? "border-teal-400 bg-teal-50 ring-1 ring-teal-300"
                      : tier.name === "pro"
                        ? "border-slate-800 bg-slate-950 text-white"
                        : "border-slate-200 bg-white"
                  }`}
                >
                  {isHighlighted ? (
                    <span className={`absolute -top-2.5 left-4 rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                      tier.name === "payg" ? "bg-teal-600 text-white" : "bg-amber-400 text-slate-950"
                    }`}>
                      {tier.name === "payg" ? "API access" : "Most popular"}
                    </span>
                  ) : null}

                  <div className="flex items-start justify-between gap-2">
                    <div className={`text-sm font-semibold ${tier.name === "pro" ? "text-white" : "text-slate-950"}`}>{tier.label}</div>
                  </div>

                  <div className={`mt-2 text-2xl font-bold ${tier.name === "pro" ? "text-white" : "text-slate-950"}`}>
                    {tier.name === "payg" ? (
                      <>
                        €0<span className="text-xs font-medium text-slate-500"> / mo base</span>
                      </>
                    ) : (
                      <>
                        €{tier.price_eur_month.toLocaleString()}<span className={`text-xs font-medium ${tier.name === "pro" ? "text-slate-300" : "text-slate-500"}`}> / mo</span>
                      </>
                    )}
                  </div>

                  {tier.payg_price_eur_cents != null ? (
                    <div className="mt-1 text-xs font-semibold text-teal-700">
                      + €{(tier.payg_price_eur_cents / 100).toFixed(2)} per optimize call
                    </div>
                  ) : null}

                  <ul className={`mt-4 flex-1 space-y-1.5 text-xs leading-5 ${tier.name === "pro" ? "text-slate-300" : "text-slate-600"}`}>
                    <li className="flex items-center gap-1.5">
                      <span className={tier.can_use_optimize ? "text-teal-500" : "text-slate-300"}>
                        {tier.can_use_optimize ? "✓" : "—"}
                      </span>
                      Optimize &amp; forecast API
                    </li>
                    <li className="flex items-center gap-1.5">
                      <span className={tier.can_use_webhooks ? "text-teal-500" : "text-slate-300"}>
                        {tier.can_use_webhooks ? "✓" : "—"}
                      </span>
                      Webhook delivery
                    </li>
                    <li className="flex items-center gap-1.5">
                      <span className="text-teal-500">✓</span>
                      {tier.rate_limit} req / minute
                    </li>
                    <li className="flex items-center gap-1.5">
                      <span className="text-teal-500">✓</span>
                      {tier.monthly_call_quota === 0
                        ? "Unlimited calls (metered)"
                        : `${tier.monthly_call_quota.toLocaleString()} calls / month`}
                    </li>
                  </ul>
                </div>
              );
            })}
          </div>

          <div className="mt-5 overflow-hidden rounded-lg border border-slate-200">
            <div className="grid grid-cols-[1fr_0.7fr_0.9fr_0.9fr_0.9fr] gap-3 bg-slate-100 px-4 py-2 text-xs font-semibold uppercase tracking-[0.1em] text-slate-500">
              <div>Key</div>
              <div>Role</div>
              <div>Tier</div>
              <div>Usage (this month)</div>
              <div className="text-right">Change tier</div>
            </div>
            {billingKeys.length === 0 ? (
              <div className="px-4 py-6 text-center text-sm text-slate-500">No API keys with billing records yet.</div>
            ) : null}
            {billingKeys.map((key) => {
              const isPayg = key.tier === "payg";
              const usagePct = key.monthly_call_quota && !isPayg
                ? Math.min(100, (key.monthly_calls / key.monthly_call_quota) * 100)
                : 0;
              return (
                <div
                  key={key.key_id}
                  className="grid grid-cols-[1fr_0.7fr_0.9fr_0.9fr_0.9fr] items-center gap-3 border-t border-slate-200 bg-white px-4 py-3 text-sm"
                >
                  <div>
                    <div className="font-mono text-xs text-slate-700">{key.prefix}</div>
                    <div className="text-xs text-slate-500">{key.label || "—"}</div>
                  </div>
                  <div className="text-slate-700">{key.role}</div>
                  <div>
                    <span className={`rounded-full border px-2 py-1 text-xs font-semibold ${
                      key.tier === "payg"
                        ? "border-teal-300 bg-teal-50 text-teal-700"
                        : key.tier === "pro" || key.tier === "enterprise"
                          ? "border-slate-800 bg-slate-950 text-white"
                          : "border-slate-200 bg-slate-50 text-slate-700"
                    }`}>
                      {key.tier_label}
                    </span>
                  </div>
                  <div>
                    {isPayg ? (
                      <div className="text-xs text-slate-700">
                        {key.monthly_calls.toLocaleString()} calls
                        <span className="ml-1 text-slate-400">(metered)</span>
                      </div>
                    ) : (
                      <>
                        <div className="text-xs text-slate-700">
                          {key.monthly_calls.toLocaleString()} / {key.monthly_call_quota.toLocaleString()}
                        </div>
                        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
                          <div
                            className={`h-full ${usagePct > 90 ? "bg-amber-500" : "bg-teal-500"}`}
                            style={{ width: `${usagePct}%` }}
                          />
                        </div>
                      </>
                    )}
                  </div>
                  <div className="text-right">
                    <select
                      className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700 outline-none focus:border-teal-600"
                      value={key.tier}
                      onChange={(event) => void handleChangeTier(key.key_id, event.target.value as BillingTier["name"])}
                    >
                      {tiers.map((tier) => (
                        <option key={tier.name} value={tier.name}>
                          {tier.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="enterprise-panel rounded-lg p-5">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">Outbound webhooks</div>
              <h2 className="mt-2 text-xl font-semibold text-slate-950">Push optimization results into your stack</h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
                After every <code className="rounded bg-slate-100 px-1 text-xs">/optimize</code> call, LogicVolt POSTs the schedule + KPIs to every registered URL. Each delivery is signed with HMAC-SHA256 in <code className="rounded bg-slate-100 px-1 text-xs">X-LogicVolt-Signature</code>; verify with the secret shown once at registration.
              </p>
            </div>
            <button
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-teal-500 hover:text-teal-700"
              type="button"
              onClick={() => void refreshWebhooks()}
            >
              Refresh
            </button>
          </div>

          <div className="mt-5 grid gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4 sm:grid-cols-[1.5fr_1fr_180px_auto]">
            <input
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
              placeholder="https://your-app/webhooks/logicvolt"
              value={webhookUrl}
              onChange={(event) => setWebhookUrl(event.target.value)}
            />
            <input
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
              placeholder="Label (e.g. SCADA prod)"
              value={webhookLabel}
              onChange={(event) => setWebhookLabel(event.target.value)}
            />
            <select
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
              value={webhookEvent}
              onChange={(event) => setWebhookEvent(event.target.value)}
            >
              {(knownEvents.length ? knownEvents : ["optimize.completed"]).map((event) => (
                <option key={event} value={event}>
                  {event}
                </option>
              ))}
            </select>
            <button
              className="enterprise-button rounded-lg px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed"
              type="button"
              disabled={isWebhookBusy}
              onClick={() => void handleCreateWebhook()}
            >
              {isWebhookBusy ? "Saving…" : "Add webhook"}
            </button>
          </div>

          {webhookError ? (
            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700">{webhookError}</div>
          ) : null}

          {revealedSecret ? (
            <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-[0.12em] text-amber-700">New webhook secret — copy now</div>
              <div className="mt-2 text-sm text-amber-900">Label: {revealedSecret.label}</div>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
                <code className="flex-1 break-all rounded-md bg-white px-3 py-2 text-xs text-amber-900 ring-1 ring-amber-200">{revealedSecret.secret}</code>
                <button
                  className="rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-semibold text-amber-700 transition hover:bg-amber-100"
                  type="button"
                  onClick={() => {
                    void navigator.clipboard?.writeText(revealedSecret.secret);
                  }}
                >
                  Copy
                </button>
                <button
                  className="rounded-lg bg-amber-700 px-3 py-2 text-xs font-semibold text-white transition hover:bg-amber-800"
                  type="button"
                  onClick={() => setRevealedSecret(null)}
                >
                  Done
                </button>
              </div>
            </div>
          ) : null}

          <div className="mt-5 overflow-hidden rounded-lg border border-slate-200">
            <div className="grid grid-cols-[1.6fr_1fr_0.9fr_1fr_0.8fr] gap-3 bg-slate-100 px-4 py-2 text-xs font-semibold uppercase tracking-[0.1em] text-slate-500">
              <div>URL</div>
              <div>Events</div>
              <div>Last status</div>
              <div>Last delivery</div>
              <div className="text-right">Actions</div>
            </div>
            {webhooks.length === 0 ? (
              <div className="px-4 py-6 text-center text-sm text-slate-500">No webhook subscriptions yet.</div>
            ) : null}
            {webhooks.map((hook) => {
              const statusTone =
                hook.last_status && hook.last_status >= 200 && hook.last_status < 300
                  ? "text-teal-700"
                  : hook.last_status
                    ? "text-amber-700"
                    : "text-slate-500";
              return (
                <div
                  key={hook.id}
                  className="grid grid-cols-[1.6fr_1fr_0.9fr_1fr_0.8fr] items-center gap-3 border-t border-slate-200 bg-white px-4 py-3 text-sm"
                >
                  <div className="truncate">
                    <div className="truncate font-mono text-xs text-slate-700">{hook.url}</div>
                    <div className="text-xs text-slate-500">{hook.label || "—"}</div>
                  </div>
                  <div className="text-xs text-slate-700">{hook.events.join(", ")}</div>
                  <div className={`text-xs font-semibold ${statusTone}`}>
                    {hook.last_status ?? "—"}
                    {hook.last_error ? <div className="font-normal text-slate-500">{hook.last_error}</div> : null}
                  </div>
                  <div className="text-xs text-slate-500">{formatTimestamp(hook.last_delivered_at)}</div>
                  <div className="flex justify-end gap-2 text-xs font-semibold">
                    <button
                      className="rounded-md border border-slate-300 bg-white px-2 py-1 text-slate-700 transition hover:border-teal-500 hover:text-teal-700"
                      type="button"
                      onClick={() => void handleTestWebhook(hook.id)}
                    >
                      Send test
                    </button>
                    <button
                      className="text-amber-700 transition hover:text-amber-900"
                      type="button"
                      onClick={() => void handleDeleteWebhook(hook.id)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="enterprise-panel rounded-lg p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-teal-700">Audit log</div>
              <h2 className="mt-2 text-xl font-semibold text-slate-950">Tamper-resistant operational trail</h2>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                Each entry is appended via SQLite WORM authorizer that blocks UPDATE / DELETE at the driver level.
              </p>
            </div>
            <button
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-teal-500 hover:text-teal-700"
              type="button"
              onClick={() => void refreshAudit()}
            >
              {isLoadingAudit ? "Refreshing…" : "Refresh"}
            </button>
          </div>

          {auditError ? (
            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700">{auditError}</div>
          ) : null}

          <div className="mt-4 overflow-hidden rounded-lg border border-slate-200">
            <div className="grid grid-cols-[170px_1fr_140px_120px] gap-3 bg-slate-100 px-4 py-2 text-xs font-semibold uppercase tracking-[0.1em] text-slate-500">
              <div>Time</div>
              <div>Action</div>
              <div>User</div>
              <div>IP</div>
            </div>
            {audit.length === 0 && !isLoadingAudit ? (
              <div className="px-4 py-6 text-center text-sm text-slate-500">No audit entries yet.</div>
            ) : null}
            {audit.map((entry) => (
              <div
                key={entry.id}
                className="grid grid-cols-[170px_1fr_140px_120px] items-start gap-3 border-t border-slate-200 bg-white px-4 py-3 text-sm"
              >
                <div className="text-slate-500">{formatTimestamp(entry.timestamp)}</div>
                <div>
                  <div className={`font-semibold ${actionTone(entry.action)}`}>{entry.action}</div>
                  {entry.resource ? <div className="text-xs text-slate-500">{entry.resource}</div> : null}
                  {entry.details && Object.keys(entry.details).length ? (
                    <div className="mt-1 truncate text-xs text-slate-500">{JSON.stringify(entry.details)}</div>
                  ) : null}
                </div>
                <div className="text-slate-600">{entry.user}</div>
                <div className="font-mono text-xs text-slate-500">{entry.ip || "—"}</div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
