# Current Codex Task — Phase 5: DecisionEngine

## Implementation status

Phase 5 is complete on `phase-5-decision-engine`. All five batches are finished.
Baseline: **1469 passed, 2 warnings in 4.92s**. Final complete backend regression:
**1645 passed, 2 warnings in 5.90s**, including **176 Phase 5 tests**. Dependency,
import/OpenAPI, offline lifecycle, scope and whitespace checks passed.
See `docs/PHASE_5_REPORT.md` for exact rules, commands, results and limitations.
No Phase 6 work, commit or push was performed. Changes remain uncommitted for review.

Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/PHASE_4_REPORT.md`, and the implemented Phase 4 strategy code completely before editing.

## Model workflow
This task is written for **GPT-6 Astra in Codex**. Inspect before editing, work in small reviewable batches, run targeted tests after each batch, then run the complete backend suite. Do not perform a broad repository rewrite.

The working branch is `phase-5-decision-engine`. Phase 4 has been merged into `main` and the accepted baseline is **1469 backend tests passing**.

## Objective
Build an exchange-independent, deterministic **DecisionEngine** that consumes typed `StrategySnapshot` / `StrategyCandidate` output from Phase 4 and produces an immutable, explainable **decision eligibility record** for future paper/backtest orchestration.

Architecture:

```text
MarketDataHub
    -> FeatureEngine
    -> FeatureSnapshot
    -> StrategyEngine
    -> StrategySnapshot / StrategyCandidate
    -> DecisionEngine
    -> DecisionRecord (ELIGIBLE / BLOCKED / NO_ACTION)
    -> future sizing + deterministic RiskEngine
    -> future paper execution only
```

Phase 5 is still **analysis/simulation oriented**. `ELIGIBLE` means only that a strategy candidate passed deterministic decision-policy checks and may be considered by a later sizing/risk layer. It does **not** mean an order is approved or executable.

## Critical architectural boundary
The repository already contains Phase 1 `TradeIntent`, `ApprovedTradeIntent`, `RiskEngine`, and `PaperExecutionGateway` contracts. `TradeIntent` requires a concrete quantity, and `RiskEngine` is the authority that can approve an intent. Phase 5 must not invent sizing merely to bridge to those types.

Therefore Phase 5 must **not create `TradeIntent` or `ApprovedTradeIntent`** and must not call `RiskEngine` or any execution gateway.

The intended later boundary is:

```text
DecisionRecord(ELIGIBLE)
    -> future deterministic sizing / intent builder
    -> TradeIntent
    -> RiskEngine
    -> ApprovedTradeIntent
    -> PaperExecutionGateway
```

Do not collapse those steps.

## Non-negotiable boundaries
Do not add:
- private Binance streams,
- account balances or positions,
- Binance API keys or secrets,
- order submission,
- testnet order submission,
- live-money execution,
- direct or indirect `ExecutionGateway` / `PaperExecutionGateway` calls,
- `TradeIntent` generation,
- `ApprovedTradeIntent` generation,
- quantity sizing,
- leverage,
- margin logic,
- stop-loss/take-profit order placement,
- RiskEngine bypass or RiskEngine approval inside DecisionEngine,
- AI Advisor or OpenAI API,
- ML/RL prediction models,
- automatic parameter optimization,
- persistent database/Redis,
- frontend redesign,
- reconstructed full order book.

No DecisionEngine method may submit, route, simulate, or approve an order.

## Baseline first
Before editing:
1. confirm `git branch --show-current` is `phase-5-decision-engine`;
2. confirm `git status` is clean except for this task-file commit already pulled from the branch;
3. run the complete existing backend suite;
4. inspect at minimum:
   - `backend/src/domain/strategies.py`
   - `backend/src/application/strategy_engine.py`
   - `backend/src/application/strategy_settings.py`
   - `backend/src/strategies/identity.py`
   - `backend/src/domain/models.py`
   - `backend/src/application/risk_engine.py`
   - `backend/src/infrastructure/paper_execution.py`
   - Phase 4 strategy tests
   - `docs/ARCHITECTURE.md`
   - `docs/PHASE_4_REPORT.md`.

Do not redesign Phase 1–4 unless a small compatibility change is clearly required and independently tested.

## Core design principles
1. Deterministic and reproducible decision policy.
2. Consume typed Phase 4 strategy output only; no Binance-specific imports.
3. DecisionEngine is a policy gate, not a strategy and not a risk engine.
4. Preserve Phase 4 score/confidence semantics; confidence is evidence quality, not win probability.
5. Every blocked/no-action outcome must expose explicit stable reason codes.
6. No look-ahead behavior.
7. No hidden network or wall-clock side effects in pure evaluation.
8. On-demand evaluation is preferred; do not add a polling task.
9. Stable identities must make repeated evaluation of the same analytical observation idempotent for downstream consumers.
10. Invalid/stale/mismatched input must fail closed.
11. Configuration is typed, validated, and conservative.
12. Tests are deterministic and offline.
13. No profitability or performance claims.

## Required domain concepts
Create immutable typed models. Prefer semantics close to:

```text
DecisionOutcome = ELIGIBLE | BLOCKED | NO_ACTION
DecisionReadiness = READY | STALE | UNAVAILABLE

DecisionReason
- code
- detail/context fields only if bounded and non-sensitive

DecisionRecord
- decision_id
- symbol
- generated_at
- source_strategy_timestamp
- strategy_snapshot_id
- observation_id
- candidate_id (nullable for NO_ACTION)
- direction (nullable/neutral for NO_ACTION/BLOCKED as appropriate)
- outcome
- readiness
- composite_score (nullable when no candidate)
- confidence (nullable when no candidate)
- agreement (nullable when unavailable)
- contributing_strategies
- reasons
- policy_id / engine_version

DecisionSymbolStatus
DecisionEngineStatus
```

Names may be adjusted after repository inspection, but preserve these semantics.

`DecisionRecord` must contain **no quantity, leverage, price, order type, stop/take-profit, execution mode, API credential, or execution method**.

## Outcome semantics
Use clear semantics:

### NO_ACTION
Use when there is no Phase 4 candidate to consider, for example:
- StrategySnapshot is valid but neutral,
- aggregate thresholds were not met,
- no candidate exists by Phase 4 design.

NO_ACTION is not an error and must remain distinguishable from BLOCKED.

### BLOCKED
Use when a candidate exists but DecisionEngine refuses eligibility because one or more decision-policy checks fail, for example:
- stale/future strategy snapshot,
- inconsistent candidate/snapshot identity,
- insufficient agreement,
- insufficient number of agreeing contributors,
- invalid/malformed candidate data,
- unsupported symbol/direction,
- policy-specific conservative gate failure.

### ELIGIBLE
Use only when:
- StrategySnapshot is READY,
- a coherent candidate exists,
- freshness checks pass,
- identity checks pass,
- configured decision-policy gates pass.

ELIGIBLE is an analytical eligibility result only. It must never be called `approved_trade`, `approved_order`, or similar.

## Decision policy
Create a small transparent deterministic policy on top of Phase 4 consensus.

Suggested conservative defaults:

```text
MAX_STRATEGY_SNAPSHOT_AGE_SECONDS=10
MIN_DECISION_AGREEMENT=0.50
MIN_CONTRIBUTING_STRATEGIES=2
BLOCK_INCOMPLETE_STRATEGY_COVERAGE=false
```

You may add a small number of other policy settings only if clearly justified by the existing Phase 4 semantics.

Avoid duplicating Phase 4's entire scoring model. Phase 4 already owns candidate score/confidence thresholds. DecisionEngine should primarily validate freshness, coherence, agreement, contributor coverage, and orchestration eligibility.

If you decide to add independent minimum score/confidence gates, document why they are not redundant and validate them carefully. Prefer not to unless needed.

### Contributor policy
`contributing_strategies` must be unique and already supplied by the Phase 4 candidate. A configurable minimum contributor count may be used to prevent a single rule family from becoming action-eligible by itself.

Do not treat the three strategies as statistically independent votes. The contributor-count gate is only an engineering policy.

### Agreement policy
Use Phase 4's existing bounded agreement value. Do not reinterpret it as a probability.

Default eligibility should require `agreement >= MIN_DECISION_AGREEMENT`.

### Incomplete strategy coverage
Phase 4 may produce a candidate with some strategies unavailable. Expose whether `incomplete_strategy_coverage` was present in the source reasons.

Default behavior may allow it while preserving the reason, unless `BLOCK_INCOMPLETE_STRATEGY_COVERAGE=true`.

Do not silently discard this provenance.

## Freshness and timestamp validation
DecisionEngine must independently validate the StrategySnapshot at the service boundary.

At minimum:
- timestamps must be timezone-aware,
- generated time cannot precede source strategy/feature time where contracts require ordering,
- future timestamps must be blocked/stale,
- snapshot age must be strictly within the configured maximum,
- candidate generated time / snapshot identity must match the containing StrategySnapshot,
- candidate observation identity must match the StrategySnapshot,
- decision evaluation time must be explicit for pure tests.

Pure `evaluate(snapshot, now=...)` must be reproducible for the same snapshot, policy and explicit `now`.

`latest(symbol)` may use an injected clock, as StrategyEngine already does.

## Deterministic identity / deduplication contract
Phase 4 already provides deterministic `snapshot_id`, `observation_id`, `candidate_id`, and `settings_id`.

Create deterministic Phase 5 identity such as:

```text
decision_id = hash(
    decision_engine_version,
    decision_policy_id,
    observation_id,
    candidate_id or NO_ACTION marker,
    outcome
)
```

Exact canonicalization should reuse or carefully extend the existing stable identity helper rather than invent random UUIDs.

Requirements:
- repeated equivalent analytical observation + same policy -> same decision ID,
- a mere later API read must not create a new actionable identity,
- changed observation -> changed decision identity,
- changed policy/settings -> changed policy ID and decision identity,
- changed outcome -> changed decision identity.

Do not add persistent deduplication in Phase 5. Stable identities are the contract that future paper orchestration can use to avoid repeated action.

If process-local caching is added for performance, keep it bounded and never make correctness depend on it. Prefer no cache initially.

## Suggested structure
Prefer something close to:

```text
backend/src/
  domain/
    decisions.py
  application/
    decision_engine.py
    decision_settings.py
  api/
    decisions.py
```

A small shared decision identity/policy helper module is acceptable if it keeps the service clearer.

Do not create a large orchestration framework in this phase.

## DecisionEngine behavior
Prefer an injected protocol:

```text
StrategyProvider.latest(symbol) -> StrategySnapshot
```

DecisionEngine should:
1. validate a typed StrategySnapshot at its boundary;
2. classify NO_ACTION / BLOCKED / ELIGIBLE;
3. preserve source score/confidence/agreement without modifying them;
4. apply only explicit decision-policy gates;
5. produce deterministic DecisionRecord identity;
6. never call lower-level FeatureEngine, Binance, RiskEngine, or execution directly.

On-demand evaluation is preferred:

```text
StrategyEngine.latest(symbol)
    -> DecisionEngine.evaluate(...)
```

No DecisionEngine background task or subscriber is needed.

## API
Add read-only endpoints such as:
- `GET /decisions/status`
- `GET /decisions/{symbol}/latest`

Responses should expose:
- source strategy identity,
- decision identity,
- outcome/readiness,
- direction if applicable,
- source score/confidence/agreement,
- contributors,
- stable reason codes,
- policy/engine version.

Unknown symbol -> 404.
Before initialization -> 503 if applicable.
No POST/PUT/PATCH/DELETE decision action endpoint.
No endpoint may trigger RiskEngine or execution.

## Lifecycle integration
Construct DecisionEngine over the existing StrategyEngine in FastAPI lifespan/state.

It should not add a task:

```text
FeatureEngine task (existing)
StrategyEngine on-demand (existing)
DecisionEngine on-demand (new)
```

Import must remain side-effect free.
Existing startup/shutdown subscriber counts and tasks must remain unchanged.

## Relationship to Phase 1 RiskEngine
Inspect existing Phase 1 code and document the boundary, but do not wire it in Phase 5.

Important distinctions:
- DecisionEngine: candidate eligibility / orchestration policy.
- future sizing layer: chooses a simulation quantity under explicit constraints.
- RiskEngine: deterministic pre-execution guard for a concrete `TradeIntent`.
- PaperExecutionGateway: simulated fill only after RiskEngine approval.

DecisionEngine must not duplicate or weaken RiskEngine checks such as quantity limits or execution enable/disable state.

Do not modify Phase 1 `RiskLimits` just to make Phase 5 fit.

## Numerical and validation safety
Guard/reject:
- NaN/Infinity,
- score/confidence/agreement outside typed bounds,
- duplicate contributor IDs,
- candidate/snapshot mismatches,
- symbol mismatches,
- unsupported/neutral candidate direction,
- naive timestamps,
- future/stale timestamps,
- inconsistent observation IDs,
- impossible outcome/value combinations,
- malformed validation-bypassing model copies.

Do not silently turn invalid candidates into ELIGIBLE.

For a malformed external/service-boundary object, prefer fail-closed BLOCKED/UNAVAILABLE where a safe record can be produced; raise only where the existing repository contract clearly treats malformed typed input as programmer error. Test and document the distinction.

## Testing requirements
Add comprehensive deterministic offline tests.

### Domain/settings
Test:
- immutable decision models,
- extra-field rejection,
- outcome coherence,
- no executable/order fields,
- settings ranges,
- agreement threshold boundaries,
- contributor count bounds,
- deterministic serialization/identity,
- NaN/Infinity rejection.

### Pure DecisionEngine evaluation
Test at minimum:
- ready candidate -> ELIGIBLE,
- neutral StrategySnapshot/no candidate -> NO_ACTION,
- stale snapshot with candidate -> BLOCKED,
- future snapshot -> BLOCKED,
- candidate snapshot-ID mismatch -> blocked/rejected safely,
- candidate observation-ID mismatch,
- candidate symbol mismatch,
- direction mismatch,
- agreement exactly at threshold,
- agreement just below threshold,
- contributor count exactly at threshold,
- contributor count below threshold,
- one contributor duplicate / malformed,
- incomplete coverage allowed by default with preserved reason,
- incomplete coverage blocked when configured,
- repeated equivalent evaluation -> same decision ID,
- changed observation -> changed decision ID,
- changed policy -> changed policy/decision ID,
- later API read over same observation does not invent a new actionable ID,
- explicit clock reproducibility,
- symbol isolation.

### Interaction with StrategyEngine
Use actual deterministic Phase 4 fixtures/output for integration tests:
- strong consensus candidate can become ELIGIBLE,
- weak/conflicted/no-candidate source becomes NO_ACTION,
- stale Phase 4 output becomes BLOCKED,
- DecisionEngine does not mutate StrategySnapshot,
- no FeatureEngine/Binance imports required by DecisionEngine core.

### API/lifecycle
Test:
- `/decisions/status`,
- `/decisions/{symbol}/latest`,
- unknown symbol 404,
- before-init 503 if applicable,
- GET-only routes / mutation returns 405,
- OpenAPI path list,
- import side-effect free,
- offline lifespan smoke,
- no new runtime task,
- zero new subscribers after shutdown,
- Phase 1–4 regression tests remain intact.

### Scope/security regression
Add explicit tests or review assertions showing:
- DecisionRecord has no quantity/leverage/order fields,
- DecisionEngine never constructs `TradeIntent`,
- DecisionEngine never imports/calls `RiskEngine`,
- DecisionEngine never imports/calls `PaperExecutionGateway`,
- no private Binance/account API is introduced.

Use fixed fixtures and independent expected outputs. Do not calculate expected decision outcomes by calling the same production policy helper under test.

## Documentation
Update:
- `CODEX_TASK.md`,
- `docs/ARCHITECTURE.md`,
- `backend/README.md`,
- root README only if needed.

Create `docs/PHASE_5_REPORT.md` at completion.

Document:
- DecisionEngine purpose,
- ELIGIBLE/BLOCKED/NO_ACTION semantics,
- exact policy defaults,
- freshness rules,
- contributor/agreement gates,
- incomplete-coverage behavior,
- identity/deduplication contract,
- StrategyEngine -> DecisionEngine boundary,
- DecisionEngine -> future sizing/RiskEngine boundary,
- why no `TradeIntent` is created,
- API endpoints,
- limitations,
- why `confidence` is not probability,
- no profitability claim.

## Development batches
### Batch 1 — contracts/settings/identity
- decision domain models,
- typed settings,
- deterministic policy/decision identity,
- targeted tests.

### Batch 2 — DecisionEngine policy
- StrategyProvider protocol,
- pure `evaluate`,
- NO_ACTION / BLOCKED / ELIGIBLE policy,
- freshness/coherence checks,
- targeted tests.

### Batch 3 — StrategyEngine integration and edge cases
- real typed StrategySnapshot integration,
- contributor/agreement/incomplete-coverage policy,
- malformed/stale/future cases,
- deterministic repeated identity,
- targeted tests.

### Batch 4 — read-only Decision API
- `/decisions/status`,
- `/decisions/{symbol}/latest`,
- app factory/state integration,
- no new task,
- targeted API/lifecycle tests.

### Batch 5 — documentation and full regression
- report/docs,
- scope/security review,
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
- offline lifespan smoke test,
- `git diff --check`,
- `git status`,
- `git diff --stat`.

Perform a final source scan for accidental imports/references to:
- `TradeIntent`,
- `ApprovedTradeIntent`,
- `RiskEngine`,
- `PaperExecutionGateway`,
- Binance private/account/order endpoints,
inside newly added Phase 5 production modules. Documentation/tests may mention them only to verify the boundary.

Do not commit or push automatically.

## Acceptance criteria
Phase 5 is complete only when:
1. DecisionEngine consumes typed Phase 4 StrategySnapshot output.
2. It is deterministic and exchange-independent.
3. It produces typed immutable DecisionRecord output.
4. Outcomes distinguish ELIGIBLE, BLOCKED, and NO_ACTION.
5. Candidate freshness/identity/coherence are independently checked.
6. Agreement/contributor policy is explicit, bounded, and tested.
7. Same analytical observation + same policy yields stable decision identity.
8. Repeated API reads do not invent new actionable identities.
9. DecisionEngine creates no `TradeIntent` or `ApprovedTradeIntent`.
10. DecisionEngine has no quantity/leverage/order fields or sizing logic.
11. DecisionEngine does not call RiskEngine or execution gateways.
12. No AI/private/account/order API is added.
13. No new background task/subscription is introduced.
14. All existing **1469** baseline tests still pass.
15. New Phase 5 tests pass.
16. Documentation and `docs/PHASE_5_REPORT.md` are complete.

## Completion report
At the end report:
- exact baseline result,
- files created,
- files modified,
- decision domain models,
- settings/defaults,
- exact policy rules,
- outcome semantics,
- freshness rules,
- contributor/agreement policy,
- incomplete-coverage behavior,
- identity/dedup contract,
- StrategyEngine integration,
- API endpoints,
- lifecycle behavior,
- exact targeted test results,
- exact complete test result,
- warnings,
- intentionally deferred work,
- remaining technical risks,
- `git status`,
- `git diff --stat`.

Do not commit or push until reviewed.
