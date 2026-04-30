"use client";

import type { FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, LockKeyhole, ShieldCheck, Zap } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getSession, login as loginRequest, verifyMfa } from "@/lib/api";
import { toUserErrorMessage } from "@/lib/errors";

function safeNext(raw: string | null) {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) {
    return "/dashboard";
  }
  return raw;
}

function Spinner() {
  return <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />;
}

export default function LoginPage() {
  const router = useRouter();
  const [nextPath, setNextPath] = useState("/dashboard");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [mfaChallenge, setMfaChallenge] = useState<{ mfa_token: string } | null>(null);
  const [isCheckingSession, setIsCheckingSession] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requestedNext = safeNext(params.get("next"));
    setNextPath(requestedNext);

    let cancelled = false;
    async function checkSession() {
      try {
        await getSession();
        if (!cancelled) {
          router.replace(requestedNext);
        }
      } catch {
        if (!cancelled) {
          setIsCheckingSession(false);
        }
      }
    }

    void checkSession();
    return () => {
      cancelled = true;
    };
  }, [router]);

  const submitDisabled = useMemo(() => {
    if (isCheckingSession || isSubmitting) return true;
    if (mfaChallenge) return totpCode.length !== 6;
    return !username.trim() || !password;
  }, [isCheckingSession, isSubmitting, mfaChallenge, password, totpCode.length, username]);

  const handleLogin = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      setIsSubmitting(true);
      setError(null);
      try {
        const response = await loginRequest({ username: username.trim(), password });
        if (response.mfa_required) {
          setMfaChallenge({ mfa_token: response.mfa_token });
          setPassword("");
          return;
        }
        router.replace(nextPath);
      } catch (requestError) {
        setError(toUserErrorMessage(requestError));
      } finally {
        setIsSubmitting(false);
      }
    },
    [nextPath, password, router, username]
  );

  const handleMfa = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!mfaChallenge) return;

      setIsSubmitting(true);
      setError(null);
      try {
        await verifyMfa({ mfa_token: mfaChallenge.mfa_token, totp_code: totpCode });
        router.replace(nextPath);
      } catch (requestError) {
        setError(toUserErrorMessage(requestError));
      } finally {
        setIsSubmitting(false);
      }
    },
    [mfaChallenge, nextPath, router, totpCode]
  );

  return (
    <main className="min-h-screen bg-[#f3f5f7] text-[#17202a]">
      <div className="grid min-h-screen lg:grid-cols-[1fr_480px]">
        <section className="relative hidden overflow-hidden bg-[#17202a] p-10 text-white lg:block">
          <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(15,118,110,0.18)_1px,transparent_1px),linear-gradient(180deg,rgba(82,97,111,0.2)_1px,transparent_1px)] bg-[size:56px_56px] opacity-40" />
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_75%_30%,rgba(15,118,110,0.38),transparent_34%),linear-gradient(90deg,rgba(23,32,42,0.95),rgba(23,32,42,0.7))]" />
          <div className="relative z-10 flex min-h-full flex-col justify-between">
            <Link className="inline-flex items-center gap-3" href="/">
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-teal-500 text-white">
                <Zap aria-hidden="true" className="h-5 w-5" />
              </span>
              <span className="text-base font-semibold">LogicVolt</span>
            </Link>

            <div className="max-w-xl">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-teal-200">Secure operations console</div>
              <h1 className="mt-5 text-5xl font-semibold leading-tight">Sign in to approve storage dispatch decisions.</h1>
              <p className="mt-5 text-sm leading-6 text-slate-300">
                Access forecast uncertainty, degradation-aware schedules, SoC guardrails, audit trails, and API controls for BESS operations.
              </p>
            </div>

            <div className="grid gap-3 text-sm text-slate-200">
              {["HttpOnly session cookies", "TOTP multi-factor support", "Role-scoped API key management"].map((item) => (
                <div key={item} className="flex items-center gap-3 rounded-lg border border-white/10 bg-white/10 p-3">
                  <ShieldCheck aria-hidden="true" className="h-4 w-4 text-teal-200" />
                  <span className="font-medium">{item}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="flex min-h-screen items-center justify-center px-4 py-10 sm:px-6 lg:px-10">
          <div className="w-full max-w-md">
            <Link className="mb-8 inline-flex items-center gap-3 text-slate-950 lg:hidden" href="/">
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-[#17202a] text-white">
                <Zap aria-hidden="true" className="h-5 w-5" />
              </span>
              <span className="text-base font-semibold">LogicVolt</span>
            </Link>

            <div className="enterprise-panel rounded-lg p-6 shadow-xl sm:p-8">
              <div className="inline-flex h-11 w-11 items-center justify-center rounded-lg bg-teal-50 text-teal-700">
                <LockKeyhole aria-hidden="true" className="h-5 w-5" />
              </div>
              <div className="mt-5">
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-teal-700">Authorized access</div>
                <h1 className="mt-2 text-3xl font-semibold text-slate-950">{mfaChallenge ? "Verify MFA" : "Sign in"}</h1>
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  {mfaChallenge
                    ? "Enter the six-digit code from your authenticator app."
                    : "Use your LogicVolt operator credentials to continue."}
                </p>
              </div>

              {mfaChallenge ? (
                <form className="mt-6 space-y-4" onSubmit={(event) => void handleMfa(event)}>
                  <label className="block">
                    <span className="text-sm font-medium text-slate-700">Authenticator code</span>
                    <input
                      className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-3 text-center text-lg tabular-nums tracking-[0.6em] text-slate-950 shadow-sm outline-none transition focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                      autoComplete="one-time-code"
                      inputMode="numeric"
                      maxLength={6}
                      value={totpCode}
                      disabled={isSubmitting}
                      onChange={(event) => setTotpCode(event.target.value.replace(/[^0-9]/g, ""))}
                    />
                  </label>

                  {error ? <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700">{error}</div> : null}

                  <button className="enterprise-button flex w-full items-center justify-center gap-2 rounded-lg px-4 py-3 text-sm font-semibold transition disabled:cursor-not-allowed" type="submit" disabled={submitDisabled}>
                    {isSubmitting ? <Spinner /> : null}
                    Verify and continue
                    {!isSubmitting ? <ArrowRight aria-hidden="true" className="h-4 w-4" /> : null}
                  </button>
                  <button
                    className="w-full text-center text-xs font-semibold text-slate-500 transition hover:text-slate-800"
                    type="button"
                    onClick={() => {
                      setMfaChallenge(null);
                      setTotpCode("");
                      setError(null);
                    }}
                  >
                    Use a different account
                  </button>
                </form>
              ) : (
                <form className="mt-6 space-y-4" onSubmit={(event) => void handleLogin(event)}>
                  <label className="block">
                    <span className="text-sm font-medium text-slate-700">Username</span>
                    <input
                      className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-3 text-sm text-slate-950 shadow-sm outline-none transition focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                      autoComplete="username"
                      value={username}
                      disabled={isCheckingSession || isSubmitting}
                      onChange={(event) => setUsername(event.target.value)}
                    />
                  </label>

                  <label className="block">
                    <span className="text-sm font-medium text-slate-700">Password</span>
                    <input
                      className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-3 text-sm text-slate-950 shadow-sm outline-none transition focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                      autoComplete="current-password"
                      type="password"
                      value={password}
                      disabled={isCheckingSession || isSubmitting}
                      onChange={(event) => setPassword(event.target.value)}
                    />
                  </label>

                  {error ? <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700">{error}</div> : null}

                  <button className="enterprise-button flex w-full items-center justify-center gap-2 rounded-lg px-4 py-3 text-sm font-semibold transition disabled:cursor-not-allowed" type="submit" disabled={submitDisabled}>
                    {isCheckingSession || isSubmitting ? <Spinner /> : null}
                    Continue
                    {!isCheckingSession && !isSubmitting ? <ArrowRight aria-hidden="true" className="h-4 w-4" /> : null}
                  </button>
                </form>
              )}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
