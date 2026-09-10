# Current Codex Task — Phase 8: Live Public-Data Paper Runtime & Explainable Dashboard

## Working branch

`phase-8-live-paper-dashboard`

Phase 7 is merged into `main` at `d334c14ee099834fa1ec7d15d9c08bb5abb724d5` and the accepted backend baseline is **2059 tests passing**.

## Objective

Turn the research/backend system into an understandable, live-looking application without enabling real-money execution.

Phase 8 has two coordinated deliverables:

1. **Live Public-Data Paper Runtime** — consume the existing public Binance market feed, evaluate the existing FeatureEngine → StrategyEngine → DecisionEngine pipeline, and maintain a bounded in-memory virtual paper portfolio using the Phase 7 portfolio policy/math.
2. **Explainable React/TypeScript Dashboard** — a clean user interface that shows what every module is doing, what each metric means, why a signal/decision was produced, and what the current virtual portfolio state is.

The dashboard may use the public `meiiie/hinto-trader` project only as a UX/feature reference. Do not copy its implementation. Build a fresh frontend around this repository's current contracts.

This phase is intended to make the program usable and understandable now while keeping clear architectural seams for future separately-reviewed exchange/account/P2P modules.

## Hard safety and scope boundaries

Phase 8 must NOT add or use:

- Binance private/account endpoints,
- API keys, API secrets or account credentials,
- balance/position reads from a real exchange account,
- real order submission,
- testnet order submission,
- deposits, withdrawals or transfers,
- P2P trade/transfer automation,
- payment automation,
- leverage/margin execution,
- liquidation logic tied to a real account,
- `TradeIntent` creation from the live paper runtime,
- `ApprovedTradeIntent` creation from the live paper runtime,
- calls to Phase 1 `RiskEngine` from the live paper runtime,
- calls to `PaperExecutionGateway` from the live paper runtime,
- AI/OpenAI API,
- ML/RL,
- automatic parameter optimization,
- strategy tuning against returns,
- database/Redis unless independently justified (prefer no persistence in Phase 8),
- buttons or API routes that can perform financial transactions.

The UI must visibly identify the current mode as **PAPER / VIRTUAL ONLY**.

Future real trading and P2P are architectural roadmap items only. It is acceptable to document future adapter boundaries, but do not implement an operational exchange-account or P2P transaction adapter in this phase.

## Baseline first

Before editing:

1. confirm branch is `phase-8-live-paper-dashboard`;
2. confirm `git status`;
3. run complete backend suite and confirm **2059 passing tests**;
4. inspect `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/PHASE_6_REPORT.md`, `docs/PHASE_7_REPORT.md`;
5. inspect the current public market-data lifecycle, FeatureEngine, StrategyEngine, DecisionEngine, Phase 7 policy/math/ledger/engine, and current API routes;
6. inspect repository CI;
7. inspect the public `meiiie/hinto-trader` frontend only for UX ideas such as dashboard/navigation/backtest/settings presentation. Do not copy source code.

Do not redesign or weaken Phase 1–7 contracts.

---

# Part A — Live Public-Data Paper Runtime

## Target data flow

```text
Existing public Binance WebSocket market feed
        ↓
MarketDataHub
        ↓
FeatureEngine
        ↓
StrategyEngine
        ↓
DecisionEngine
        ↓
LivePaperCoordinator
        ↓
PaperPortfolioPolicy / Phase 7 paper math
        ↓
virtual reservations / positions / closes
        ↓
LivePaperSnapshot + bounded audit events
        ↓
read-only HTTP/WebSocket telemetry
        ↓
React dashboard
```

No execution gateway belongs after this path in Phase 8.

## Closed-bar trigger

Use finalized `kline_1m` observations as the default analytical trigger.

Requirements:

- only closed/finalized bars trigger portfolio decisions;
- never trigger from an unfinished candle;
- preserve existing market freshness/readiness rules;
- no synthetic bars;
- no REST gap fabrication;
- a feed gap must remain observable;
- no future observation is available to a decision;
- use explicit event timestamps and UTC.

Do not create a second set of strategy formulas for live mode. Reuse the existing production Feature/Strategy/Decision engines.

## Same-close multi-symbol batching

Live WebSocket arrival order is nondeterministic, but portfolio arbitration must remain stable.

Implement a small `LiveBarBatcher` or equivalent that groups finalized bars by their canonical close/event boundary.

Preferred behavior:

- key groups by the existing canonical finalized-bar event timestamp;
- collect configured-symbol bars for that close boundary;
- finalize a group when all expected symbols for that boundary have arrived, OR after a small configurable timeout;
- timeout must use an injected monotonic clock/timer abstraction in tests;
- missing symbols on timeout stay missing; never fabricate their bars;
- sort the finalized group deterministically by symbol before evaluation/arbitration;
- late bars for an already finalized group must be diagnosed explicitly and must not rewrite historical portfolio state;
- duplicate identical finalized bars are ignored/countable; conflicting duplicates fail closed/are diagnosed.

Suggested settings:

```text
LIVE_PAPER_ENABLED=true
LIVE_PAPER_BATCH_TIMEOUT_MS=1500
LIVE_PAPER_EVENT_HISTORY_LIMIT=1000
LIVE_PAPER_CURVE_HISTORY_LIMIT=2000
LIVE_PAPER_POSITION_HISTORY_LIMIT=1000
```

Validate all limits strictly.

## Runtime portfolio state

Do not blindly reuse the finite Phase 7 `PaperPortfolioEngine.run()` report object as a perpetual live service because its full audit history grows for a finite backtest.

Reuse Phase 7 domain types, policy and pure arithmetic where practical, but add a bounded live runtime/coordinator designed for indefinite operation.

It must maintain:

- current virtual realized equity;
- current known marked equity;
- peak marked equity;
- drawdown;
- gross exposure;
- reserved exposure;
- per-symbol exposure;
- active reservations;
- active virtual positions;
- recent virtual closes;
- recent portfolio decisions/rejections;
- recent feed/runtime warnings;
- bounded equity/metric history for dashboard charts.

The same portfolio defaults remain the starting point unless explicitly configured:

- initial virtual equity = 100000;
- target position fraction = 0.10;
- max gross exposure = 0.40;
- max symbol exposure = 0.15;
- max open positions = 4;
- max drawdown = 0.20;
- one position per symbol = true;
- holding period = 5 complete bars;
- fee assumption = 5 bps/side;
- adverse slippage assumption = 2 bps/side.

These remain simulation assumptions, not current Binance fee claims.

## Live paper entry/exit convention

Preserve the Phase 6/7 anti-look-ahead convention conceptually:

- decision from closed bar `t`;
- reservation is made after close `t`;
- virtual entry uses the next exact bar `t+1` open once that finalized bar later becomes available to the system;
- exit uses the configured fixed-horizon close;
- missing entry bar expires the reservation;
- missing required holding bar makes exposure incomplete/unknown rather than fabricating a mark or exit.

No confidence-based size multiplier.
No Kelly sizing.
No leverage.
No pyramiding/reversal.
No partial allocation.

## Runtime state machine

Create explicit statuses close to:

```text
DISABLED
STARTING
WARMING_UP
RUNNING
DEGRADED
STOPPING
STOPPED
ERROR
```

Expose why a state is degraded, for example:

- market feed stale;
- missing required symbol bar;
- feature pipeline warming up;
- portfolio valuation unknown;
- delayed/late bar;
- runtime exception.

A dashboard user should never have to infer whether the engine is healthy.

## Bounded audit events

Create immutable, JSON-safe telemetry/event types.

Each event should include when appropriate:

- event ID;
- UTC timestamp;
- category;
- severity (`info`, `warning`, `error`);
- symbol if relevant;
- short machine reason;
- short human-readable explanation;
- related decision/reservation/position ID where applicable.

Keep event history bounded.
Do not log credentials because Phase 8 has none.

## Lifecycle

Integrate the live paper coordinator with FastAPI lifespan without breaking existing feed lifecycle.

Requirements:

- when `LIVE_PAPER_ENABLED=false`, no live-paper background task is created;
- startup must not perform private/account calls;
- shutdown cleanly cancels coordinator/batcher subscriptions;
- zero orphan tasks/subscribers after shutdown;
- one application instance must not accidentally start duplicate live-paper coordinators;
- tests must use injected/offline market sources; no real Binance network in CI.

---

# Part B — Read-only dashboard API

Add read-only endpoints specifically for UI telemetry. Keep mutating financial actions out of the API.

Suggested routes (adapt to existing API style):

```text
GET /paper/status
GET /paper/portfolio
GET /paper/positions
GET /paper/decisions
GET /paper/events
GET /paper/curve
GET /explain/modules
GET /explain/terms
```

Support bounded `limit` query parameters where appropriate with strict max limits.

Optionally add one **read-only WebSocket telemetry stream** such as:

```text
WS /ws/dashboard
```

It may push snapshots/events to connected dashboards. It must accept no commands that alter trading state. If a WebSocket adds too much complexity, deterministic polling is acceptable for the first Phase 8 implementation, but structure the frontend service layer so streaming can be added later.

Do not expose internal exception traces to the browser.

## Explainability payloads

The UI needs understandable descriptions, not only raw fields.

Create a small static/backend explanation catalog or frontend equivalent for terms such as:

- Market Data;
- Feature Engine;
- EMA;
- RSI;
- ATR;
- VWAP;
- volatility;
- spread;
- basis/funding context;
- Strategy Engine;
- trend following;
- momentum continuation;
- mean reversion;
- strategy score;
- agreement;
- confidence;
- Decision Engine;
- ELIGIBLE / BLOCKED / NO_ACTION;
- reservation;
- virtual position;
- marked equity;
- realized PnL;
- unrealized PnL;
- gross exposure;
- drawdown;
- fee/slippage assumptions;
- backtest;
- paper portfolio.

Critical wording:

- confidence is **evidence quality/agreement**, not probability of profit;
- ELIGIBLE means the deterministic policy allowed further paper evaluation, not "guaranteed buy";
- historical/backtest returns do not predict future profit;
- paper fills are simulated assumptions.

---

# Part C — Frontend

## Technology

Create a new `frontend/` application using a current stable, version-pinned setup after verifying package compatibility.

Preferred:

- React;
- TypeScript;
- Vite;
- simple maintainable CSS/design tokens;
- lightweight charting only if justified;
- Vitest + Testing Library for core component/service tests;
- no secret values in frontend environment variables.

This phase is web-first. Keep it easy to wrap with Tauri later, but do not require Rust/Tauri for Phase 8 CI unless there is a compelling reason.

Do not copy the original Hinto frontend code. Recreate the useful UX concepts in a cleaner structure.

## Visual direction

Build a dark professional trading/research dashboard, readable rather than flashy.

Use:

- left navigation/sidebar;
- top status bar;
- clear PAPER / VIRTUAL badge always visible;
- responsive desktop-first layout;
- cards/tables/charts with consistent spacing;
- accessible contrast;
- keyboard/focus states;
- empty/loading/error/degraded states;
- no deceptive "profit guaranteed" styling.

Avoid excessive animation.

## Navigation

Required sections:

### 1. Overview

Show at a glance:

- runtime status;
- public feed health;
- selected symbol/current price;
- Feature/Strategy/Decision readiness;
- virtual marked equity;
- realized equity;
- drawdown;
- gross exposure;
- open positions;
- active reservations;
- latest portfolio decision;
- recent warnings/events;
- equity curve.

Every advanced metric gets an info icon / tooltip.

### 2. Market

For each configured symbol show:

- latest price / close;
- market freshness;
- bid/ask/spread if available;
- mark/index context if available;
- feature readiness;
- key indicators already produced by Phase 3;
- timestamp / stale marker.

A symbol details panel should explain indicator values in plain language.

### 3. Signals & Decisions

Show the full explainable chain:

```text
Features → strategies → aggregate → Decision Engine → portfolio policy
```

For each recent observation show:

- symbol/time;
- trend/momentum/mean-reversion assessments;
- composite score;
- confidence;
- agreement;
- DecisionOutcome;
- DecisionEngine reason;
- portfolio action (RESERVED/REJECTED/IGNORED);
- portfolio reason;
- a human-readable "Why?" explanation.

Do not present confidence as a win probability.

### 4. Paper Portfolio

Show:

- virtual initial equity;
- realized/marked equity;
- realized/unrealized PnL;
- costs;
- peak equity;
- drawdown;
- gross exposure and limits;
- per-symbol exposure;
- reservations;
- open virtual positions;
- recent closed positions;
- entry/exit timestamps and raw prices;
- reason/status for incomplete positions;
- equity/drawdown/exposure charts.

Clearly label all amounts as virtual simulation units.

### 5. Backtest & Validation

Phase 8 does not need a full browser file uploader/execution workflow unless it is small and safe.

At minimum provide an educational/report view describing Phase 6/7 validation capabilities and show example/schema/known report metrics if available from read-only backend data.

If adding a local backtest form, it must operate only on local/offline historical public bars and fixed simulation settings. No optimizer.

### 6. System / Settings

Read-only or locally editable UI preferences only.

Show:

- runtime mode;
- configured public symbols;
- relevant Feature/Strategy/Decision/Paper settings;
- portfolio limits;
- fee/slippage assumptions;
- backend/API connection status;
- version/build information;
- warnings/limitations.

Do not add controls that enable real trading, private API credentials, withdrawals, transfers or P2P transactions.

If future modules are shown, display them as disabled roadmap cards:

- `Exchange Account Adapter — future phase`
- `Real Execution — future phase`
- `P2P Analytics — future phase`

No credential form.
No "Enable Live Trading" button.

### 7. Guide / How It Works

This section is mandatory because the user wants to understand the program.

Create a simple visual explanation of the architecture:

```text
Binance public data
→ MarketDataHub
→ FeatureEngine
→ StrategyEngine
→ DecisionEngine
→ PaperPortfolioPolicy
→ Virtual portfolio
→ Dashboard
```

For every block explain:

- what goes in;
- what it calculates;
- what comes out;
- whether it can move money (all Phase 8 blocks: no);
- links to relevant dashboard section.

Add a glossary and examples.

## Beginner / Advanced presentation

Implement a simple UI preference:

- **Simple view**: plain-language descriptions and only the most important metrics;
- **Advanced view**: full technical fields/IDs/strategy evidence.

This preference is local UI state only; it must not change backend strategy/risk behavior.

## Help / tooltips

Every technical label introduced to the main UI should have one of:

- tooltip;
- inline help text;
- link to glossary.

The help text should explain not just definition but why the metric matters.

Example style:

```text
Drawdown
How far the virtual portfolio is below its previous peak.
A 10% drawdown means the marked virtual equity is 10% below its highest previously observed value.
This is a simulation metric, not a prediction.
```

---

# Part D — Frontend/backend contracts

Create typed frontend API models matching backend JSON.

Prefer a dedicated service layer:

```text
frontend/src/api/
frontend/src/types/
frontend/src/pages/
frontend/src/components/
frontend/src/features/
frontend/src/help/
```

Keep components reasonably small; do not build one 40k-line `App.tsx`.

Centralize:

- API base URL;
- polling/streaming behavior;
- date formatting;
- Decimal/string-number display;
- runtime error mapping;
- glossary/help content.

The frontend must gracefully handle backend unavailable, stale market data and unknown portfolio valuation.

Never silently convert `null` valuation into zero.

---

# Part E — Future-ready architecture without implementing live money

Document a future clean architecture only:

```text
DecisionRecord
→ future deterministic intent/sizing builder
→ future independent pre-execution risk review
→ future execution port
→ future exchange adapter
```

For P2P, document a completely separate future boundary:

```text
future public P2P market observations
→ analytics/risk/quote comparison
→ user-visible information
```

Do not implement automated counterpart selection, transfers, deposits, withdrawals or transaction execution.

The current dashboard should keep paper/live-money concepts visually separate so a future real adapter cannot accidentally reuse a paper label or UI action.

---

# Development batches

## Batch 1 — Runtime contracts and pure batching

Implement:

- live paper settings;
- runtime domain/status/event contracts;
- deterministic finalized-bar batching;
- duplicate/late/missing behavior;
- bounded buffers;
- tests.

Run targeted tests.

## Batch 2 — Live paper coordinator

Implement:

- coordinator around existing public market/analytical engines;
- reuse Phase 7 policy/math;
- reservation/position lifecycle for indefinite runtime;
- bounded telemetry/audit;
- explicit degraded/error states;
- clean startup/shutdown;
- tests including injected clocks and sources.

Run targeted tests + relevant Phase 7 regressions.

## Batch 3 — Read-only dashboard API

Implement:

- `/paper/*` telemetry endpoints;
- explanation/glossary data;
- strict response models;
- limits/pagination where needed;
- optional read-only WebSocket if clean;
- offline API/lifecycle tests.

Confirm no financial mutation routes are introduced.

## Batch 4 — Frontend foundation and explainability

Create fresh React/TypeScript/Vite frontend with:

- app shell/sidebar/status bar;
- API client;
- reusable cards/tables/status badges/tooltips/help drawer;
- Simple/Advanced view preference;
- Overview + Guide + System pages;
- frontend tests/build.

## Batch 5 — Trading/research views

Implement:

- Market page;
- Signals & Decisions page;
- Paper Portfolio page;
- Backtest/Validation page;
- charts where useful;
- loading/stale/degraded/unknown states;
- responsive/accessibility pass.

## Batch 6 — Integration, CI and documentation

- connect frontend to actual Phase 8 API;
- verify runtime with injected public events;
- verify frontend against representative backend payloads;
- update CI to run backend suite and frontend tests/build;
- update README and architecture;
- create `docs/PHASE_8_REPORT.md`;
- create `docs/USER_GUIDE.md` with screenshots optional but not required;
- create `docs/MODULE_MAP.md` explaining every engine/module in plain language.

---

# Required tests

Backend tests must include at minimum:

- baseline Phase 1–7 regression;
- no unfinished candle triggers a decision;
- same-close symbol permutations produce identical arbitration;
- batch timeout uses injected clock and never fabricates missing bars;
- late bar does not rewrite finalized state;
- duplicate finalized event handling;
- conflicting duplicate handling;
- reservation next-bar entry;
- fixed-horizon close;
- missing-entry expiry;
- missing-horizon unknown valuation;
- drawdown/exposure/symbol/position limits;
- runtime disabled creates no tasks;
- enabled runtime starts exactly once;
- graceful shutdown leaves zero tasks/subscribers;
- bounded event/curve/close histories;
- stale/degraded states;
- no private/account network calls;
- no TradeIntent/ApprovedTradeIntent creation;
- no RiskEngine/PaperExecutionGateway invocation;
- API response schema tests;
- API limit validation;
- null/unknown valuation remains null;
- deterministic IDs for equivalent injected input where relevant.

Frontend tests must cover at minimum:

- app renders with backend unavailable;
- PAPER/VIRTUAL badge is visible;
- overview renders representative state;
- null marked equity shows `Unknown`, not zero;
- stale/degraded state is obvious;
- confidence explanation says it is not profit probability;
- portfolio limit explanations;
- Simple/Advanced toggle changes presentation only;
- Signals & Decisions reason display;
- Guide/module explanations;
- core tables/cards with empty data;
- API parser/adapter behavior;
- frontend production build succeeds.

---

# CI and final validation

Keep existing backend CI green and extend CI carefully for the new frontend.

At completion run and report exact results for:

```text
backend: python -m pytest
backend: python -m pip check
frontend: npm ci
frontend: npm test -- --run   (or exact chosen equivalent)
frontend: npm run build
```

Also validate:

- backend import/OpenAPI;
- offline lifespan with live paper disabled;
- offline lifespan with injected public source and live paper enabled;
- zero remaining coordinator/subscriber tasks after shutdown;
- repeated deterministic injected run;
- same-close symbol permutation equivalence;
- bounded-history behavior over a long synthetic stream;
- `git diff --check`;
- `git status`;
- `git diff --stat`;
- source audit for private Binance endpoints, credentials, transaction actions and prohibited integrations.

No CI test may require access to Binance or any external network.

---

# Documentation requirements

Update/create:

- `README.md` — quick start for backend + dashboard;
- `backend/README.md` — live paper runtime/API;
- `frontend/README.md` — frontend commands and architecture;
- `docs/ARCHITECTURE.md` — Phase 8 path and future adapter boundaries;
- `docs/USER_GUIDE.md` — plain-language guide to every screen and metric;
- `docs/MODULE_MAP.md` — what each backend component does;
- `docs/PHASE_8_REPORT.md` — exact implementation/testing evidence.

The user guide should be understandable to someone learning the project. Avoid assuming the reader already knows trading-engine vocabulary.

---

# Completion report

At completion report:

1. exact baseline test result;
2. every batch's targeted test result;
3. final backend test count;
4. frontend test count;
5. frontend production-build result;
6. files created/modified;
7. live runtime architecture;
8. batch/grouping rules;
9. reservation/entry/exit semantics;
10. portfolio accounting behavior;
11. bounded-memory limits;
12. API routes added;
13. frontend pages/components;
14. Simple/Advanced behavior;
15. glossary/help coverage;
16. lifecycle behavior;
17. CI changes;
18. exact ancillary checks;
19. warnings/limitations;
20. future real-execution boundary;
21. future P2P analytics boundary;
22. explicit confirmation that no private/account/order/transfer/P2P execution was added;
23. `git status` and `git diff --stat`.

Do not commit or push automatically.
Do not start Phase 9.
