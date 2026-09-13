# Phase 8 completion report

Branch: `phase-8-live-paper-dashboard`. Scope: live **public-data + virtual paper
runtime + explainable dashboard**. No commit, push, history rewrite or Phase 9 work.
Existing work was preserved across usage-limit interruptions. Finalization resumed
from completed Batches 1–5; only documentation, formatting, verification and fixes
supported by final validation were added.

## Baseline and workflow

Phase 7 merged base: `d334c14ee099834fa1ec7d15d9c08bb5abb724d5`. The branch's
pre-implementation additions were the Phase 8 task/spec, not production changes.
The user authorized the initial switch from main to the existing Phase 8 branch.
The accepted **branch baseline was 2059 passed, 2 warnings in 48.57s** using
`backend/.venv/Scripts/python.exe -m pytest`. The earlier main check was 2059
passed, 2 warnings in 48.36s; it was not substituted for the branch check.

AGENTS, task, UI spec, architecture, Phase 6/7 reports, CI and relevant production
code were read before implementation. Batches were validated before continuing.
There was no broad rewrite of Phase 1–7 engines or new backend dependency.

## Runtime architecture and evidence boundary

```text
Existing public Binance feed -> MarketDataHub
  -> bounded tagged closed-candle observer -> LiveBarBatcher
  -> original age / source-generation admission
  -> isolated closed-bar view using unchanged FeatureEngine
     -> unchanged StrategyEngine -> unchanged DecisionEngine
  -> LivePaperCoordinator -> Phase 7 PaperPortfolioPolicy
  -> bounded LivePaperPortfolio -> read-only telemetry -> React
```

Ordinary Hub and on-demand analytical APIs remain available. An isolated analytical
view is necessary: the ordinary cache may already contain t+1 when closed t is
handled. `LivePaperAnalysis` publishes only admitted canonical finalized bars and
evaluates each at its exact close boundary. It checks that the resulting feature
snapshot's closed-candle time equals the admitted bar. No alternative strategy
formula or look-ahead context is introduced.

Three time concepts stay explicit: real UTC for admission/health, monotonic time
for batch deadlines, and canonical close time for admitted analytical evaluation.
Original boundary, publication and receipt ages must each satisfy
`0 <= age < min(Hub stale allowance, strategy feature-age limit, decision age limit)`.
The default minimum is 10 seconds; 9.999 passes and 10 fails. Canonicalization does
not erase this gate. Lazy feature-consumer startup yields once, so connection
provenance and ages are checked again after that yield. Telemetry retains actual
publication and receipt times alongside canonical evaluation time.

The observer tags each admitted closed observation with connection ID/generation.
It must match the current CONNECTED kline connection. Obsolete generations cannot
enter a batch; a change while preparing a group rejects that group's old evidence.
Connection identity/status/generation changes invalidate continuity, expire
reservations and leave active exposure explicitly unresolved. The analytical
generation advances and history warms up again. Missing optional book, trade and
mark/funding context is not replaced with newer live quotes; production optional
book confidence quality remains 0.75 by default. Current public context is displayed
separately from captured evidence.

### Grouping, duplicates, loss and late data

Groups use canonical close boundaries and configured symbol scope. Finalization
occurs when all expected symbols are seen (including conflicted members), or at
the first-arrival monotonic deadline, default 1500 ms. Pending groups are processed
chronologically and each result is sorted by symbol. Missing members stay missing.
The implementation cannot predict an entirely unseen earlier group; after a newer
boundary seals, an earlier arrival is late and cannot rewrite state.

Identical duplicates compare canonical bar content, not incidental receipt/publication
latency. They are ignored/countable. Conflicting pending members are removed from
the usable group; conflicting late bars are diagnosed without replacing history.
Conflicting evidence fails closed for virtual continuity. Recent fingerprints are
bounded, while a monotonic watermark permanently prevents reopening sealed times.
After fingerprint eviction an old event is diagnosed as late, not necessarily as
an identical duplicate.

The additive closed observer preserves ordinary Hub cache/subscriber semantics.
It can expose revisions rejected by ordinary latest ordering so the coordinator
can diagnose them. Future-clock events remain excluded from queues. Queue loss is
tracked per subscriber. On loss, pending groups are sealed/discarded, queued
ambiguity is drained and virtual/analytical continuity invalidates. The queue/timer
race fix is preserved: settle both tasks, recheck drops before admitting a held
observation, always acknowledge it, and poll only when no new loss occurred.

### States and lifecycle

States: DISABLED, STARTING, WARMING_UP, RUNNING, DEGRADED, STOPPING, STOPPED, ERROR.
Normal insufficient history is WARMING_UP; missing/stale required feed, failed
analytical consumer, unknown valuation or recent continuity diagnostics produce
DEGRADED. RUNNING means current requirements are met, not that a candidate exists.
Safe events make receipt/generation rejection and missing members visible.
Internal failures stop the runtime as ERROR without returning exception text.

Lifespan builds one coordinator. Public and paper consumers register before the
source starts. A disabled paper runtime creates no paper task/subscription.
Disabled public data without an injected source also disables paper/features.
Shutdown cancels and awaits source, coordinator and original feature task; nested
closed-view analysis and receive/timer tasks are removed. Active exposure is not
liquidated. Import/OpenAPI creates no network or runtime task. All state is
process-local and starts fresh on restart; use one backend worker.

### Bounded continuous storage

| Structure | Default bound | Configuration |
| --- | --- | --- |
| Tagged closed queue | 1000 events | `LIVE_PAPER_QUEUE_LIMIT`, 1–10000 |
| Pending close groups | 8 groups × configured symbols | `LIVE_PAPER_PENDING_BATCH_LIMIT`, 1–64 |
| Recent sealed fingerprints | 8 groups × configured symbols | Same pending-group setting |
| Runtime events | 1000 | `LIVE_PAPER_EVENT_HISTORY_LIMIT`, 1–10000 |
| Captured feature/strategy/decision history | 1000 captures | Same event-history setting |
| Recent decision dedupe IDs | 1000 | Same event-history setting |
| Recent completed positions | 1000 | `LIVE_PAPER_POSITION_HISTORY_LIMIT`, 1–10000 |
| Equity/exposure/drawdown curve | 2000 points | `LIVE_PAPER_CURVE_HISTORY_LIMIT`, 1–20000 |
| Current analytical captures | One per configured symbol | Fixed configured scope |
| Closed-candle history | 500 per symbol per FeatureEngine | Existing `FEATURE_HISTORY_LIMIT` |
| Active plus reserved positions | 4; one per symbol | Existing Phase 7 settings |

Monotonic watermark and cumulative PnL/count/peak aggregates do not retain a
growing event list. Configuration bounds validate strictly. Continuous record
retention is bounded; scalar counter integer precision naturally grows with count.
Phase 6/7 finite-run audit reports intentionally grow with finite input and are
not used as live storage. The 650-bar coordinator test uses small event=11,
curve=13, close=2 caps and verifies eviction, feature bounds and cleanup. A separate
400-bar ledger test checks that lifetime PnL survives recent-close eviction.

## Phase 7 policy and accounting integration

The new live ledger reuses domain contracts, PaperPortfolioPolicy, identity
helpers and pure Phase 7 math, plus Phase 6 `outcome_returns`. It does not call
RiskEngine or PaperExecutionGateway. Exact finite-prefix equivalence is tested.

Defaults: initial virtual equity 100000; target fraction 0.10; max gross 0.40;
max symbol 0.15; four open-plus-reserved positions; drawdown limit 0.20; one
position per symbol. No pyramiding, reversal or partial allocation. Candidate
confidence never scales size or represents profit probability.

At each finalized group, apply previous reservations at exact current bar opens,
apply known close marks/exits, then arbitrate current decisions. Rank descending
absolute score, confidence and agreement, then ascending symbol and decision ID.
Full desired notional is known marked equity times target fraction. Capacity
includes reservations immediately. LONG/SHORT gross notionals do not cancel.
Noneligible upstream records are diagnostic IGNORED results. Invalid/stale/unknown
state, nonpositive equity, drawdown at the limit, active symbol, slot capacity,
gross capacity and symbol capacity block reservations with stable reasons.

Decision at closed t enters at open(t+1), observed only when that next finalized
bar arrives. Exit is close(t+H), H=5 default. The source close is not an entry
price. Entry quantity, leverage, account balance and executable intent do not exist.
Reservations are fixed before future prices are visible.

For notional N, raw entry E, current known close C, direction d=+1/-1,
slippage fraction s=2/10000 and fee fraction f=5/10000 by default:

```text
open gross PnL       = N*d*(C-E)/E
entry slippage cost  = N*s
entry fee cost       = N*f*(1+d*s)
open net PnL         = open gross PnL - entry slippage cost - entry fee cost
realized equity      = initial equity + cumulative completed net PnL
marked equity        = realized equity + sum(known open net PnL)
drawdown             = (peak known marked equity - marked equity)/peak
gross exposure       = open fixed notional + reserved fixed notional
```

Completed return/cost components use Phase 6 math and multiply by N; full two-sided
net PnL is realized exactly once after removing the open mark. Both fee sides
use slippage-adjusted effective prices. Costs are assumptions, not current Binance
fee claims. Arithmetic uses the fixed 34-digit Decimal context. Outstanding entry
costs are reported separately for unfinished positions.

Missing exact entry expires a reservation. Missing any required holding bar makes
that position INCOMPLETE, retaining notional and null total marked equity/drawdown/
exposure fraction. Later bars cannot repair its path. Other known positions can
finish; new reservations block. With a silent source, a required boundary becomes
missing after stale allowance + batch timeout (11.5 seconds default); empty
evidence advances the ledger without fabricating prices. Prior curve points stay
unchanged. Limits affect new reservations, not forced exits or liquidation.

Decision, policy, reservation, position and close identities reuse canonical
hashing/settings/evidence rules. Equivalent injected runs and equal-time symbol
permutations produce identical captured decisions, curves and closes. Runtime
event IDs additionally include time and occurrence count; diagnostic arrival order
is observable. Whole live sessions are not promised identical across different
network delays, losses or restarts. Dedupe is bounded/in-memory, not durable action
suppression; sealed-time admission prevents old observations reopening history.

## API, consistency and provenance

Exactly **nine new GET paths**, **19 total OpenAPI paths**:

```text
GET /paper/snapshot
GET /paper/status
GET /paper/portfolio
GET /paper/positions
GET /paper/decisions
GET /paper/events
GET /paper/curve
GET /explain/modules
GET /explain/terms
```

No POST/PUT/PATCH/DELETE trading/runtime action or new WebSocket is added. Polling
is the task's permitted first implementation. Strict limits accept ASCII integer
query text 1–1000, default 100 for snapshot/positions/decisions/events and 500 for
curve. Decisions/events/closes are newest first; curves are chronological tails.
Uninitialized runtime returns safe 503; disabled runtime returns valid empty data.
The existing unknown-symbol market behavior stays 404.

The combined snapshot is synchronously projected on the application event loop.
It shares `as_of` for status/portfolio/positions, includes a distinct portfolio
`valuation_as_of`, and separates current market times from captured analysis times.
No await occurs inside ledger transition or projection. GETs never invoke analytical
evaluation, drain a queue, advance a clock or create virtual actions. Tests forbid
those methods during repeated reads. Returned dictionaries cannot mutate runtime
state. Independently issued GETs are not a single atomic transaction.

Settings and hashes cover runtime, features, strategy, decision policy, portfolio
policy and costs. Captures expose source connection identity/generation separately
from current Hub metadata. Null valuation stays null; Decimal JSON stays finite
strings. Depth arrays are not interpreted or exported as a full order book.

## Frontend and generated contracts

Fresh React/TypeScript/Vite frontend, authored without copying upstream code.
The public Hinto project was used only as a UX reference. Node 22.12.0/npm 11.0.0
were tested. Pinned runtime packages: React/ReactDOM 19.3.0, AJV 8.20.0,
ajv-formats 3.0.1. Tooling: Vite 8.3.0, plugin-react 6.1.1, TypeScript 7.0.2,
Vitest 5.0.0, jsdom 28.1.0, json-schema-to-typescript 16.0.0 and pinned Testing
Library/type packages listed in package.json/lockfile. Later jsdom versions need
a newer Node minor. No dependency was added just to suppress a warning.

App only composes the polling hook and Dashboard; pages/components/services are
separate. Backend schema and TypeScript models are generated, not hand-maintained
duplicate domain definitions. One backend catalog supplies 50 terms and ten module
descriptions: market, Hub, features, strategies, decisions, coordinator, policy,
ledger, telemetry and dashboard. It covers all key indicators, readiness, costs,
equity/exposure, identity/generation and confidence limitations. Frontend reason
wording is centralized and exhaustively typed against backend enums.

The serialization exporter fixes a real mismatch: Pydantic Decimal can emit
`0E+33`, while its default schema pattern can reject that string. The exported
schema accepts normal, negative and finite scientific Decimal notation, rejecting
NaN/Infinity. Serialized default fields are required. AJV checks discriminator,
status and other required fields. Formatting converts finite numbers only for
presentation; accounting remains Decimal in Python. Overflow displays Unknown.

Python exporters produce schema, help and four actual offline runtime fixtures:
disabled, RUNNING, unresolved/incomplete exposure, and BLOCKED under a stricter
three-contributor decision gate. Test fixtures are not imported into the product.
Two identical regenerations match hashes. Type-generator style explicitly matches
the installed formatter, avoiding regeneration-versus-format drift. `--check`
verifies Python artifacts; CI checks generated types against Git.

Seven pages: Overview; Market; Signals & Decisions; Paper Portfolio; Backtest &
Validation; System / Settings; Guide / How It Works. Simple/Advanced changes only
local display (`hinto.view`), never server settings. Advanced adds captured evidence,
source ages, generation and IDs. Backend remains authoritative for all indicators,
decisions, approvals, status and accounting. Frontend math is limited to formatting,
sorting, quote differences, display ratios and chart coordinates.

PAPER / VIRTUAL ONLY is persistent. Loading, empty, unavailable, stale, degraded,
blocked/no-action/eligible and incomplete states are explicit. Unknown values never
become zero; charts split at null points and omit all-unknown series. Missing
optional freshness metadata is STALE / MISSING, never FRESH. UTC times distinguish
current observations, captures and valuation. Help is keyboard reachable with
Enter/Space/Escape; a skip link and focus styling are included. Responsive CSS has
no external fonts/assets. Backtest is educational, with no fake performance or run
button. Future account/execution/P2P cards are disabled and nonfunctional.

GET polling uses `/api/paper/snapshot?limit=100`, five-second timeout and sequential
two-second success polling; errors retry at 4/8/15 seconds capped at 15. Failure
clears old displayed data; unmount aborts requests/removes timers and visibility
listeners. The local Vite `/api` proxy targets port 8000. A production same-origin
reverse proxy/deployment remains separate work.

## Validation evidence

Python commands use the repository virtual environment from `backend/`; npm
commands use `npm.cmd` in Windows PowerShell from `frontend/`. This avoids blocked
unsigned npm.ps1 without changing execution policy. No tests contact Binance.

| Stage / exact test scope | Result |
| --- | --- |
| Branch baseline: `python -m pytest` | 2059 passed, 2 warnings, 48.57s |
| Batch 1: `tests/test_live_bar_batcher.py` | 77 passed, 0.41s |
| Batch 2 intermediate: live portfolio/batcher, Hub, portfolio policy | 192 passed, 1.92s |
| Batch 2 coordinator/portfolio/batcher | 109 passed, 23.11s |
| Batch 2 broader lifecycle/live/Phase 7/market/feature regression | 504 passed, 2 warnings, 50.35s |
| Batch 3: `tests/test_live_paper_api.py` | 79 passed, 4.06s |
| Batch 3 affected `tests/test_feature_api.py` | 23 passed, 2 warnings, 1.38s |
| Batch 3 broad live/all API/Phase 7 regression | 482 passed, 2 warnings, 56.33s |
| Contract export + live API | 84 passed, 4.01s |
| Batch 4: `npm test` | 27 passed, 3.68s; TypeScript/build passed |
| Batch 5: `npm test` | 48 passed, 6.94s; TypeScript/build passed (Vite 156ms) |
| Finalization semantic fixes: frontend / contract tests | 55 passed, 7.34s / 5 passed, 0.50s |
| Final Phase 8: all six `test_live_*.py` files | 203 collected, 203 passed, 0 failed, 0 warnings, 25.55s |
| Final frontend: `npm test` | 60 passed in 2 files, 0 failed, 16.96s |
| Final build: `npm run build` | `tsc --noEmit` passed; Vite 8.3.0 built 131 modules in 256ms |
| Reproducible install: `npm ci` | 133 packages added, 134 audited, 0 vulnerabilities, 31s |
| Final broad Phase 8 + relevant regression | 678 collected, 678 passed, 0 failed, 2 warnings, 55.73s |
| Complete backend: `python -m pytest` | **2262 collected, 2262 passed, 0 failed, 2 warnings, 73.21s (0:01:13)** |
| `python -m pip check` | `No broken requirements found.` |
| Import/OpenAPI | PASS: 19 paths, nine Phase 8 paths, all GET-only |
| Offline disabled/injected lifespan smoke | PASS: clean shutdown, zero tasks/subscribers/timers |
| Python exporters `--check` | PASS: schema/catalog and four deterministic fixtures |
| Repeated type generation / Prettier check | PASS: byte-identical types, all matched files formatted |

Final total is the original 2059 plus 203 Phase 8 tests. No backend test was
removed, skipped or weakened. The final OpenAPI one-line audit initially compared
dicts to tuples by mistake; correcting the audit expression passed without an
application change. Earlier standalone smoke and API tests already passed the
same route/method assertions.

Final Vite output: HTML 0.61 kB (gzip 0.37), CSS 12.98 kB (gzip 3.86), JS 487.61 kB
(gzip 135.37). No separate typecheck/lint script exists; build performs TypeScript.
Installed Prettier checks source/README/config/generator/index after regeneration.

Earlier failures were resolved rather than weakened: one old exact-route assertion
needed the nine added GET paths; frontend validation exposed Decimal exponent and
reason-shape mismatches; fixture/selector issues were corrected; keyboard help was
made explicit. Finalization exposed the missing optional-stream FRESH label with
a failing test, then fixed only those two labels. The new NO_ACTION assertion was
corrected to expect the existing human-readable "NO ACTION" display. Generator
format drift was fixed at the generator. No analytical formula changed.

### Determinism, anti-look-ahead and cleanup evidence

The full Phase 8 suite reruns identical/reversed/rotated three-symbol 80-bar
scenarios and compares captured decisions/curves/closes byte-for-byte; a constrained
one-slot case checks deterministic BTC selection. Batcher permutations test all
equal-time orders. Tests cover open-candle exclusion, duplicate/conflict/late
immutability, exact age limits, original time retention, old generation and
generation changes during startup, queue/timer loss and cancellation.

Future-cache contamination tests publish a newer closed bar before processing
the older one and verify its exact evidence boundary. Changing future prices
preserves the entire earlier decision/portfolio prefix. Phase 7 capacity/sizing
tests preserve current-state-only arbitration. The 650/400-bar bound tests execute
as part of final targeted/full suites, not a skipped soak claim.

Standalone import/OpenAPI and network-guarded ASGI lifespan smoke passed:
disabled runtime returned DISABLED with zero decisions/subscribers; injected
source processed three finalized bars, returned WARMING_UP with three captured
decisions and two public-Hub subscribers while active. Both shutdowns had zero
remaining tasks, subscribers, source workers or timer waiters. The nested
analytical Hub also had zero subscribers. External socket connection attempts
were patched to fail. Existing tests additionally cover RUNNING, DEGRADED, safe
ERROR and cleanup during lazy startup.

Local HTTP serving previously returned frontend 200 and a proxied disabled paper
snapshot with zero subscribers. Both local test servers were stopped. **Browser
visual inspection unavailable in this Codex environment.** No manual visual
verification, screenshot or browser layout claim is made; jsdom component and
keyboard tests are the available UI evidence.

## CI and scope audit

The workflow now triggers for backend/frontend changes. Backend job installs
requirements, runs complete pytest, pip check and both Python exporter checks.
Frontend job sets Node 22.12.0, runs npm ci, generates/verifies types, runs Vitest
and builds. Current official setup-node documentation was checked for v7. CI
tests need no market service, browser cloud, secret or credential. Dependency
installation uses package registries; test execution itself is offline. Remote CI
was not run because nothing was pushed.

Runtime AST tests reject execution/private-network/AI/database/optimizer imports
and financial action calls in the Phase 8 services. Component tests inspect every
page for forbidden financial controls and credential forms. Existing Phase 1
types remain present but separate. Final source/artifact audit is recorded below.

Public Binance adapter behavior was not changed. Existing combined route mapping:
aggTrade, kline and markPrice -> `/market`; bookTicker and depth -> `/public`.
Two route-grouped combined connections retain the existing transport's reconnect,
rotation, subscription restoration and built-in ping/pong behavior. Depth remains
normalized deltas only. No new external Binance contract was guessed or implemented.

## Limitations and deferred boundaries

- Existing two dependency deprecations remain: Starlette TestClient/httpx and
  AnyIO BlockingPortal import. No backend dependency upgrade was made for them.
- No connected browser: human visual, responsive and full assistive-technology
  review remains. jsdom is not a real browser rendering engine.
- No sustained real-Binance soak, latency benchmark or production deployment is
  claimed. Delayed/lost evidence deliberately fails closed; defaults may require
  operational validation without tuning strategy thresholds to returns.
- Reconnect/rotation can require 50-candle warm-up and leave existing exposure
  permanently unknown. There is no REST backfill, reconciliation or recovery API.
- State, dedupe and audit windows are in-memory; restart loses them. A long-lived
  process has bounded records but feature recalculation and large typed snapshots
  still have CPU/serialization cost. No multiworker shared state or durable audit.
- Next-open/fixed-horizon fills are retrospective bar assumptions, not executable
  latency guarantees. No funding charge, market impact, fill queue, intrabar stop,
  margin/liquidation or quantity selection. No profitability claim.
- Decimal accounting is finite and deterministic; log-statistic floats inherit
  existing platform math limitations. Exact cross-platform fixture regeneration
  remains subject to the Ubuntu CI check; it has not been run remotely here.
- Frontend display uses finite JavaScript numbers and can lose precision relative
  to Decimal strings; backend accounting/IDs remain authoritative. Very large
  nonrepresentable values show Unknown. Bundle includes schema validation.
- Polling is implemented; dashboard WebSocket, report upload/run UI, persistent
  sessions, Tauri wrapping and production reverse-proxy configuration are deferred.
- Future execution must separately introduce deterministic intent/sizing,
  independent pre-execution risk review, an execution port and exchange adapter.
  Future P2P public observations belong to separate analytics/quote comparison and
  user-visible information. No transaction automation is connected.
- No private/account endpoints, API keys, real/testnet orders, account reads,
  deposits/withdrawals/transfers, P2P execution, leverage, TradeIntent creation,
  ApprovedTradeIntent, RiskEngine/gateway invocation, AI/ML/RL, parameter fitting,
  optimization, database/Redis or full order-book reconstruction was introduced.

## Final regression, file inventory and Git state

Final targeted command (from backend):

```text
python -m pytest tests/test_live_bar_batcher.py tests/test_live_paper_portfolio.py tests/test_live_paper_coordinator.py tests/test_live_paper_lifecycle.py tests/test_live_paper_api.py tests/test_live_paper_contract_export.py
```

Final broad command selected the 21 test files matching the following PowerShell
expression, then ran `python -m pytest @phase8Tests`:

```powershell
$phase8Tests = Get-ChildItem tests/test_*.py |
  Where-Object { $_.Name -match '^test_live_|^test_paper_portfolio_|^test_market_data_hub|^test_feature_(engine|history|subscription|edge_cases)|_api\.py$' } |
  ForEach-Object { 'tests/'+$_.Name }
```

This includes all six Phase 8 files, all five Phase 7 portfolio files, Hub,
feature engine/history/subscription/edge cases, and all existing API tests.
The full `python -m pytest` additionally covers Binance transport/router/parsers,
all numerical/strategy/decision/backtest tests and Phase 1 risk/paper behavior.

Other executed commands: `npm ci`, `npm test`, `npm run build`, `npm run types`,
`python scripts/export_dashboard_contract.py` and `--check`,
`python tests/export_dashboard_examples.py` and `--check`, `python -m pip check`,
installed Prettier `--write` and separate `--check`, `git diff --check`,
`git status`, `git diff --stat`, and read-only source/link/credential audits.
Import/OpenAPI and offline smoke were inline Python checks with socket connections
forbidden. No formatter touched Phase 1–7 Python. No stage/commit/push command ran.

Reproducibility SHA-256 values after final generation:

```text
dashboard.schema.json 7F1FF9708205007D08F844C39F58FE6690D7727955C44A5B5BB913FDCF065225
catalog.json          176BFFC61615BDFD7767EF02BF6EBADB4DBDE8D1614EDD5E24E5A6CBA7C71212
generated.ts          30F6AF683FAC84AC95A99291FA92AFBBB89F8C6996BA62419D65363DCC18C0A1
blocked.json          4E21592DC3DABD6B00FFDD1110E52EBF3EBC4B28295D9EC08E1E7AD17632E26A
disabled.json         42EA2151649526A1E014E8E57AC1F21B3DC07415FF923BAF24DD90A4226ED755
incomplete.json       11D96EDB154BE4898E8CD9597D40FD48AE4A84F0C2B5BE9BE7115CF5794E04D5
running.json          541DFEFC4CC5B68636D137A7451E6EE9358D7E0ECA5CDE030C58C3056BFDB302
```

Audit found no accidental build/cache/log/env files among intended changes; no
credential assignments, private endpoint URLs, external AI/database endpoints,
or new prohibited execution calls. All new guide/module/report links resolve.
Manual diff inspection confirms only additive Hub/lifespan wiring and exact API
test compatibility changes in previous-phase files. React has one GET client;
its remaining arithmetic is presentation-only, with no backend-setting mutation.
New live services have no TODO, FIXME or unimplemented placeholder. No actual
secret value was printed during scanning. Contextual safety/future wording is
deliberately retained. Existing .gitignore excludes caches, environments,
node_modules, dist and runtime storage. Git may emit LF-to-CRLF notices; these
are line-ending conversion notices, not test failures.

All listed changes are intentional Phase 8 work. The inventory and final Git
outputs below include untracked files explicitly; ordinary `git diff --stat`
does not count their contents.


### Files modified (12 tracked)

```text
.github/workflows/backend-ci.yml
CODEX_TASK.md
README.md
backend/README.md
backend/src/application/market_data_hub.py
backend/src/main.py
backend/tests/conftest.py
backend/tests/test_decision_api.py
backend/tests/test_feature_api.py
backend/tests/test_paper_portfolio_engine.py
backend/tests/test_strategy_api.py
docs/ARCHITECTURE.md
```

### Files created (61 untracked)

```text
backend/scripts/export_dashboard_contract.py
backend/src/api/live_paper.py
backend/src/application/explanations.py
backend/src/application/live_bar_batcher.py
backend/src/application/live_paper_analysis.py
backend/src/application/live_paper_clock.py
backend/src/application/live_paper_coordinator.py
backend/src/application/live_paper_portfolio.py
backend/src/application/live_paper_settings.py
backend/src/application/live_paper_telemetry.py
backend/src/domain/live_paper.py
backend/tests/export_dashboard_examples.py
backend/tests/live_paper_fixtures.py
backend/tests/test_live_bar_batcher.py
backend/tests/test_live_paper_api.py
backend/tests/test_live_paper_contract_export.py
backend/tests/test_live_paper_coordinator.py
backend/tests/test_live_paper_lifecycle.py
backend/tests/test_live_paper_portfolio.py
docs/MODULE_MAP.md
docs/PHASE_8_REPORT.md
docs/USER_GUIDE.md
frontend/README.md
frontend/index.html
frontend/package-lock.json
frontend/package.json
frontend/scripts/generate-types.mjs
frontend/src/App.tsx
frontend/src/api/client.ts
frontend/src/api/dashboard.schema.json
frontend/src/components/Capacity.tsx
frontend/src/components/Common.tsx
frontend/src/components/Curve.tsx
frontend/src/components/FeatureDetails.tsx
frontend/src/help/Help.tsx
frontend/src/help/catalog.json
frontend/src/help/reasons.ts
frontend/src/hooks/useTelemetry.ts
frontend/src/layouts/Dashboard.tsx
frontend/src/main.tsx
frontend/src/pages/Backtest.tsx
frontend/src/pages/Guide.tsx
frontend/src/pages/Market.tsx
frontend/src/pages/Overview.tsx
frontend/src/pages/Portfolio.tsx
frontend/src/pages/Signals.tsx
frontend/src/pages/System.tsx
frontend/src/styles.css
frontend/src/test/fixtures/blocked.json
frontend/src/test/fixtures/disabled.json
frontend/src/test/fixtures/incomplete.json
frontend/src/test/fixtures/running.json
frontend/src/test/foundation.test.tsx
frontend/src/test/research.test.tsx
frontend/src/test/setup.ts
frontend/src/types/generated.ts
frontend/src/types/index.ts
frontend/src/utils/format.ts
frontend/src/utils/market.ts
frontend/tsconfig.json
frontend/vite.config.ts
```

### Final git status

```text
On branch phase-8-live-paper-dashboard
Your branch is up to date with 'origin/phase-8-live-paper-dashboard'.

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
	modified:   .github/workflows/backend-ci.yml
	modified:   CODEX_TASK.md
	modified:   README.md
	modified:   backend/README.md
	modified:   backend/src/application/market_data_hub.py
	modified:   backend/src/main.py
	modified:   backend/tests/conftest.py
	modified:   backend/tests/test_decision_api.py
	modified:   backend/tests/test_feature_api.py
	modified:   backend/tests/test_paper_portfolio_engine.py
	modified:   backend/tests/test_strategy_api.py
	modified:   docs/ARCHITECTURE.md

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	backend/scripts/
	backend/src/api/live_paper.py
	backend/src/application/explanations.py
	backend/src/application/live_bar_batcher.py
	backend/src/application/live_paper_analysis.py
	backend/src/application/live_paper_clock.py
	backend/src/application/live_paper_coordinator.py
	backend/src/application/live_paper_portfolio.py
	backend/src/application/live_paper_settings.py
	backend/src/application/live_paper_telemetry.py
	backend/src/domain/live_paper.py
	backend/tests/export_dashboard_examples.py
	backend/tests/live_paper_fixtures.py
	backend/tests/test_live_bar_batcher.py
	backend/tests/test_live_paper_api.py
	backend/tests/test_live_paper_contract_export.py
	backend/tests/test_live_paper_coordinator.py
	backend/tests/test_live_paper_lifecycle.py
	backend/tests/test_live_paper_portfolio.py
	docs/MODULE_MAP.md
	docs/PHASE_8_REPORT.md
	docs/USER_GUIDE.md
	frontend/

no changes added to commit (use "git add" and/or "git commit -a")
```

### Final git diff --stat

```text
 .github/workflows/backend-ci.yml             |  25 ++++-
 CODEX_TASK.md                                |  11 +++
 README.md                                    |  47 +++++++++-
 backend/README.md                            | 131 ++++++++++++++++++++++++++-
 backend/src/application/market_data_hub.py   |  43 ++++++++-
 backend/src/main.py                          |  39 +++++++-
 backend/tests/conftest.py                    |   5 +-
 backend/tests/test_decision_api.py           |   2 +-
 backend/tests/test_feature_api.py            |   5 +-
 backend/tests/test_paper_portfolio_engine.py |   2 +-
 backend/tests/test_strategy_api.py           |   2 +-
 docs/ARCHITECTURE.md                         |  85 ++++++++++++++++-
 12 files changed, 378 insertions(+), 19 deletions(-)
```

`git diff --check` passed (exit 0). Nothing is staged. The stat above covers
tracked edits only; 61 new files are also present, for 73 intended files total.
No implementation item remains unfinished. Operational/visual limitations above
remain explicit review risks. No commit, push or Phase 9 work was performed.

**PHASE 8 READY FOR REVIEW**
