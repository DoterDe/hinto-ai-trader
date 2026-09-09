# Phase 5 — DecisionEngine

## Status and baseline

Complete on `phase-5-decision-engine`; final validation finished 2026-09-10.
**1645 passed, 2 warnings in 5.90s**. No Phase 6 work, commit or push.

Before editing, `git branch --show-current` confirmed the requested branch and
`git status` was clean. HEAD was `0205bee` (`chore: define Phase 5 decision engine
task`), following the Phase 4 merge. AGENTS.md, CODEX_TASK.md, architecture,
Phase 4 report, implemented strategy code and relevant tests were inspected,
along with the existing Phase 1 domain, risk and paper gateway contracts.

The complete existing backend suite passed before changes:
**1469 passed, 2 warnings in 4.92s**.

## Implemented architecture

```text
MarketDataHub -> FeatureEngine -> FeatureSnapshot
    -> StrategyEngine -> StrategySnapshot / StrategyCandidate
    -> DecisionEngine -> DecisionRecord (ELIGIBLE / BLOCKED / NO_ACTION)
```

DecisionEngine is an exchange-independent policy service over typed Phase 4
output. `StrategyProvider.latest(symbol) -> StrategySnapshot` is its only source
interface. It does not call lower-level features, market data, risk or execution.
The `evaluate(snapshot, now=...)` method requires explicit aware time and is pure;
`latest(symbol)` and `status()` use the provider and injected clock. No polling,
subscriber, task, cache, mutable history or durable storage is introduced.

The separate identity and boundary-validation helpers keep policy evaluation
small without changing Phase 4 scoring. All original production behavior is
preserved; the only existing production file changed is the additive app factory
and router integration in `main.py`. No dependencies changed.

## Domain and outcome semantics

Immutable Pydantic models comprise DecisionPolicy, DecisionReason, DecisionRecord,
DecisionSymbolStatus and DecisionEngineStatus. They forbid unknown fields,
revalidate instances and reject nonfinite/out-of-range numbers. DecisionRecord
retains symbol, source snapshot/observation/settings/version IDs, candidate ID,
source feature/strategy/evaluation times, direction, score/confidence/agreement,
contributors, coverage flag, reasons, policy ID and decision version/ID.

There are no quantity, leverage, price, order type, stop/take-profit, execution
mode, credential or executable method fields. Record validation enforces unique
contributors/reason codes, score/direction coherence, coverage flag/reason
agreement, no blocking reasons on ELIGIBLE/NO_ACTION, and a blocking reason for
BLOCKED. An ELIGIBLE record requires a ready candidate and successful-check code.

| Outcome | Readiness and meaning |
| --- | --- |
| `ELIGIBLE` | `ready`; coherent candidate passes all decision checks. Analytical eligibility only. |
| `NO_ACTION` | `ready` for valid neutral/below-threshold output; `unavailable` for fresh warming/unavailable output with no candidate. Not an error. |
| `BLOCKED` | `stale` for known stale/future timing; `unavailable` for malformed data without usable timing; `ready` can accompany a coherent candidate failing agreement/count/coverage policy or symbol scope. |

Fail-closed precedence is deliberate: invalid/stale/future/unsupported input is
BLOCKED even without a candidate. NO_ACTION is reserved for valid fresh
abstention. Warming sources map to decision readiness `unavailable` with
`source_warming_up`; the decision readiness enum has no separate warming state.

For valid candidates, policy/staleness blocking preserves supplied candidate ID,
direction, score, confidence, agreement and contributor order. Invalid candidates
are omitted with null score/confidence/agreement, neutral direction and no
contributors; unsafe numeric values are not echoed. A valid no-candidate record
has null score/confidence and retains agreement if available. The full original
aggregate remains accessible through the Strategy API.

## Exact policy and rules

These are the only four decision settings. They use the process environment at
lifespan startup, without automatic `.env` loading; explicit factory settings win.

| Setting / environment variable | Default | Valid range and rule |
| --- | --- | --- |
| `max_strategy_snapshot_age_seconds` / `DECISION_MAX_STRATEGY_SNAPSHOT_AGE_SECONDS` | `10` | Finite positive Decimal; each strategy/feature snapshot age must be strictly less. |
| `min_decision_agreement` / `DECISION_MIN_DECISION_AGREEMENT` | `0.50` | Decimal in `[0,1]`; Phase 4 agreement must be at least this value. |
| `min_contributing_strategies` / `DECISION_MIN_CONTRIBUTING_STRATEGIES` | `2` | Integer `[1,3]`; unique agreeing contributors must meet the minimum. |
| `block_incomplete_strategy_coverage` / `DECISION_BLOCK_INCOMPLETE_STRATEGY_COVERAGE` | `false` | Boolean; when true, incomplete source coverage blocks a candidate. |

Fractional counts, booleans in numeric fields, nonfinite numbers and unknown
settings are rejected. Environment count/boolean strings are parsed explicitly.
`0.50` agreement and exactly two contributors pass their respective defaults;
age exactly 10 seconds fails freshness. A zero configured agreement gate does
not make an incoherent zero-agreement candidate valid: Phase 4 candidate
provenance still requires positive agreement/confidence.

Evaluation proceeds in stable order:

1. Require explicit aware `now` and safe source identifiers.
2. Revalidate the typed StrategySnapshot and nested values, including malformed
   validation-bypassing copies. Check candidate coherence and provenance.
3. Preserve incomplete-coverage provenance and enforce configured symbol scope.
4. Check source timestamps, maximum ages, source readiness and candidate future time.
5. For a coherent fresh candidate, apply agreement, contributor count and optional
   incomplete-coverage blocking. Collect all failing policy gates in this order.
6. Emit the immutable outcome with unique stable reason codes and identity.

Phase 4 owns candidate score/confidence thresholds (defaults absolute score 40
and confidence 0.55). Phase 5 introduces no independent score/confidence cutoff
and does not rerun weighted aggregation. It validates typed bounds, positive
candidate confidence/agreement and `candidate_thresholds_met` provenance, rejecting
contradictory threshold-failure markers. Source numbers are preserved exactly.

Agreement retains Phase 4 net/gross directional consensus semantics. Confidence
is evidence quality, not win probability. Contributor count is an engineering
guard against one rule family qualifying alone, not statistically independent
votes. The supplied unique contributors must equal the READY, nonzero assessment
IDs with the same score sign as the candidate; assessment direction labels are
not substituted for that existing Phase 4 rule.

Incomplete coverage must agree with actual unready assessments and appear in
both snapshot/candidate reasons. Allowed incomplete coverage remains visible in
the record's boolean and reason. Setting the block flag adds an explicit blocking
reason without altering score or confidence.

## Freshness, validation and error boundary

Both strategy evaluation and source feature snapshot age are independently
checked against the decision maximum. A recent strategy wrapper cannot hide an
old feature snapshot. Aware UTC-equivalent times compare by instant. Candidate
time must equal strategy time; feature time must not exceed strategy time;
strategy/candidate future time is refused. Age arithmetic uses a fixed 34-digit
Decimal context with exact timedelta components, independent of caller precision.
There is no clock-skew grace period or implicit current time in pure evaluation.

Source STALE remains BLOCKED/stale. Phase 4 still owns relevant feature-group
freshness, partial coverage and closed-history rules. DecisionEngine does not
refresh lower-level timestamps, infer missing observations, read open candles,
reconstruct history or add a look-ahead path.

At the service boundary timestamps must already be actual aware datetime objects;
numeric timestamp coercion and naive copies are refused. Candidate symbol,
snapshot/observation identity, direction, score and confidence must match the
containing snapshot. Nested assessment timestamps and source identities must
match that same evaluation. Candidate ID is recomputed using the existing Phase 4
version/settings/observation/direction formula.

Malformed typed objects produce a safe BLOCKED record if the symbol and source
IDs remain valid. Missing/unusable source timestamps are null and force decision
readiness unavailable. If both source times remain usable, known stale/future
timing takes precedence over other invalidity and reports stale. Invalid candidate
values are omitted. Raw validation input and exception text never become reasons.

Wrong object types and missing/unsafe symbol/source IDs cannot support a truthful
record, so pure evaluation raises TypeError/ValueError. Invalid evaluation clocks
are programmer errors. `latest` rejects wrong-symbol provider output and converts
provider/evaluation failures to a sanitized DecisionSourceError; HTTP returns 503.
Unknown configured symbols return 404 without consulting the provider.

Reason codes are finite enums, including `no_candidate`, source readiness,
age/future/timestamp failures, candidate identity/contributor/provenance failures,
agreement/count/coverage gates, invalid source and unsupported symbol. Age,
agreement and contributor failures expose finite observed/threshold values.
No free-form external payload or diagnostic exception is included.

## Identity and deduplication contract

Decision version is `decision-engine-v1`. Phase 4's canonical JSON/SHA-256 helper
normalizes Decimal values and aware timestamps. Policy identity hashes validated
decision settings and sorted symbol scope. An empty symbol scope allows any valid
symbol for pure evaluation; configured `latest` still requires an allowlisted
symbol. Production receives the existing feed's symbol list.

```text
decision_id = hash(
    decision_engine_version, policy_id, symbol,
    strategy_engine_version, strategy_settings_id,
    observation_id, candidate_id or NO_CANDIDATE, outcome
)
```

Evaluation time and full feature `snapshot_id` are intentionally excluded. Two
equivalent fresh reads retain an eligible identity even if read timestamps and
full snapshot IDs differ. Changed observation, decision policy, symbol scope,
upstream settings/version, candidate or outcome changes decision identity. A
later read that expires a candidate changes outcome and therefore decision ID.
Different reasons for the same blocked observation/outcome need not change ID.

The record still exposes evaluation and source timestamps/full snapshot ID.
These hashes identify analytical observations, not unique audit events or
cryptographic authorization. Source settings/observation hashes and scoring
provenance remain trusted internal producer metadata. Phase 5 cannot recompute
the original feature snapshot or prove a score calculation from identity alone.
There is no HTTP candidate-submission endpoint and no persistent deduplication.
Future consumers must add durable action suppression if needed.

## API and lifecycle

| Endpoint | Response |
| --- | --- |
| `GET /decisions/status` | Typed version, policy/ID, `on_demand` mode and per-symbol decision summaries/reasons. |
| `GET /decisions/{symbol}/latest` | Typed DecisionRecord with analytical values, provenance and identity. |

Symbols are stripped/uppercased. Unknown symbols return sanitized 404; pre-lifespan
or unusable-provider reads return sanitized 503. Valid NO_ACTION/BLOCKED records
are ordinary 200 responses. POST/PUT/PATCH/DELETE return 405. Decimal values
serialize as JSON strings; NaN/Infinity is rejected. OpenAPI has ten paths,
including all eight preexisting routes. No arbitrary strategy input is accepted.

`create_app` accepts an additive optional `decision_settings` argument. Lifespan
creates DecisionEngine over the actual StrategyEngine before starting the existing
feed/feature tasks. Import, factory creation and OpenAPI generation do not create
engines or start network work. Each lifespan receives a fresh decision service.
Shutdown cancels/awaits only existing tasks and removes the feature subscriber.
The decision service has no work to cancel. Status evaluates symbols sequentially;
it is not an atomic snapshot across symbols. Existing single-worker guidance applies.

## Relationship to Phase 1 and deferred work

```text
DecisionRecord(ELIGIBLE)
    -> future deterministic sizing / intent builder
    -> TradeIntent
    -> independent RiskEngine
    -> ApprovedTradeIntent
    -> PaperExecutionGateway
```

These later connections are not implemented. Phase 1 TradeIntent requires concrete
quantity; Phase 5 does not invent one to bridge the types. DecisionEngine neither
approves nor submits nor simulates an order, and does not duplicate Phase 1 size,
execution-disabled, duplicate or other pre-execution risk checks. RiskLimits and
both execution contracts are untouched. Paper remains the default system mode.

Deferred: sizing, simulation orchestration/backtesting, durable audit/deduplication,
portfolio constraints, execution wiring, AI advisory integration, ML/RL, parameter
optimization, private/account data, credentials, testnet/live orders, database/Redis,
frontend changes, full-book reconstruction and performance qualification. No Phase
6 work or P2P/money-transfer automation. No profitability claim is made.

## Files created

- `backend/src/domain/decisions.py` — immutable output/policy/status contracts.
- `backend/src/application/decision_settings.py` — validated environment settings.
- `backend/src/application/decision_identity.py` — policy/decision content identity.
- `backend/src/application/decision_validation.py` — safe metadata and source coherence.
- `backend/src/application/decision_engine.py` — pure and on-demand policy service.
- `backend/src/api/decisions.py` — two read-only endpoints.
- `backend/tests/decision_fixtures.py` — deterministic typed strategy fixtures.
- `backend/tests/test_decision_contracts.py` — models/settings/identity regression.
- `backend/tests/test_decision_engine.py` — policy, freshness and provider tests.
- `backend/tests/test_decision_integration.py` — actual StrategyEngine and edge cases.
- `backend/tests/test_decision_api.py` — API, serialization and lifecycle tests.
- `docs/PHASE_5_REPORT.md` — this completion report.

## Files modified

- `backend/src/main.py` — additive factory argument, lifespan service, router.
- `backend/tests/conftest.py` — isolate `DECISION_` environment variables.
- `backend/tests/test_feature_api.py` — add the two expected OpenAPI paths.
- `backend/tests/test_strategy_api.py` — update expected path count from 8 to 10.
- `backend/README.md` — settings, rules, boundaries and API usage.
- `README.md` — current architecture/status.
- `docs/ARCHITECTURE.md` — implemented Phase 5 and future sizing/risk boundary.
- `CODEX_TASK.md` — status and validation record; requirements retained.

## Tests and commands

Commands ran from `backend` using repository `.venv/Scripts/python.exe`
(Python 3.11.9, pytest 8.4.2). The earlier targeted runs overlap; they are not
counts of separate additions.

| Stage | Command after virtual-environment activation | Exact result |
| --- | --- | --- |
| Baseline | `python -m pytest` | **1469 passed, 2 warnings in 4.92s** |
| Batch 1 | `python -m pytest tests/test_decision_contracts.py` | **81 passed in 0.30s** |
| Batch 2 | `python -m pytest tests/test_decision_engine.py tests/test_decision_contracts.py` | **106 passed in 0.35s** |
| Batch 3 | `python -m pytest tests/test_decision_integration.py tests/test_decision_engine.py tests/test_decision_contracts.py tests/test_strategy_engine.py` | **199 passed in 0.81s** |
| Batch 4 | `python -m pytest tests/test_decision_api.py tests/test_strategy_api.py tests/test_feature_api.py tests/test_market_api.py tests/test_api.py` | **98 passed, 2 warnings in 2.80s** |
| Final contract review | `python -m pytest tests/test_decision_contracts.py tests/test_decision_engine.py tests/test_decision_integration.py tests/test_decision_api.py` | **176 passed, 2 warnings in 1.59s** |
| Complete final regression | `python -m pytest` | **1645 passed, 2 warnings in 5.90s** |

During Batch 3, an initial edge-case run reported **3 failed, 40 passed in 0.76s**.
The fixes classify future candidate time as stale, refuse numeric timestamp
coercion and prohibit ELIGIBLE records with blocking reasons. The successful
199-test rerun includes all three cases. Final review added three tests for a
BLOCKED record lacking a blocking reason and contradictory coverage provenance;
the 176-test result includes them. Tests were not weakened.

There are **176 new Phase 5 tests**: 84 contracts/settings, 25 policy/provider,
43 actual-strategy/edge/scope and 24 API/lifecycle. Existing 1469 tests are retained.
Fixtures, injected providers/clocks and offline normalized feeds avoid Binance
availability or credentials. Scope tests inspect imports/calls and nonexecutable
schemas. No new external API contract or dependency was introduced.

All **1469 baseline + 176 Phase 5 = 1645** tests pass; no full-regression failures.
Additional completion checks:

- `python -m pip check`: **No broken requirements found.**
- Repository Python import/OpenAPI validation via stdin: **PASS**, all 10 expected
  paths GET-only, typed DecisionRecord, no initialized runtime engines/tasks,
  and zero network calls with connection/task-creation guards installed.
- Repository Python offline lifespan smoke via stdin: **PASS** for both disabled
  feed and injected offline source. Decision/status/config GETs return safe results,
  paper remains default, real-money execution remains disabled, and no decision
  task is created. Injected feed/feature tasks are cancelled and awaited; both
  scenarios finish with **0 pending tasks and 0 subscribers**.
- Offline network guard: **0 application network calls**. On Windows, the asyncio
  runner's local socketpair was initialized before installing the connection guard.
- Final source/import/AST audit: **PASS** for all six new production modules;
  no private/account/execution/AI/database references or lower-level/network imports.
  No retained decision history/cache or unbounded mutable collection was introduced.
- Credential-pattern and inventory review: no matches, conflict markers or
  accidental files; only the 12 expected new and 8 modified files listed above.
  No staged changes. Dependency files and Phase 1–4 service implementations are
  unchanged; prior API tests only accommodate the new routes/environment prefix.
- `git diff --check`: **exit 0**, no whitespace errors. New untracked files were
  separately checked for trailing whitespace and Python syntax.

The import/lifecycle scripts were run inline with `.venv/Scripts/python.exe -`;
no temporary scripts or runtime artifacts were added to the repository. The
repeatable API/lifecycle cases also remain in `test_decision_api.py`.

## Final working tree

`git status` reports branch `phase-5-decision-engine`, up to date with its tracking
branch, eight modified tracked files and twelve untracked files. Nothing is staged,
committed or pushed. The compact status is:

```text
 M CODEX_TASK.md
 M README.md
 M backend/README.md
 M backend/src/main.py
 M backend/tests/conftest.py
 M backend/tests/test_feature_api.py
 M backend/tests/test_strategy_api.py
 M docs/ARCHITECTURE.md
?? backend/src/api/decisions.py
?? backend/src/application/decision_engine.py
?? backend/src/application/decision_identity.py
?? backend/src/application/decision_settings.py
?? backend/src/application/decision_validation.py
?? backend/src/domain/decisions.py
?? backend/tests/decision_fixtures.py
?? backend/tests/test_decision_api.py
?? backend/tests/test_decision_contracts.py
?? backend/tests/test_decision_engine.py
?? backend/tests/test_decision_integration.py
?? docs/PHASE_5_REPORT.md
```

`git diff --stat` covers tracked modifications only: **8 files changed,
210 insertions(+), 43 deletions(-)**. It does not include the twelve untracked
files listed above; these are intentionally left unstaged for review.

## Warnings and remaining risks

The two existing dependency warnings are unchanged:

- Starlette TestClient's use of `httpx` is deprecated in favor of `httpx2`.
- AnyIO's `anyio.abc.BlockingPortal` alias is deprecated in favor of
  `anyio.from_thread.BlockingPortal`.

Dependency migration is outside this task. Git can emit existing Windows
LF-to-CRLF conversion notices; these do not imply whitespace-check failures.

Remaining technical limitations: source identity/provenance is an internal trust
contract; hashes are not authentication. Clock skew blocks data without tolerance.
Decision identities are not persistent deduplication or an audit log. Policy defaults
are uncalibrated engineering choices and strategy families are correlated. Partial
coverage is allowed by default and visible; optional upstream context can remain
missing. Live throughput is not qualified. Per-request evaluation repeats strategy
work and status is not cross-symbol atomic. Upstream warm-up, reconnect gaps,
process-local state and single-worker limits remain unchanged. No order safety or
profitability follows from ELIGIBLE.
