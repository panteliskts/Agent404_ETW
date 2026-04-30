import Link from "next/link";

const TIERS = [
  {
    name: "Free",
    price: "€0",
    period: "/ month",
    badge: null,
    badgeStyle: "",
    cardStyle: "border-slate-200 bg-white",
    headingStyle: "text-slate-950",
    subStyle: "text-slate-500",
    bodyStyle: "text-slate-600",
    cta: "Get started",
    ctaStyle: "border border-slate-300 bg-white text-slate-700 hover:border-teal-500 hover:text-teal-700",
    href: "/login",
    features: [
      { label: "Forecast & status endpoints", included: true },
      { label: "500 API calls / month", included: true },
      { label: "10 requests / minute", included: true },
      { label: "Optimize endpoint", included: false },
      { label: "Webhook delivery", included: false },
      { label: "MFA & audit log", included: true },
    ],
    footnote: null,
  },
  {
    name: "Pay-as-you-go",
    price: "€0",
    period: "/ month base",
    badge: "API access",
    badgeStyle: "bg-teal-600 text-white",
    cardStyle: "border-teal-400 bg-teal-50 ring-1 ring-teal-300",
    headingStyle: "text-slate-950",
    subStyle: "text-teal-700",
    bodyStyle: "text-slate-700",
    cta: "Get API key",
    ctaStyle: "bg-[#17202a] text-white hover:bg-teal-700",
    href: "/login?next=/account",
    features: [
      { label: "Forecast & status endpoints", included: true },
      { label: "Optimize endpoint", included: true },
      { label: "Unlimited metered calls", included: true },
      { label: "60 requests / minute", included: true },
      { label: "MFA & audit log", included: true },
      { label: "Webhook delivery", included: false },
    ],
    footnote: "€0.08 per /optimize call, billed monthly.",
  },
  {
    name: "Pro",
    price: "€499",
    period: "/ month",
    badge: "Most popular",
    badgeStyle: "bg-amber-400 text-slate-950",
    cardStyle: "border-slate-800 bg-slate-950",
    headingStyle: "text-white",
    subStyle: "text-slate-300",
    bodyStyle: "text-slate-300",
    cta: "Contact sales",
    ctaStyle: "bg-teal-600 text-white hover:bg-teal-500",
    href: "mailto:sales@logicvolt.ai",
    features: [
      { label: "Everything in Pay-as-you-go", included: true },
      { label: "50 000 calls / month included", included: true },
      { label: "120 requests / minute", included: true },
      { label: "Webhook delivery", included: true },
      { label: "Priority support", included: true },
      { label: "Dedicated onboarding", included: false },
    ],
    footnote: null,
  },
  {
    name: "Enterprise",
    price: "€2 499",
    period: "/ month",
    badge: null,
    badgeStyle: "",
    cardStyle: "border-slate-200 bg-white",
    headingStyle: "text-slate-950",
    subStyle: "text-slate-500",
    bodyStyle: "text-slate-600",
    cta: "Contact sales",
    ctaStyle: "border border-slate-300 bg-white text-slate-700 hover:border-teal-500 hover:text-teal-700",
    href: "mailto:sales@logicvolt.ai",
    features: [
      { label: "Everything in Pro", included: true },
      { label: "1 000 000 calls / month", included: true },
      { label: "600 requests / minute", included: true },
      { label: "Webhook delivery", included: true },
      { label: "Dedicated onboarding", included: true },
      { label: "SLA & custom contracts", included: true },
    ],
    footnote: null,
  },
];

const FAQS = [
  {
    q: "What counts as an API call?",
    a: "Each request to /optimize is one metered call on Pay-as-you-go. Calls to /forecast, /status, and /data-feeds are not metered.",
  },
  {
    q: "Can I switch tiers at any time?",
    a: "Yes. An admin can change a key's tier instantly from the Account page. The change takes effect on the next request.",
  },
  {
    q: "Is there a free trial of the Optimize endpoint?",
    a: "Sign up for Pay-as-you-go — there is no monthly minimum. Your first calls are billed at €0.08 each with no upfront commitment.",
  },
  {
    q: "How is the monthly invoice calculated for Pay-as-you-go?",
    a: "We count /optimize calls over the calendar month and invoice at €0.08 per call. The base fee is always €0.",
  },
  {
    q: "Do you offer academic or non-profit pricing?",
    a: "Yes. Contact sales@logicvolt.ai with your institutional details and we will work out a custom arrangement.",
  },
];

export default function PricingPage() {
  return (
    <main className="min-h-screen bg-[#f3f5f7] text-[#17202a]">
      {/* Nav */}
      <nav className="sticky top-0 z-30 border-b border-white/10 bg-[#17202a]/95 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-4 py-3 md:px-8">
          <Link className="text-lg font-bold tracking-tight text-white" href="/">
            LogicVolt
          </Link>
          <div className="flex items-center gap-3 text-sm font-semibold">
            <Link className="text-slate-300 transition hover:text-white" href="/">Home</Link>
            <Link className="rounded-lg bg-teal-600 px-3 py-2 text-white transition hover:bg-teal-500" href="/login">
              Sign in
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="bg-[#17202a] px-4 py-16 text-center md:px-8 md:py-20">
        <div className="mx-auto max-w-2xl">
          <div className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-400">Pricing</div>
          <h1 className="mt-4 text-4xl font-bold text-white md:text-5xl">
            Pay for what you dispatch
          </h1>
          <p className="mt-5 text-base leading-7 text-slate-300 md:text-lg">
            Start free. Add API access with no monthly commitment on Pay-as-you-go.
            Scale to Pro or Enterprise when you need higher throughput and webhook delivery.
          </p>
        </div>
      </section>

      {/* Pricing cards */}
      <section className="mx-auto max-w-7xl px-4 py-14 md:px-8">
        <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
          {TIERS.map((tier) => (
            <div
              key={tier.name}
              className={`relative flex flex-col rounded-xl border p-6 shadow-sm ${tier.cardStyle}`}
            >
              {tier.badge ? (
                <span className={`absolute -top-3 left-5 rounded-full px-3 py-0.5 text-[10px] font-bold uppercase tracking-widest ${tier.badgeStyle}`}>
                  {tier.badge}
                </span>
              ) : null}

              <div className={`text-sm font-semibold ${tier.headingStyle}`}>{tier.name}</div>

              <div className={`mt-3 text-3xl font-bold ${tier.headingStyle}`}>
                {tier.price}
                <span className={`text-sm font-medium ${tier.subStyle}`}> {tier.period}</span>
              </div>

              {tier.footnote ? (
                <div className={`mt-1 text-xs font-semibold ${tier.subStyle}`}>{tier.footnote}</div>
              ) : null}

              <ul className={`mt-6 flex-1 space-y-2.5 text-sm ${tier.bodyStyle}`}>
                {tier.features.map((f) => (
                  <li key={f.label} className="flex items-start gap-2">
                    <span className={`mt-0.5 shrink-0 text-base leading-none ${f.included ? "text-teal-500" : "text-slate-300"}`}>
                      {f.included ? "✓" : "—"}
                    </span>
                    {f.label}
                  </li>
                ))}
              </ul>

              <Link
                href={tier.href}
                className={`mt-7 inline-flex w-full items-center justify-center rounded-lg px-4 py-2.5 text-sm font-semibold transition ${tier.ctaStyle}`}
              >
                {tier.cta}
              </Link>
            </div>
          ))}
        </div>

        {/* Compare table teaser */}
        <p className="mt-8 text-center text-sm text-slate-500">
          All plans include HMAC-signed audit logs, session MFA, and end-to-end AES-256-GCM encryption.
        </p>
      </section>

      {/* FAQ */}
      <section className="mx-auto max-w-3xl px-4 pb-20 md:px-8">
        <h2 className="text-center text-2xl font-semibold text-slate-950">Frequently asked questions</h2>
        <dl className="mt-8 divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white shadow-sm">
          {FAQS.map((faq) => (
            <div key={faq.q} className="px-6 py-5">
              <dt className="text-sm font-semibold text-slate-950">{faq.q}</dt>
              <dd className="mt-2 text-sm leading-6 text-slate-600">{faq.a}</dd>
            </div>
          ))}
        </dl>

        <div className="mt-10 rounded-xl border border-teal-200 bg-teal-50 p-6 text-center">
          <p className="text-sm font-semibold text-teal-900">Need a custom quote or volume discount?</p>
          <p className="mt-1 text-sm text-teal-700">We work with grid operators, energy retailers, and aggregators across Europe.</p>
          <a
            href="mailto:sales@logicvolt.ai"
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-[#17202a] px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-teal-700"
          >
            Talk to sales
          </a>
        </div>
      </section>
    </main>
  );
}
