# Phase 10 — Research Validation Lab

## Purpose

Phase 10 turns the existing deterministic backtest and paper-trading stack into a reproducible **research validation lab**. The goal is not to find parameters that maximize return. The goal is to measure whether the existing fixed strategies and decision policy remain coherent across time windows, market regimes, symbols and plausible transaction-cost assumptions.

This phase stays **PAPER / VIRTUAL / RESEARCH ONLY**.

Accepted base: `main` at `2925f38d6423c28e92a39c9758766112bd197714` (Phase 9 fully merged and green).

Accepted baseline on the Phase 9 merge:

- backend: **2410 passed, 2 existing warnings** on GitHub Actions;
- frontend: **77 passed**;
- `pip check`: clean;
- generated dashboard contract/examples: reproducible;
- all 19 HTTP paths: GET-only;
- no private exchange/account integration.

---

## Deliverables

1. **Reproducible historical dataset contract**
   - content-addressed manifest;
   - symbol/interval/time-range provenance;
   - deterministic canonical row encoding;
   - gap/duplicate/conflict diagnostics;
   - dataset SHA-256 identity;
   - no silent repair or fabricated bars.

2. **Deterministic walk-forward evaluator**
   - fixed strategy/settings only;
   - rolling and expanding evaluation windows;
   - chronological train/context/test boundaries;
   - no future leakage;
   - no browser-triggered optimization;
   - no parameter search.

3. **Regime and robustness analysis**
   - causal regime labels based only on information available at each bar;
   - trend/range and low/medium/high-volatility partitions;
   - symbol-level and aggregate breakdowns;
   - minimum-sample warnings;
   - no claim that historical success predicts profit.

4. **Cost/slippage sensitivity**
   - rerun identical decisions under a bounded deterministic grid of fee/slippage assumptions;
   - strategy parameters stay fixed;
   - show where conclusions are sensitive to costs;
   - never select the “best” cost scenario.

5. **Explainable validation report + read-only dashboard**
   - persisted/exportable deterministic JSON report;
   - report identity from dataset + engine/settings + validation protocol;
   - backend GET-only projection;
   - frontend Validation page or equivalent research panel;
   - Simple/Advanced explanations;
   - explicit separation of confidence, historical hit rate, expected return and probability of profit.

---

## Hard boundaries

Phase 10 must NOT add:

- private Binance/account endpoints;
- API keys/secrets/signing;
- real or testnet order submission;
- deposits, withdrawals, transfers or P2P transaction automation;
- leverage/margin execution;
- real liquidation logic;
- browser financial controls;
- `TradeIntent` / `ApprovedTradeIntent` creation from validation flows;
- `RiskEngine` or `PaperExecutionGateway` invocation from validation flows;
- AI/OpenAI API;
- ML/RL;
- automatic strategy optimization;
- Bayesian/grid/random parameter search;
- return-based parameter fitting;
- automatic selection of the best strategy/settings from validation results;
- cloud databases or remote experiment stores;
- fabricated historical candles;
- forward-fill of missing OHLCV;
- newest-price substitution for historical gaps.

Public historical market-data acquisition may be added only as an explicit **public-data import utility**, never as an account integration. CI must remain fully offline and use deterministic fixtures/local datasets.

---

## Core scientific invariants

### No lookahead

For every evaluated decision at time `t`:

- features may use only observations with event time `<= t`;
- regime labels at `t` may use only history available by `t`;
- entry/exit semantics remain exactly those already defined by Phase 6/7;
- a test window cannot influence features, thresholds or settings used before it.

### No hidden fitting

The validation engine evaluates fixed repository settings. It may split data and summarize outcomes, but it may not modify strategy, decision, portfolio or cost parameters based on test performance.

### Missing data remains missing

A dataset with gaps must report those gaps. The evaluator must either reject a protocol that requires contiguous evidence or preserve existing explicit incomplete/missing semantics. It must never synthesize a bar.

### Reproducibility

The same:

- canonical dataset;
- validation protocol;
- engine versions;
- settings identities;
- cost scenario;

must produce the same report identity and metrics.

---

## Suggested architecture

```text
historical public bars / local canonical dataset
        ↓
DatasetValidator
        ↓
DatasetManifest + dataset_id
        ↓
WalkForwardProtocol
        ↓
existing HistoricalReplay
        ↓
existing FeatureEngine → StrategyEngine → DecisionEngine
        ↓
existing backtest / virtual portfolio evaluator
        ↓
window results
        ↓
RegimeAnalyzer + CostSensitivityAnalyzer
        ↓
ValidationReport
        ↓
content-addressed local report export
        ↓
GET-only telemetry → dashboard Validation page
```

Do not fork or rewrite the existing strategy/decision/backtest math.

---

## Batch 1 — Dataset contracts and canonical identity

Add narrow domain/application models for:

- dataset metadata;
- row count;
- symbols;
- interval;
- first/last boundary;
- source label;
- canonical content hash;
- gap count;
- duplicate count;
- conflict count;
- validation status.

Requirements:

- aware UTC timestamps;
- finalized bars only;
- deterministic ordering by `(boundary, symbol)`;
- exact Decimal preservation;
- duplicate-identical rows diagnosed once;
- duplicate-conflicting rows rejected;
- out-of-order input canonicalized only when doing so does not hide a conflict;
- gaps explicitly listed/countable;
- no repair.

Create a canonical dataset codec/export format using only bounded, deterministic dependencies. Prefer stdlib JSON/JSONL + gzip if practical; do not add pandas/pyarrow solely for this phase unless clearly justified.

Acceptance tests:

- identical dataset → identical ID;
- different price/volume/timestamp/symbol → different ID;
- permutation of otherwise identical rows → same canonical ID;
- identical duplicate diagnostics;
- conflicting duplicate rejection;
- missing-bar diagnostics;
- invalid/non-closed/non-UTC bar rejection;
- no NaN/Infinity;
- deterministic manifest serialization.

---

## Batch 2 — Walk-forward protocol

Implement explicit protocol types, for example:

- `EXPANDING`;
- `ROLLING`.

Each split must expose:

- context/train start/end;
- test start/end;
- warm-up requirement;
- test bar count;
- symbol coverage;
- split ID.

The evaluator must reuse existing deterministic replay and backtest semantics.

A reasonable default research protocol can be defined in bars rather than calendar assumptions, for example:

- warm-up/context bars sufficient for all feature histories;
- test windows non-overlapping by default;
- optional rolling context length;
- no future overlap into earlier decisions.

No optimizer is allowed.

Acceptance tests:

- exact split boundaries;
- insufficient-history rejection;
- no overlapping test windows unless explicitly configured;
- deterministic split IDs;
- same input → same window outputs;
- decision at `t` cannot consume `t+1` evidence;
- changing future test bars cannot change earlier window decisions.

---

## Batch 3 — Regime analysis

Add deterministic causal regime labels.

Prefer simple explainable labels derived from past-only data, such as:

- trend direction/strength from existing past-only indicators;
- volatility bucket from trailing realized volatility versus trailing historical distribution;
- liquidity/spread bucket where data exists.

Do not use future-window outcomes to define a regime.

Every report must disclose the exact regime rule and minimum sample threshold.

Metrics should include at least:

- eligible-decision count;
- evaluated outcome count;
- incomplete count;
- net return/PnL distribution summary under existing virtual assumptions;
- hit rate with sample count;
- drawdown where portfolio evaluation applies;
- cost drag;
- confidence distribution;
- composite-score distribution.

Confidence must remain described as evidence/agreement quality, **not probability of profit**.

Acceptance tests:

- causal labels invariant to future data changes;
- deterministic bucket assignment;
- minimum-sample warning behavior;
- empty/sparse regime handling;
- no divide-by-zero/NaN output;
- symbol aggregation is deterministic.

---

## Batch 4 — Cost/slippage sensitivity

Evaluate the same fixed decisions under a bounded set of deterministic cost scenarios.

The grid may vary only execution-assumption inputs already modeled by the offline evaluator, such as:

- fee bps per side;
- adverse slippage bps per side.

Do not vary strategy thresholds, indicator periods, portfolio sizing or decision gates in this batch.

Report:

- scenario ID;
- assumptions;
- total cost drag;
- net-vs-gross difference;
- outcome-count stability;
- drawdown/equity effect where applicable;
- sensitivity flags when conclusions materially change.

Never rank scenarios as “best trading setup”.

Acceptance tests:

- zero-cost scenario reconciles with gross math;
- higher adverse costs never improve an otherwise identical trade’s net result;
- decision identities remain unchanged across cost scenarios;
- only cost-derived metrics change;
- deterministic scenario IDs.

---

## Batch 5 — Validation report and statistical hygiene

Create a deterministic `ValidationReport` containing:

- dataset identity/manifest;
- engine versions/settings identities;
- protocol identity;
- split summaries;
- per-symbol metrics;
- per-regime metrics;
- cost sensitivity table;
- aggregate metrics;
- warnings;
- report identity;
- generated-at timestamp kept separate from content identity where needed.

Statistical hygiene requirements:

- always show sample counts;
- distinguish in-sample/context from out-of-sample/test;
- do not present hit rate as probability of future profit;
- do not present backtest fit as forecast;
- flag small samples;
- avoid a single opaque “AI score” or “profitability score”;
- if confidence intervals are added, state their method and assumptions;
- no p-hacking / automated metric cherry-picking.

Add deterministic report export/check commands similar to existing dashboard contract checks.

---

## Batch 6 — Read-only API and dashboard

Add GET-only research surfaces, preferably no more than a small number of routes, such as:

- `/validation/status`;
- `/validation/latest`;
- `/validation/reports/{report_id}` only if bounded local report discovery is implemented safely.

No POST/run/optimize endpoint in Phase 10.

The browser must not start computational validation runs or financial actions.

Dashboard should show:

- dataset/protocol identity;
- number of walk-forward windows;
- test-period coverage;
- symbol coverage;
- regime breakdown;
- cost sensitivity;
- incomplete/missing-data warnings;
- confidence vs realized historical outcome as separate concepts;
- “Historical validation is not a prediction” explanation.

Simple mode: plain-language summaries.

Advanced mode: IDs, split boundaries, settings identities, exact assumptions, counts and diagnostics.

Add glossary terms for:

- Walk-forward validation;
- Out-of-sample;
- Regime;
- Cost sensitivity;
- Data leakage;
- Dataset identity;
- Sample size.

Always retain `PAPER / VIRTUAL ONLY`.

---

## Batch 7 — Robustness, performance and final validation

Run:

1. targeted dataset tests;
2. targeted split/no-lookahead tests;
3. regime tests;
4. cost-sensitivity tests;
5. report/API tests;
6. frontend tests/build;
7. complete backend suite;
8. `pip check`;
9. generated contract/example checks;
10. `git diff --check`;
11. source audit confirming no prohibited integrations.

Create at least one deterministic medium-size validation fixture large enough to cross multiple walk-forward windows and regimes while remaining practical for CI.

Add a larger local release-validation tool if needed, but keep ordinary CI bounded and offline.

Final report:

`docs/PHASE_10_REPORT.md`

The report must contain exact test counts, runtime, dataset identities, protocol settings, no-lookahead evidence, regime/cost-sensitivity evidence, known limitations and repository status.

---

## Definition of done

Phase 10 is complete only if:

- fixed strategies are evaluated across deterministic out-of-sample windows;
- future-data mutation cannot alter earlier decisions/regime labels;
- dataset identity/provenance is reproducible;
- gaps/conflicts are visible and never repaired silently;
- regime metrics are causal and sample-counted;
- cost sensitivity changes costs, not decisions;
- reports are deterministic/content-addressed;
- API remains GET-only;
- frontend remains presentation-only;
- full backend/frontend suites pass;
- CI is offline and green;
- no private/account/live-execution/AI/optimizer integration appears.

Final signal:

`PHASE 10 READY FOR REVIEW`
