# Current Codex Task — Phase 10: Research Validation Lab

## Working branch

`phase-10-validation-lab`

## Accepted base

Current implementation status: **Batches 1–7 complete; ready for review.**
See [`docs/PHASE_10_REPORT.md`](docs/PHASE_10_REPORT.md) for the accepted baseline,
contracts, exact final regression results, file inventory and limitations.
All final release gates passed. No commit, push, merge or Phase 11 work was performed.

Phase 9 is fully merged and green on `main` at:

`2925f38d6423c28e92a39c9758766112bd197714`

Accepted GitHub Actions baseline:

- backend: **2410 passed, 2 existing dependency warnings**;
- frontend: **77 passed**;
- `pip check`: clean;
- TypeScript/Vite build: passed;
- generated dashboard contracts/examples: reproducible;
- all 19 HTTP paths: GET-only.

Before editing, confirm this branch is based exactly on that main SHA and run the baseline unless an uninterrupted prior run already proves it.

Read first:

- `AGENTS.md`;
- `docs/PHASE_10_VALIDATION_SPEC.md`;
- `docs/PHASE_9_REPORT.md`;
- `docs/ARCHITECTURE.md`;
- `docs/MODULE_MAP.md`;
- `docs/USER_GUIDE.md`.

Inspect the existing Phase 6 historical replay/backtest, Phase 7 portfolio evaluator, Phase 8 live analytical pipeline, Phase 9 persistence boundaries, contract exporter and frontend research pages before designing new modules.

---

# Objective

Build a deterministic **Research Validation Lab** around the existing fixed strategy/decision/backtest stack.

Phase 10 must answer:

> Do the current fixed analytical rules behave consistently across chronological out-of-sample windows, symbols, causal market regimes and plausible cost assumptions?

It must **not** answer this by fitting parameters to maximize historical returns.

This phase remains **PAPER / VIRTUAL / RESEARCH ONLY**.

---

# Deliverables

1. Canonical reproducible historical dataset manifest/identity.
2. Deterministic rolling/expanding walk-forward protocol.
3. Causal regime segmentation with sample-counted metrics.
4. Fee/slippage sensitivity using fixed decisions.
5. Content-addressed deterministic validation reports.
6. GET-only API projection and explainable frontend Validation view.
7. No-lookahead, reproducibility and robustness tests plus final report.

Full requirements are authoritative in:

`docs/PHASE_10_VALIDATION_SPEC.md`

---

# Hard boundaries

Do NOT add:

- private/account exchange endpoints;
- credentials/signing/API secrets;
- real or testnet orders;
- deposits/withdrawals/transfers/P2P transaction automation;
- leverage/margin execution;
- real liquidation;
- browser financial controls;
- TradeIntent / ApprovedTradeIntent from validation flows;
- RiskEngine / PaperExecutionGateway invocation from validation flows;
- AI/OpenAI provider calls;
- ML/RL;
- automatic parameter optimization;
- grid/random/Bayesian strategy search;
- return-based parameter fitting;
- automatic “best strategy/settings” selection;
- cloud experiment storage;
- fabricated/forward-filled historical bars.

Public historical market data may only be handled as public research data. CI must remain completely offline.

---

# Scientific invariants

## No lookahead

A decision/regime label at `t` may depend only on data available by `t`.

Changing future test bars must not change earlier:

- features;
- strategy scores;
- decisions;
- regime labels;
- portfolio actions.

## No hidden fitting

Validation may split, replay and summarize fixed settings. It may not modify settings based on test outcomes.

## Missing means missing

Gaps/conflicts must be explicit. Never fabricate, forward-fill or substitute newest prices.

## Reproducibility

Same canonical dataset + protocol + engine/settings identities + cost assumptions must produce identical report content identity.

---

# Implementation batches

## Batch 1 — dataset contracts and identity

Implement canonical dataset validation/manifest/codec.

Must cover:

- finalized bars only;
- UTC aware timestamps;
- deterministic `(boundary, symbol)` ordering;
- exact Decimal preservation;
- dataset SHA-256/content identity;
- gap diagnostics;
- identical duplicate diagnostics;
- conflicting duplicate rejection;
- no silent repair.

Run focused tests and report exact count before continuing.

## Batch 2 — walk-forward protocol

Implement explicit `ROLLING` and `EXPANDING` protocols around existing historical replay.

Requirements:

- deterministic split IDs;
- context/warmup separated from test;
- chronological non-overlapping test windows by default;
- insufficient-history rejection;
- no future evidence;
- existing Phase 6 entry/exit semantics unchanged;
- no strategy parameter search.

Add a future-mutation regression proving earlier outputs do not change.

## Batch 3 — causal regime analysis

Add explainable past-only regime labels.

At minimum support meaningful partitions such as:

- trend/range;
- low/medium/high trailing volatility;
- optional liquidity/spread bucket only where evidence exists.

Every metric must include sample counts and sparse-sample warnings.

Do not present confidence or historical hit rate as probability of profit.

## Batch 4 — cost/slippage sensitivity

Re-evaluate identical decisions across bounded fee/slippage scenarios.

Only execution-cost assumptions may vary.

Strategy/feature/decision/portfolio settings stay fixed.

Prove:

- decision identities unchanged;
- higher adverse costs cannot improve the same trade's net result;
- zero-cost reconciles with gross math;
- cost scenario IDs deterministic.

## Batch 5 — deterministic validation report

Create a versioned report with:

- dataset manifest/ID;
- engine/settings identities;
- protocol/split IDs;
- per-window metrics;
- per-symbol metrics;
- per-regime metrics;
- cost sensitivity;
- missing/incomplete diagnostics;
- warnings;
- report ID.

Generated-at time must not make otherwise identical report content nondeterministic.

Do not create an opaque profitability/AI score.

## Batch 6 — GET-only API + frontend

Add minimal read-only validation telemetry.

Preferred surfaces:

- `/validation/status`;
- `/validation/latest`;
- optionally bounded report lookup if justified.

No POST/run/optimize endpoint.

Frontend must explain:

- walk-forward;
- out-of-sample;
- regime;
- cost sensitivity;
- sample size;
- data leakage;
- dataset identity;
- historical validation is not a prediction.

Simple/Advanced remains presentation-only.

Always retain `PAPER / VIRTUAL ONLY`.

## Batch 7 — final robustness validation

Run targeted suites, then full backend/frontend.

Required final checks:

```text
python -m pytest
python -m pip check
python scripts/export_dashboard_contract.py --check
python tests/export_dashboard_examples.py --check
npm ci
npm run types
npm test
npm run build
git diff --check
```

Also explicitly audit:

- no lookahead/future mutation;
- deterministic dataset/report identities;
- no optimizer/ML/AI/private/live execution integration;
- GET-only API;
- bounded report/data retention if local report storage is added;
- no network dependency in CI.

Create:

`docs/PHASE_10_REPORT.md`

End with exactly:

`PHASE 10 READY FOR REVIEW`

or

`PHASE 10 NOT READY`

with exact blockers.

Do not commit/push/merge the implementation automatically. Do not start Phase 11.
