# LogicVolt — 5-Minute Video Pitch Script

**Total Word Count:** ~790 words | **Target Duration:** 5:00

---

## MASTER STORYBOARD SCRIPT

### ACT 1: THE HOOK & PROBLEM (0:00 – 0:45)

| Timecode | Visual | Audio |
|---|---|---|
| 0:00–0:10 | **AI Presenter 1** — Confident, direct-to-camera. Background: stylized Greek energy grid animation. | **Presenter 1:** "Greece just turned on its first standalone batteries in the Day-Ahead electricity market. Fifty megawatts. One hundred megawatt-hours. And every fifteen minutes, there is a decision to make: charge, discharge, or stay idle." |
| 0:10–0:25 | **Screencast** — Animated timeline showing Greek DAM 15-minute price bars over 24 hours. Prices spike violently at sunset, collapse at midday. | **VO (Narrator):** "Greece's Day-Ahead Market now clears at fifteen-minute intervals — ninety-six price slots every single day. Renewable curtailments rose sharply in 2025. Solar floods collapse midday prices to zero. Evening peaks spike past two hundred euros per megawatt-hour. The spread is the opportunity — but only if you can predict it." |
| 0:25–0:45 | **AI Presenter 1** — Leaning in slightly. | **Presenter 1:** "The problem? These batteries have no operating history. No telemetry. No training data. The challenge asked us to build a system that makes profitable decisions despite that scarcity. We didn't just build a model — we built LogicVolt, a full enterprise platform." |

---

### ACT 2: THE SOLUTION (0:45 – 1:30)

| Timecode | Visual | Audio |
|---|---|---|
| 0:45–1:05 | **AI Presenter 2** — Clean, technical confidence. Background: architecture diagram fading in. | **Presenter 2:** "LogicVolt is a two-stage intelligence engine. Stage one: a quantile forecasting stack that predicts not just the price, but the uncertainty — the fifth, fiftieth, and ninety-fifth percentiles. Stage two: an adaptive Model Predictive Control scheduler. It looks up to seven days ahead, automatically selects the optimal planning horizon based on market volatility, and commits only today's dispatch." |
| 1:05–1:30 | **Screencast** — Architecture diagram: Data Sources → Feature Engine (73 features) → LightGBM Quantile Ensemble → Adaptive MPC (2–7 day horizon) → D0 Dispatch. Each block highlights as narrator speaks. | **VO (Narrator):** "Six live data feeds — HEnEx prices, ENTSO-E grid forecasts, IPTO load and renewables, Open-Meteo weather across four Greek cities, TTF gas futures, and EU carbon allowances — fuse into seventy-three engineered features. The scheduler then solves an N-day rolling-horizon MILP, discounting future days exponentially to hedge against forecast error. On volatile days, it extends the horizon. On stable days, it keeps it short." |

---

### ACT 3: THE DEMO (1:30 – 3:00)

| Timecode | Visual | Audio |
|---|---|---|
| 1:30–1:50 | **Screencast** — LogicVolt dashboard loads. Price forecast chart with q05/q50/q95 bands. Scenario selector visible (Base / Mild / Severe Degradation). | **VO (Narrator):** "Here is the live dashboard. The blue band shows our ninety-percent prediction interval. Notice how the model captures the midday solar collapse and the evening thermal ramp — the two windows that drive all battery revenue in Greece. Operators can switch degradation scenarios instantly." |
| 1:50–2:15 | **Screencast** — Hit "Optimize." Scheduler output overlaid: green charge bars, red discharge bars. SoC curve beneath. Planning mode selector and horizon counter visible. Faded D+1/D+2 forecast ghost on the right side. | **VO (Narrator):** "One click runs the full optimization. The adaptive scheduler chose a four-day horizon here — low spread today means there's a better opportunity tomorrow. It lets today's battery end at a lower State-of-Charge, banking capacity for tomorrow's deeper trough. Ninety-five percent round-trip efficiency, one-and-a-half cycle daily cap — all enforced mathematically, not with rules." |
| 2:15–2:40 | **Screencast** — KPI panel: daily profit, annualized revenue, naive baseline comparison, uplift, cycles used, idle count. | **Presenter 2 (VO overlay on demo):** "The KPIs tell the full story. Our walk-forward validation — five folds, seven days each, retrained weekly with zero leakage — delivers eighty-seven percent mean capture. But the number the customer sees is uplift: LogicVolt versus a naive peak-shaving heuristic, displayed right in the dashboard. Real value, not academic metrics." |
| 2:40–3:00 | **Screencast** — Side-by-side: negative price slots (scheduler never discharges), spike day zoom. Then quick flash of the feature importance chart. | **VO (Narrator):** "Edge cases handled natively. The system never discharges into negative prices. On the hardest spike day — two hundred ninety-two euros — our hand-engineered spike-likelihood feature lifted capture by seven percentage points. And operators can inspect exactly which features are driving the forecast." |

---

### ACT 4: PERFORMANCE & PLATFORM (3:00 – 3:45)

| Timecode | Visual | Audio |
|---|---|---|
| 3:00–3:25 | **AI Presenter 1** — Key metrics float beside them: €549K, +51%, 0.873. | **Presenter 1:** "The headline numbers. Thirty-day production-honest backtest: five hundred and forty-nine thousand euros in realized revenue. Eighteen thousand euros per day. Fifty-one percent above our honest baseline — one hundred and eighty-six thousand euros of additional value in a single month." |
| 3:25–3:45 | **Screencast** — Quick montage: Onboarding page (asset digital twin wizard, data feed health), Account page (API keys, MFA, audit log), Chatbot widget. | **VO (Narrator):** "And LogicVolt is not a notebook. It's a production SaaS platform. Digital twin onboarding. Live data feed monitoring. Role-based API keys with billing. Multi-factor authentication. An immutable audit log. Webhook integrations. And an in-app AI assistant powered by Groq for operator support." |

---

### ACT 5: DATA SCARCITY & ARCHITECTURE (3:45 – 4:15)

| Timecode | Visual | Audio |
|---|---|---|
| 3:45–4:15 | **AI Presenter 2** — Feature importance chart and architecture diagram fade in beside them. | **Presenter 2:** "The competition was designed around data scarcity — no battery telemetry exists in Greece. Our answer: domain-knowledge engineering. We built a spike-likelihood composite — encoding cloud cover, solar deficit, thermal stress, and time-of-day — directly as a feature. The model doesn't need thousands of spike examples. We gave it the physics. Top twelve features carry fifty percent of model gain. Every feature is strictly gate-close feasible — nothing leaks from the future." |

---

### ACT 6: CALL TO ACTION (4:15 – 5:00)

| Timecode | Visual | Audio |
|---|---|---|
| 4:15–4:35 | **AI Presenter 1** — Warm, forward-looking. | **Presenter 1:** "LogicVolt is live. Automated data refresh. Daily forecasting. Adaptive multi-day planning that adjusts its own horizon. An enterprise security stack. And a dashboard that any operator can use without writing a single line of code." |
| 4:35–4:55 | **AI Presenter 2** — Closing with vision. | **Presenter 2:** "Greece is just the beginning. Every European market coupled through SDAC — Italy, Bulgaria, Romania, and beyond — faces the same renewable volatility. The architecture is market-agnostic. The MPC framework scales from one battery to an entire portfolio. We built LogicVolt to optimize one asset. It's designed to manage a fleet." |
| 4:55–5:00 | **Both Presenters** side-by-side (or LogicVolt logo + tagline). | **Presenter 1:** "LogicVolt. Intelligence at every interval." |

---
---

## VOICE-OVER (VO) NARRATOR SCRIPT

*Record as a single clean take. Moderate pace, authoritative tone.*

> Greece's Day-Ahead Market now clears at fifteen-minute intervals — ninety-six price slots every single day. Renewable curtailments rose sharply in 2025. Solar floods collapse midday prices to zero. Evening peaks spike past two hundred euros per megawatt-hour. The spread is the opportunity — but only if you can predict it.
>
> Six live data feeds — HEnEx prices, ENTSO-E grid forecasts, IPTO load and renewables, Open-Meteo weather across four Greek cities, TTF gas futures, and EU carbon allowances — fuse into seventy-three engineered features. The scheduler then solves an N-day rolling-horizon MILP, discounting future days exponentially to hedge against forecast error. On volatile days, it extends the horizon. On stable days, it keeps it short.
>
> Here is the live dashboard. The blue band shows our ninety-percent prediction interval. Notice how the model captures the midday solar collapse and the evening thermal ramp — the two windows that drive all battery revenue in Greece. Operators can switch degradation scenarios instantly.
>
> One click runs the full optimization. The adaptive scheduler chose a four-day horizon here — low spread today means there's a better opportunity tomorrow. It lets today's battery end at a lower State-of-Charge, banking capacity for tomorrow's deeper trough. Ninety-five percent round-trip efficiency, one-and-a-half cycle daily cap — all enforced mathematically, not with rules.
>
> Edge cases handled natively. The system never discharges into negative prices. On the hardest spike day — two hundred ninety-two euros — our hand-engineered spike-likelihood feature lifted capture by seven percentage points. And operators can inspect exactly which features are driving the forecast.
>
> And LogicVolt is not a notebook. It's a production SaaS platform. Digital twin onboarding. Live data feed monitoring. Role-based API keys with billing. Multi-factor authentication. An immutable audit log. Webhook integrations. And an in-app AI assistant powered by Groq for operator support.

**VO Word Count:** ~290 words

---
---

## PRESENTER 1 SCRIPT

*Natural, confident delivery. The "business face" — owns the hook, the numbers, and the close.*

> Greece just turned on its first standalone batteries in the Day-Ahead electricity market. Fifty megawatts. One hundred megawatt-hours. And every fifteen minutes, there is a decision to make: charge, discharge, or stay idle.
>
> The problem? These batteries have no operating history. No telemetry. No training data. The challenge asked us to build a system that makes profitable decisions despite that scarcity. We didn't just build a model — we built LogicVolt, a full enterprise platform.
>
> The headline numbers. Thirty-day production-honest backtest: five hundred and forty-nine thousand euros in realized revenue. Eighteen thousand euros per day. Fifty-one percent above our honest baseline — one hundred and eighty-six thousand euros of additional value in a single month.
>
> LogicVolt is live. Automated data refresh. Daily forecasting. Adaptive multi-day planning that adjusts its own horizon. An enterprise security stack. And a dashboard that any operator can use without writing a single line of code.
>
> LogicVolt. Intelligence at every interval.

**Presenter 1 Word Count:** ~170 words

---
---

## PRESENTER 2 SCRIPT

*Technical authority with accessible delivery. The "architect" — owns the solution, the demo overlay, and the vision.*

> LogicVolt is a two-stage intelligence engine. Stage one: a quantile forecasting stack that predicts not just the price, but the uncertainty — the fifth, fiftieth, and ninety-fifth percentiles. Stage two: an adaptive Model Predictive Control scheduler. It looks up to seven days ahead, automatically selects the optimal planning horizon based on market volatility, and commits only today's dispatch.
>
> The KPIs tell the full story. Our walk-forward validation — five folds, seven days each, retrained weekly with zero leakage — delivers eighty-seven percent mean capture. But the number the customer sees is uplift: LogicVolt versus a naive peak-shaving heuristic, displayed right in the dashboard. Real value, not academic metrics.
>
> The competition was designed around data scarcity — no battery telemetry exists in Greece. Our answer: domain-knowledge engineering. We built a spike-likelihood composite — encoding cloud cover, solar deficit, thermal stress, and time-of-day — directly as a feature. The model doesn't need thousands of spike examples. We gave it the physics. Top twelve features carry fifty percent of model gain. Every feature is strictly gate-close feasible — nothing leaks from the future.
>
> Greece is just the beginning. Every European market coupled through SDAC — Italy, Bulgaria, Romania, and beyond — faces the same renewable volatility. The architecture is market-agnostic. The MPC framework scales from one battery to an entire portfolio. We built LogicVolt to optimize one asset. It's designed to manage a fleet.

**Presenter 2 Word Count:** ~240 words

---
---

## PRODUCTION NOTES

| Item | Recommendation |
|---|---|
| **AI Avatar Tool** | HeyGen, Synthesia, or D-ID for presenter segments |
| **Screen Recording** | OBS Studio or Loom for dashboard/demo captures |
| **VO Recording** | Clean room, condenser mic, 48kHz/24-bit WAV |
| **Music** | Subtle, cinematic underscore (royalty-free). Builds during Act 1, drops during Demo, swells at CTA |
| **Transitions** | Clean cuts between Avatar and Screencast. No flashy transitions |
| **Lower Thirds** | Display key metrics (€549K, +51%, 0.873) as animated text overlays during P1's Act 4 segment |
| **Demo Capture Priority** | 1) Dashboard with forecast bands, 2) Optimize click → schedule + SoC, 3) KPI panel with naive baseline uplift, 4) Onboarding page montage, 5) Account page with API keys + audit log |
| **Key Visual for MPC** | During Act 3, show D0 in full color and D+1/D+2 as faded ghost overlays. Show the "horizon: 4 days" indicator in the KPI panel |
| **Total Estimated Word Count** | ~790 words (VO: 290 + P1: 170 + P2: 240 + shared: ~90) |
