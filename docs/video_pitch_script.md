# LogicVolt — 5-Minute Video Pitch Script

**Total Word Count:** ~790 words | **Target Duration:** 5:00

---

## MASTER STORYBOARD SCRIPT

### ACT 1: THE HOOK & PROBLEM (0:00 – 0:45)

| Timecode | Visual | Audio |
|---|---|---|
| 0:00–0:10 | **AI Presenter 1** — Confident, direct-to-camera. Background: stylized Greek energy grid animation. | **Presenter 1:** "Greece just turned on its first standalone batteries in the Day-Ahead electricity market. Fifty megawatts. One hundred megawatt-hours. And every fifteen minutes, there is a decision to make: charge, discharge, or stay idle." |
| 0:10–0:25 | **Screencast** — Animated timeline showing Greek DAM 15-minute price bars over 24 hours. Prices spike violently at sunset, collapse at midday. | **VO (Narrator):** "Greece's Day-Ahead Market now clears at fifteen-minute intervals — ninety-six price slots every single day. Renewable curtailments rose sharply in 2025. Solar floods collapse midday prices to zero. Evening peaks spike past two hundred euros per megawatt-hour. The spread is the opportunity — but only if you can predict it." |
| 0:25–0:45 | **AI Presenter 1** — Leaning in slightly. | **Presenter 1:** "The problem? These batteries have no operating history. No telemetry. No training data. The challenge asked us to build a system that makes profitable decisions despite that scarcity. We built LogicVolt." |

---

### ACT 2: THE SOLUTION (0:45 – 1:30)

| Timecode | Visual | Audio |
|---|---|---|
| 0:45–1:05 | **AI Presenter 2** — Clean, technical confidence. Background: architecture diagram fading in. | **Presenter 2:** "LogicVolt is a two-stage intelligence engine. Stage one: a quantile forecasting stack that predicts not just the price, but the uncertainty around the price — the fifth, fiftieth, and ninety-fifth percentiles. Stage two: a Model Predictive Control scheduler — a rolling-horizon MILP that optimizes across today and tomorrow simultaneously, then commits only today's dispatch." |
| 1:05–1:30 | **Screencast** — Simplified architecture diagram: Data Sources → Feature Engine (73 features) → LightGBM Quantile Ensemble → Scenario Blend → MPC MILP Scheduler (D0+D1) → D0 Dispatch Plan. Each block highlights as narrator describes it. | **VO (Narrator):** "Six live data feeds — HEnEx market results, ENTSO-E grid forecasts, IPTO load and renewables, Open-Meteo weather across four Greek cities, TTF gas futures, and EU carbon allowances — are fused into seventy-three engineered features. These feed a three-seed LightGBM ensemble with conformal calibration. The output flows into a two-day rolling-horizon optimizer that sees one hundred and ninety-two slots at once — but only executes the first ninety-six." |

---

### ACT 3: THE DEMO (1:30 – 3:00)

| Timecode | Visual | Audio |
|---|---|---|
| 1:30–1:50 | **Screencast** — Dashboard loads. Price forecast chart with q05/q50/q95 bands for a single day. | **VO (Narrator):** "Here is a typical forecast day. The blue band shows our ninety-percent prediction interval. Notice how the model captures the midday solar collapse and the evening thermal ramp — the two windows that drive all battery revenue in Greece." |
| 1:50–2:15 | **Screencast** — Scheduler output overlaid: green bars for charging at low-price hours, red bars for discharging at peaks. SoC curve flowing beneath. A faded D+1 forecast visible on the right side of the chart. | **VO (Narrator):** "The MPC scheduler charges during the solar surplus — near-zero cost energy — and discharges into the evening peak. But here is what makes it different: it sees tomorrow's forecast too. If tomorrow has a deeper price trough, the solver lets today's battery end at a lower State-of-Charge, banking capacity for tomorrow's better opportunity. It respects a one-and-a-half cycle daily cap and ninety-five percent round-trip efficiency. No hard-coded rules. Pure mathematical optimization with a two-day planning horizon." |
| 2:15–2:40 | **Screencast** — Walk-forward validation results table. Daily capture ratios as a bar chart — most bars above 0.85. | **Presenter 2 (VO overlay on demo):** "This is the number that matters: capture ratio — how much of the theoretically perfect revenue our system actually realizes. Our walk-forward validation — five folds, seven days each, retrained weekly with zero data leakage — delivers an eighty-seven point three percent mean capture, with a median of eighty-nine percent." |
| 2:40–3:00 | **Screencast** — Side-by-side: negative price slots highlighted (scheduler never discharges), spike day zoom (Apr 22, 292€/MWh peak). | **VO (Narrator):** "Edge cases are handled natively. The system never discharges into negative prices. Never charges in the top ten percent of slots. On the hardest spike day — a two-hundred-ninety-two euro peak — our hand-engineered spike-likelihood feature lifted capture by seven percentage points on the worst day alone." |

---

### ACT 4: PERFORMANCE & TRACTION (3:00 – 3:45)

| Timecode | Visual | Audio |
|---|---|---|
| 3:00–3:25 | **AI Presenter 1** — Key metrics appear as floating text beside them: €549K, +51%, 0.873. | **Presenter 1:** "The headline numbers. Over a thirty-day production-honest backtest: five hundred and forty-nine thousand euros in realized revenue. Eighteen thousand euros per day. Compared to our original honest baseline, that is a fifty-one percent increase — one hundred and eighty-six thousand euros of additional value unlocked in a single month." |
| 3:25–3:45 | **Screencast** — Progression table: baseline 0.808 → leakage fix → soft cyclic SoC (+6pp) → economic weighting → spike features → MPC horizon → final 0.873. | **VO (Narrator):** "Every improvement was validated through walk-forward testing. The single biggest lever — a soft cyclic State-of-Charge penalty — added six percentage points alone. We tried and discarded twelve approaches that didn't survive honest validation. What remains is battle-tested." |

---

### ACT 5: DATA SCARCITY & ARCHITECTURE (3:45 – 4:15)

| Timecode | Visual | Audio |
|---|---|---|
| 3:45–4:15 | **AI Presenter 2** — Speaking with authority. Feature importance chart fades in beside them. | **Presenter 2:** "The competition was designed around data scarcity — no battery telemetry exists in Greece. Our answer: domain-knowledge engineering. We built a spike-likelihood composite — encoding cloud cover, solar deficit, thermal stress, and time-of-day — directly as a feature. The model doesn't need thousands of spike examples. We gave it the physics. Our top twelve features carry fifty percent of model gain. Top thirty cover eighty-two percent. Every single feature is strictly gate-close feasible — nothing leaks from the future." |

---

### ACT 6: CALL TO ACTION (4:15 – 5:00)

| Timecode | Visual | Audio |
|---|---|---|
| 4:15–4:35 | **AI Presenter 1** — Warm, forward-looking. | **Presenter 1:** "LogicVolt is not a prototype. It has a live operational loop — automated data refresh, daily forecasting at eleven AM, rolling KPI monitoring, and a two-day planning horizon that adapts as new forecasts arrive. It is ready to run a real fifty-megawatt battery on the Greek grid, today." |
| 4:35–4:55 | **AI Presenter 2** — Closing with vision. | **Presenter 2:** "Greece is just the beginning. Every European market coupled through SDAC — Italy, Bulgaria, Romania, and beyond — faces the same renewable volatility. The architecture is market-agnostic. The MPC framework scales from one battery to an entire portfolio. We built LogicVolt to optimize one asset. It's designed to manage a fleet." |
| 4:55–5:00 | **Both Presenters** side-by-side (or LogicVolt logo + tagline). | **Presenter 1:** "LogicVolt. Intelligence at every interval." |

---
---

## VOICE-OVER (VO) NARRATOR SCRIPT

*Record as a single clean take. Moderate pace, authoritative tone.*

> Greece's Day-Ahead Market now clears at fifteen-minute intervals — ninety-six price slots every single day. Renewable curtailments rose sharply in 2025. Solar floods collapse midday prices to zero. Evening peaks spike past two hundred euros per megawatt-hour. The spread is the opportunity — but only if you can predict it.
>
> Six live data feeds — HEnEx market results, ENTSO-E grid forecasts, IPTO load and renewables, Open-Meteo weather across four Greek cities, TTF gas futures, and EU carbon allowances — are fused into seventy-three engineered features. These feed a three-seed LightGBM ensemble with conformal calibration. The output flows into a two-day rolling-horizon optimizer that sees one hundred and ninety-two slots at once — but only executes the first ninety-six.
>
> Here is a typical forecast day. The blue band shows our ninety-percent prediction interval. Notice how the model captures the midday solar collapse and the evening thermal ramp — the two windows that drive all battery revenue in Greece.
>
> The MPC scheduler charges during the solar surplus — near-zero cost energy — and discharges into the evening peak. But here is what makes it different: it sees tomorrow's forecast too. If tomorrow has a deeper price trough, the solver lets today's battery end at a lower State-of-Charge, banking capacity for tomorrow's better opportunity. It respects a one-and-a-half cycle daily cap and ninety-five percent round-trip efficiency. No hard-coded rules. Pure mathematical optimization with a two-day planning horizon.
>
> Edge cases are handled natively. The system never discharges into negative prices. Never charges in the top ten percent of slots. On the hardest spike day — a two-hundred-ninety-two euro peak — our hand-engineered spike-likelihood feature lifted capture by seven percentage points on the worst day alone.
>
> Every improvement was validated through walk-forward testing. The single biggest lever — a soft cyclic State-of-Charge penalty — added six percentage points alone. We tried and discarded twelve approaches that didn't survive honest validation. What remains is battle-tested.

**VO Word Count:** ~295 words

---
---

## PRESENTER 1 SCRIPT

*Natural, confident delivery. This is the "business face" — owns the hook, the numbers, and the close.*

> Greece just turned on its first standalone batteries in the Day-Ahead electricity market. Fifty megawatts. One hundred megawatt-hours. And every fifteen minutes, there is a decision to make: charge, discharge, or stay idle.
>
> The problem? These batteries have no operating history. No telemetry. No training data. The challenge asked us to build a system that makes profitable decisions despite that scarcity. We built LogicVolt.
>
> The headline numbers. Over a thirty-day production-honest backtest: five hundred and forty-nine thousand euros in realized revenue. Eighteen thousand euros per day. Compared to our original honest baseline, that is a fifty-one percent increase — one hundred and eighty-six thousand euros of additional value unlocked in a single month.
>
> LogicVolt is not a prototype. It has a live operational loop — automated data refresh, daily forecasting at eleven AM, rolling KPI monitoring, and a two-day planning horizon that adapts as new forecasts arrive. It is ready to run a real fifty-megawatt battery on the Greek grid, today.
>
> LogicVolt. Intelligence at every interval.

**Presenter 1 Word Count:** ~170 words

---
---

## PRESENTER 2 SCRIPT

*Technical authority with accessible delivery. This is the "architect" — owns the solution, the demo walkthrough, and the vision.*

> LogicVolt is a two-stage intelligence engine. Stage one: a quantile forecasting stack that predicts not just the price, but the uncertainty around the price — the fifth, fiftieth, and ninety-fifth percentiles. Stage two: a Model Predictive Control scheduler — a rolling-horizon MILP that optimizes across today and tomorrow simultaneously, then commits only today's dispatch.
>
> This is the number that matters: capture ratio — how much of the theoretically perfect revenue our system actually realizes. Our walk-forward validation — five folds, seven days each, retrained weekly with zero data leakage — delivers an eighty-seven point three percent mean capture, with a median of eighty-nine percent.
>
> The competition was designed around data scarcity — no battery telemetry exists in Greece. Our answer: domain-knowledge engineering. We built a spike-likelihood composite — encoding cloud cover, solar deficit, thermal stress, and time-of-day — directly as a feature. The model doesn't need thousands of spike examples. We gave it the physics. Our top twelve features carry fifty percent of model gain. Top thirty cover eighty-two percent. Every single feature is strictly gate-close feasible — nothing leaks from the future.
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
| **Transitions** | Clean cuts between Avatar and Screencast. No flashy transitions. |
| **Lower Thirds** | Display key metrics (€549K, +51%, 0.873) as animated text overlays during Presenter 1's Act 4 segment |
| **Key Visual for MPC** | During Act 3 demo, show D0 in full color and D+1 as a faded/ghost overlay on the right side of the price chart — visually communicates the "look ahead, commit today" concept |
| **Total Estimated Word Count** | ~790 words (VO: 295 + P1: 170 + P2: 240 + shared: ~85) |
