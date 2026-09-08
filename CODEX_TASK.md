# Current Codex Task — Phase 4: StrategyEngine

Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/PHASE_3_REPORT.md`, and the implemented Phase 3 feature code completely before editing.

## Model workflow
This task is written for **GPT-6 Astra in Codex**. Inspect before editing, work in small reviewable batches, run targeted tests after each batch, then run the complete backend suite. Do not perform a broad repository rewrite.

The working branch is `phase-4-strategy-engine`. Phase 3 has been merged into `main` and the accepted baseline is **1106 backend tests passing**.

## Objective
Build an exchange-independent, deterministic **StrategyEngine** that consumes typed `FeatureSnapshot` objects from Phase 3 and produces explainable strategy assessments suitable for future backtesting and paper-trading orchestration.

Architecture:

```text
MarketDataHub
    -> FeatureEngine
    -> FeatureSnapshot
    -> StrategyEngine
    -> StrategyAssessment / StrategyCandidate
    -> future DecisionEngine / RiskEngine integration
```

Phase 4 is **analysis and simulation oriented only**. StrategyEngine must never directly reach an ExecutionGateway.

## Non-negotiable boundaries
Do not add:
- private Binance streams,
- account balances or positions,
- Binance API keys,
- order submission,
- testnet order execution,
- live-money execution,
- direct calls to `PaperExecutionGateway`,
- TradeIntent generation,
- RiskEngine bypass,
- AI Advisor or OpenAI API,
- ML/RL prediction models,
- automatic parameter optimization,
- persistent database/Redis,
- frontend redesign,
- full local order-book reconstruction.

No strategy may submit, place, simulate, or route an order by itself.

## Baseline first
Before editing:
1. confirm `git branch --show-current` is `phase-4-strategy-engine`;
2. confirm `git status`;
3. run the complete existing backend suite;
4. inspect at minimum:
   - `backend/src/domain/features.py`
   - `backend/src/application/feature_engine.py`
   - `backend/src/application/feature_settings.py`
   - `backend/src/domain/models.py`
   - all Phase 3 feature tests
   - `docs/ARCHITECTURE.md`
   - `docs/PHASE_3_REPORT.md`.

Do not redesign Phase 1–3 unless a small compatibility change is clearly required and independently tested.

## Core design principles
1. Deterministic and reproducible strategy logic.
2. Strategy code consumes typed Phase 3 features only; it must not import Binance-specific payload types.
3. Every assessment must be explainable from explicit numerical evidence.
4. Missing/stale/unavailable required feature groups make that strategy unavailable, not guessed.
5. Strategy outputs are analytical candidates, not execution commands.
6. No look-ahead bias.
7. No hidden mutable global state.
8. Configuration is typed and validated.
9. Strategy scoring must be bounded and documented.
10. Avoid magic thresholds scattered through code; centralize them in strategy settings.
11. No performance claims or profitability claims.
12. Tests must be deterministic and offline.

## Required domain model
Create immutable typed strategy-domain models. Prefer a structure close to:

```text
StrategyDirection = LONG | SHORT | NEUTRAL
StrategyReadiness = READY | UNAVAILABLE | STALE | WARMING_UP

StrategyEvidence
- name
- value
- threshold/reference if relevant
- contribution
- note/code

StrategyAssessment
- strategy_id
- symbol
- generated_at
- direction
- score
- confidence
- readiness
- reasons
- required_feature_groups
- evidence
- source_feature_timestamp / snapshot identity

StrategyCandidate
- candidate_id
- symbol
- generated_at
- direction
- composite_score
- confidence
- contributing_strategies
- reasons/evidence summary
```

You may adjust names after inspecting the repository, but preserve the semantic separation between:
- one strategy's assessment,
- optional engine-level aggregation.

`StrategyCandidate` is **not** a `TradeIntent`, must not contain quantity/leverage/order type, and must not be executable.

Use a bounded score convention such as `[-100, 100]` and confidence `[0, 1]`. Validate both.

## Strategy set
Implement a small, diverse deterministic initial strategy set using only existing Phase 3 features.

Prefer these three families:

### 1. Trend-following strategy
Use numerical evidence such as:
- EMA fast/slow/long relationships,
- normalized EMA separation,
- distance from EMA,
- directional efficiency,
- ROC,
- normalized ATR as context.

The strategy should reward aligned trend evidence and penalize contradictory evidence.

Do not treat one EMA crossover alone as sufficient evidence.

### 2. Momentum/continuation strategy
Use numerical evidence such as:
- ROC,
- RSI,
- close-to-close momentum,
- relative volume,
- taker-buy ratio / volume delta proxy,
- spread/microstructure as optional quality context.

Avoid simplistic rules such as `RSI > 70 = buy` or `RSI < 30 = sell`.

The strategy should distinguish continuation evidence from exhausted/extreme conditions in a deterministic documented way.

### 3. Mean-reversion strategy
Use numerical evidence such as:
- price distance from fast/slow EMA,
- RSI deviation from neutral,
- normalized ATR,
- directional efficiency,
- relative volume,
- spread quality where available.

This strategy must not blindly oppose strong directional movement. Strong trend/efficiency should reduce or invalidate mean-reversion conviction.

## Optional fourth strategy
Only if the implementation remains small and well-tested, add a microstructure/context strategy based on:
- spread bps,
- top-of-book imbalance,
- taker-buy ratio,
- mark/index basis,
- funding context.

It must remain an analytical assessment and must not claim to reconstruct order-book pressure beyond top-of-book data.

Do not add this strategy merely to increase strategy count.

## Strategy readiness and feature dependencies
Each strategy must explicitly declare its required feature groups.

Examples:
- trend strategy: `trend`, `momentum`, `regime`, possibly `volatility`;
- momentum strategy: `momentum`, `volume`, possibly `microstructure`;
- mean reversion: `trend`, `momentum`, `volatility`, `regime`.

If any hard-required feature group is stale, warming up, unavailable, or has null values:
- do not fabricate a score,
- return an assessment with matching unavailable/readiness state and reasons.

Optional feature groups may improve confidence/quality but their absence must be explicitly documented.

A stale unrelated group must not invalidate a strategy that does not depend on it.

## Scoring model
Create a deterministic, auditable scoring framework.

Requirements:
- score is bounded,
- contribution from each feature is bounded,
- every contribution is represented in `StrategyEvidence`,
- score normalization is deterministic,
- confidence is derived from evidence completeness/strength, not random or AI-generated,
- neutral dead zones prevent tiny numerical noise from becoming directional candidates.

Prefer piecewise-linear or similarly simple functions over opaque formulas.

Create reusable pure helpers for:
- clamping,
- dead-zone normalization,
- signed threshold scoring,
- range/quality scoring if needed.

Do not tune thresholds against historical returns in Phase 4.

## Initial conservative defaults
Centralize thresholds in typed settings. Suggested starting points are engineering defaults, not claims of profitability.

Examples you may refine after inspecting actual feature units:

```text
MIN_ABSOLUTE_STRATEGY_SCORE=25
CANDIDATE_SCORE_THRESHOLD=40
MIN_CANDIDATE_CONFIDENCE=0.55
RSI_NEUTRAL_LOW=45
RSI_NEUTRAL_HIGH=55
RSI_EXTREME_LOW=30
RSI_EXTREME_HIGH=70
MAX_ACCEPTABLE_SPREAD_BPS=15
TREND_EFFICIENCY_FLOOR=0.25
STRONG_TREND_EFFICIENCY=0.55
RELATIVE_VOLUME_BASELINE=1.0
```

Do not blindly use these if units or Phase 3 semantics make a different value clearly more correct. Document any changes.

Validate ordering/ranges of thresholds.

## Aggregation / StrategyEngine
Implement a StrategyEngine that:
1. receives or reads a `FeatureSnapshot` without importing Binance infrastructure;
2. evaluates each configured deterministic strategy;
3. preserves individual assessments;
4. optionally aggregates only READY assessments;
5. produces a neutral/no-candidate result when evidence is weak or conflicting;
6. never turns a candidate into an executable intent.

For aggregation, prefer a transparent rule such as weighted consensus rather than hidden heuristics.

Requirements:
- opposing strategies must offset rather than both increasing confidence;
- confidence should decrease under strong disagreement;
- one unavailable strategy must not necessarily invalidate other independent ready strategies;
- no candidate if aggregate score/confidence thresholds are not satisfied;
- exact same FeatureSnapshot + settings must produce exactly the same output.

Avoid generating repeated random UUIDs if that would break deterministic equality tests. Candidate IDs may be derived deterministically from stable inputs (for example strategy engine version + symbol + feature generated_at + direction) or excluded until a later orchestration phase.

## No repeated signal spam
Phase 4 should not implement order execution or persistent deduplication, but the analytical API should make snapshot identity explicit so future orchestration can avoid repeated action on the same underlying feature snapshot.

If you add process-local latest-assessment caching, keep it bounded and do not make correctness depend on timing races.

## Suggested structure
Prefer something close to:

```text
backend/src/
  domain/
    strategies.py
  strategies/
    __init__.py
    scoring.py
    trend_following.py
    momentum.py
    mean_reversion.py
  application/
    strategy_engine.py
    strategy_settings.py
  api/
    strategies.py
```

Adjust only if the existing repository structure clearly suggests a cleaner layout. Explain deviations.

Keep strategy functions/classes pure where practical.

## Strategy API
Add read-only endpoints such as:
- `GET /strategies/status`
- `GET /strategies/{symbol}/latest`

The latest response should include:
- snapshot identity/time,
- individual strategy assessments,
- aggregate state,
- optional candidate if threshold requirements are satisfied.

Unknown symbols -> 404.
Before initialization -> 503.
No mutation/execution endpoints.

Do not add an endpoint that accepts arbitrary user feature values unless there is a strong testability reason. Prefer the actual FeatureEngine output as the source.

## Lifecycle integration
Integrate StrategyEngine with FeatureEngine without adding direct Binance coupling.

Prefer either:
- on-demand deterministic evaluation from the latest FeatureSnapshot, or
- a small bounded feature-snapshot subscription if the existing architecture makes that clearly cleaner.

On-demand is preferred unless continuous evaluation provides a demonstrated benefit.

Do not add polling loops merely to generate strategy scores repeatedly.

Importing the application must still produce no network/runtime side effects.

## Numerical safety
Guard against:
- NaN/Infinity,
- invalid confidence,
- score overflow,
- zero denominators,
- extreme feature magnitudes,
- contradictory thresholds,
- missing values,
- timestamp mismatch or stale snapshots.

Do not silently coerce invalid values into directional evidence.

## Testing requirements
Add comprehensive deterministic offline tests.

At minimum test:

### Domain/settings
- immutable models,
- score bounds,
- confidence bounds,
- invalid settings ordering/ranges,
- deterministic serialization.

### Scoring helpers
- clamp boundaries,
- positive/negative saturation,
- dead zone,
- exact threshold behavior,
- Decimal/float edge cases where relevant,
- NaN/Infinity rejection.

### Trend strategy
- strong aligned positive trend,
- strong aligned negative trend,
- contradictory EMA structure,
- low directional efficiency,
- neutral/dead-zone case,
- required stale/unavailable group.

### Momentum strategy
- positive continuation evidence,
- negative continuation evidence,
- extreme RSI reducing continuation confidence,
- weak/neutral volume,
- stale/missing required group,
- optional microstructure missing if optional.

### Mean-reversion strategy
- stretched positive distance with weak trend context,
- stretched negative distance with weak trend context,
- strong trend suppresses mean reversion,
- neutral/dead-zone case,
- stale/unavailable group.

### Engine aggregation
- all strategies agree positive,
- all agree negative,
- mixed disagreement,
- exact cancellation,
- one strategy unavailable,
- all unavailable,
- below score threshold,
- below confidence threshold,
- deterministic repeated evaluation,
- symbol isolation.

### API/lifecycle
- status response,
- latest per symbol,
- unknown symbol 404,
- initialization 503 if applicable,
- no mutation endpoint,
- app import side-effect free,
- Phase 1–3 regressions.

Use fixed feature snapshots and independent expected values. Do not compute expected strategy scores by calling the production scoring helper from the test.

## Documentation
Update:
- `CODEX_TASK.md`,
- `docs/ARCHITECTURE.md`,
- `backend/README.md`,
- root README only if needed.

Create `docs/PHASE_4_REPORT.md` at completion.

Document:
- each strategy's purpose,
- required/optional feature groups,
- exact formulas or piecewise scoring rules,
- thresholds/defaults,
- readiness semantics,
- aggregation/consensus logic,
- confidence calculation,
- candidate threshold rules,
- deterministic identity behavior,
- limitations,
- why assessments are not orders,
- why no profitability claim is made.

## Development batches
### Batch 1 — contracts and scoring primitives
- domain strategy models,
- typed settings,
- pure bounded scoring helpers,
- targeted tests.

### Batch 2 — individual strategies
- trend following,
- momentum/continuation,
- mean reversion,
- evidence/explanation output,
- targeted tests.

### Batch 3 — StrategyEngine aggregation
- consume FeatureSnapshot,
- evaluate strategies,
- consensus/conflict logic,
- optional analytical StrategyCandidate,
- deterministic behavior,
- targeted tests.

### Batch 4 — read-only Strategy API
- `/strategies/status`,
- `/strategies/{symbol}/latest`,
- app integration,
- targeted tests.

### Batch 5 — documentation and full regression
- docs/report,
- scope review,
- complete suite.

After each meaningful batch run targeted tests and fix failures before continuing.

## Completion commands
At minimum run from `backend`:

```bash
python -m pytest
python -m pip check
```

Also run:
- application import/OpenAPI check,
- appropriate offline lifespan smoke test,
- `git diff --check`,
- `git status`,
- `git diff --stat`.

Do not commit or push automatically.

## Acceptance criteria
Phase 4 is complete only when:
1. StrategyEngine consumes typed FeatureSnapshot data only.
2. Strategy logic is deterministic and exchange-independent.
3. At least trend, momentum, and mean-reversion strategies exist.
4. Each assessment exposes explicit evidence/contributions.
5. Required stale/unavailable features prevent directional scoring.
6. Strategy scores and confidence are bounded and validated.
7. Neutral/dead-zone behavior is explicit.
8. Aggregation handles agreement and disagreement transparently.
9. Any StrategyCandidate is analytical only and contains no executable order fields.
10. No TradeIntent or ExecutionGateway integration is added.
11. No AI provider is added.
12. No private/account data is added.
13. Existing 1106 baseline tests still pass.
14. New Phase 4 tests pass.
15. Documentation is complete.

## Completion report
At the end report:
- baseline exact test result,
- files created,
- files modified,
- strategy models,
- strategy settings/defaults,
- exact scoring formulas,
- feature dependency matrix,
- readiness rules,
- aggregation logic,
- confidence logic,
- analytical candidate rules,
- API endpoints,
- exact targeted test results,
- exact complete test result,
- warnings,
- intentionally deferred work,
- remaining technical risks.

Do not commit or push until reviewed.
