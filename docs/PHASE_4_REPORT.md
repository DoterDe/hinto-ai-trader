# Phase 4 — deterministic StrategyEngine

## Status and baseline

Implemented on `phase-4-strategy-engine`, starting from a clean working tree at
`fcb6d78` (`chore: define Phase 4 strategy engine task`). The complete baseline
was **1106 passed, 2 warnings in 3.37s** using the repository virtual environment.
AGENTS.md, CODEX_TASK.md, architecture, the Phase 3 report, feature production code
and Phase 3 tests were inspected before implementation. Existing Phase 4 work was
preserved across the usage-limit interruption.

All five batches are complete. Final full regression: **1469 passed, 2 warnings
in 5.12s** (all 1106 baseline tests plus 363 Phase 4 tests). Dependency, import,
OpenAPI, offline lifecycle, scope and whitespace checks passed. No commit or push
has been performed. No later phase has been started.

## Files created

All paths below are relative to the repository root.

| File | Responsibility |
| --- | --- |
| `backend/src/domain/strategies.py` | Immutable analytical contracts and bounds |
| `backend/src/application/strategy_settings.py` | Validated settings and fixed component weights |
| `backend/src/application/strategy_engine.py` | Feature provider protocol, consensus, on-demand service |
| `backend/src/strategies/__init__.py` | Strategy package |
| `backend/src/strategies/base.py` | Required/optional readiness, evidence and confidence assembly |
| `backend/src/strategies/scoring.py` | Pure bounded piecewise helpers and Decimal guard |
| `backend/src/strategies/identity.py` | Canonical snapshot/settings/observation identities |
| `backend/src/strategies/trend_following.py` | Trend strategy |
| `backend/src/strategies/momentum.py` | Momentum/continuation strategy |
| `backend/src/strategies/mean_reversion.py` | Mean-reversion strategy |
| `backend/src/api/strategies.py` | Two read-only routes |
| `backend/tests/strategy_fixtures.py` | Fixed typed feature observations |
| `backend/tests/test_strategy_contracts.py` | Domain/settings validation |
| `backend/tests/test_strategy_scoring.py` | Independent piecewise expectations and numerical cases |
| `backend/tests/test_strategies.py` | Three strategies, dependencies and numerical edge cases |
| `backend/tests/test_strategy_engine.py` | Consensus, deterministic identities, source/clock isolation |
| `backend/tests/test_strategy_api.py` | Read-only API, actual offline FeatureEngine integration, lifecycle |
| `docs/PHASE_4_REPORT.md` | This report |

## Files modified

| File | Change |
| --- | --- |
| `backend/src/main.py` | Optional strategy settings, lifespan construction, router registration |
| `backend/tests/conftest.py` | Clear `STRATEGY_` overrides in deterministic offline tests |
| `backend/tests/test_feature_api.py` | Extend the exact OpenAPI path assertion by the two new routes |
| `backend/README.md` | Operation, settings, API, freshness and scoring reference |
| `README.md` | Phase 4 status and explicit current analytical boundary |
| `docs/ARCHITECTURE.md` | Implemented StrategyEngine boundary and corrected Phase 4 scope |
| `CODEX_TASK.md` | Completion/validation status while retaining the original requirements |

Phase 1–3 production behavior, dependencies and feature interfaces were not
redesigned. The only existing production edit is the six-line app integration.
`base.py` and `identity.py` are small supporting modules beyond the suggested
layout, separating shared validation and identity from strategy calculations.
No fourth strategy was added.

## Architecture and contracts

```text
MarketDataHub -> FeatureEngine -> FeatureSnapshot
    -> StrategyEngine
        -> independent deterministic strategy assessments
        -> weighted consensus
        -> optional analytical StrategyCandidate
    -> future orchestration / DecisionEngine / RiskEngine integration
```

Only typed `FeatureSnapshot` input crosses into StrategyEngine. `FeatureProvider`
is an injected protocol with `latest(symbol) -> FeatureSnapshot`. The engine and
strategy code import no Binance payloads/adapters, HTTP client, execution gateway,
AI provider or persistence library. Existing normalized source names identify
freshness dependencies; there is no new external API contract in Phase 4.

`StrategyEvidence` stores name, raw value, optional reference, normalized value
in `[-1,1]`, weight in `[0,100]`, multiplier in `[0,1]`, contribution and a code.
Directional evidence validates `contribution = weight * normalized * multiplier`.
Context/quality evidence has weight and contribution zero; it is not added twice.
An assessment validates that its score equals the sum of its evidence contributions.

`StrategyAssessment` includes strategy ID, symbol, evaluation time, source feature
time, snapshot ID, direction, score, confidence, readiness, reasons, dependency
groups and evidence. Score is Decimal in `[-100,100]`; confidence is Decimal in
`[0,1]`. A ready zero score is neutral evidence, distinct from unavailable nulls.
Readiness is `ready`, `unavailable`, `stale`, or `warming_up`. Directions serialize
as `LONG`, `SHORT`, or `NEUTRAL`. Models are frozen, reject extra fields and
nonfinite numbers, and revalidate validation-bypassing copies at service boundaries.

`StrategySnapshot` preserves all assessments and adds consensus, identities,
timestamps, engine version and optional candidate. `StrategyCandidate` is inert:
ID, symbol, time, observation/snapshot identity, direction, score, confidence,
contributing strategy IDs and reasons. It has no quantity, leverage, price/order
type, execution mode or method to execute. It is neither `TradeIntent` nor the
Phase 1 `SignalCandidate`, and never reaches risk or execution services.

## Dependencies, freshness and warm-up

| Strategy | Hard-required groups | Optional group |
| --- | --- | --- |
| `trend_following` | `trend`, `momentum`, `regime`, `volatility` | None |
| `momentum_continuation` | `momentum`, `volume` | `microstructure` |
| `mean_reversion` | `trend`, `momentum`, `volatility`, `regime` | `microstructure` |

Hard groups must be READY with values. Unavailable, warming or stale groups give
that strategy a neutral, null-score/null-confidence assessment with group reasons.
When multiple hard dependencies fail, precedence is stale, unavailable, warming.
A partially available feature snapshot is acceptable; unrelated trade, returns,
mark/funding, book or depth freshness never blocks a strategy that does not use it.

Source metadata must identify exactly one relevant source: selected `kline:<interval>`
for candle groups, `book_ticker` for optional spread. Event time, receipt time,
connection ID and generation must exist. Missing/duplicate provenance is unavailable.
Stale provenance remains stale even if a group claims READY. Snapshot age and
each relevant source's event/receipt age must be strictly less than the configured
10-second default. Future snapshot/source times are stale. A closed-candle timestamp
must not exceed source event time or snapshot time. The source's actual connection
and continuity status is supplied by FeatureEngine; StrategyEngine does not open
sockets or independently reconstruct that history.

Historical groups also require a closed-candle timestamp and sufficient available
group and snapshot sample counts. At Phase 3 defaults, trend/reversion require
50 closed candles; momentum requires 21 (momentum group 15, volume group 21).
Fresh successor open-kline updates can keep those closed indicators usable under
Phase 3 expiry rules, but open OHLC values never enter strategy calculations.
Reconnect/queue-loss/gap invalidation remains owned by FeatureHistory/FeatureEngine.
No backfill or extra history is introduced. Default Phase 3 EMAs remain 9/21/50,
RSI14, ATR14 and ROC10; strategy settings do not change these indicator periods.

Optional absent, stale or semantically invalid book values retain hard readiness
and score while applying the configured missing-context factor (default 0.75).
Fresh spread quality is `1 - L(spread_bps; 0, 15)`. It is 1 at zero bps and zero
at or above 15 bps. Missing context can thus score better than known poor context;
this is an explicit analytical policy, not a spread/execution safety gate.

## Exact scoring rules

All formula parameters below show defaults. Validated settings supply overrides.
`sign(0)=0`. Arithmetic uses a fixed 34-significant-digit Decimal context with
half-even rounding, independent of caller context. Piecewise helpers compare
against boundaries before potentially overflowing intermediate calculations.

```text
L(x; a,b) = 0                  if x <= a
           (x-a)/(b-a)        if a < x < b
           1                  if x >= b

S(x; d,s) = sign(x) * L(abs(x); d,s)

R(r) = -L(-r; -45,-30)        if r < 45
        0                     if 45 <= r <= 55
        L(r; 55,70)           if r > 55

Q_ATR = 1 - L(normalized_ATR; 0.025,0.05)
```

Thus `S` has an inclusive symmetric dead zone and saturates at ±1; `R` has
RSI neutral zone 45–55 and saturates at -1 for RSI<=30, +1 for RSI>=70. RSI must
be in 0–100. ROC below -100 percent, nonpositive EMA/VWAP denominators, invalid
volume ratios and other impossible used values are rejected, not saturated into
directional evidence. Values used only as context retain their stated semantics.

### Trend following

Let F/S/L be fast/slow/long EMAs, D the fractional slow-EMA distance, E directional
efficiency, and P ROC in percent. The directional components are:

```text
n1 = S((F-S)/S; 0.0005,0.005)       weight 30
n2 = S((S-L)/L; 0.0005,0.005)       weight 30
n3 = S(D; 0.001,0.01)              weight 20
n4 = S(P; 0.1,2)                   weight 20
raw = 30*n1 + 30*n2 + 20*n3 + 20*n4
corroboration = 1 if at least two nonzero ni have sign(raw), otherwise 0
Q = L(E; 0.25,0.55) * Q_ATR * corroboration
score = sum(weight_i * ni * Q)
```

One EMA crossover alone is insufficient. Opposing EMA/price/momentum terms
subtract from score and reduce within-strategy agreement. Efficiency at/below
0.25 or normalized ATR at/above 0.05 yields zero conviction; efficiency 0.55
with ATR<=0.025 yields full quality. Positive EMA values and D>-1 are required.
The corroborating components can be correlated; they are not independent trials.

### Momentum/continuation

Let P be ROC percent, r RSI, dC the latest closed close change, V rolling VWAP,
T taker-buy ratio and RV relative volume:

```text
n1 = S(P; 0.1,2)                   weight 40
n2 = R(r)                         weight 25
n3 = S(dC/V; 0.001,0.01)           weight 20
n4 = S(2*T-1; 0.1,0.6)            weight 15
Q_volume = L(RV; 0,1)
Q_exhaustion = 1 - max(L(r; 70,100), L(-r; -30,0))
Q = Q_volume * Q_exhaustion
score = sum(weight_i * ni * Q)
```

RSI 30–70 incurs no exhaustion penalty; RSI15/85 halves conviction; RSI0/100
reduces it to zero. Relative volume supplies quality, not direction, and saturates
at baseline 1. Close change is normalized by the available positive rolling VWAP
to make this price-unit input dimensionless. No open price or extra price source
is introduced. Optional spread affects confidence only.

The normalized candle's `taker_base_volume_delta_proxy` is displayed as context
with zero contribution. Its direction is already represented by `2*T-1`; it is
not counted a second time. It is not exchange-wide true order flow or liquidity.

### Mean reversion

Let Ds/Df be fractional distances from slow/fast EMA, A normalized ATR, E
directional efficiency, r RSI and RV the regime group's relative volume:

```text
stretch = Ds / A                  A must be strictly positive
n1 = -S(stretch; 1,3)             weight 60
n2 = -R(r)                       weight 40
confirmation = 1 if n1 != 0 and sign(Df) == sign(stretch), otherwise 0
Q = (1-L(E; 0.25,0.55)) * (1-L(RV; 1,3)) * Q_ATR * confirmation
score = 60*n1*Q + 40*n2*Q
```

This is ATR-normalized **fractional EMA distance**:
`((C-EMA_slow)/EMA_slow)/(ATR/C)`, not exactly `(C-EMA_slow)/ATR`.
Both distances must exceed -1. Zero ATR is unavailable, not an invented zero
stretch. Efficient trend (E>=0.55), RV>=3, high ATR, insufficient stretch or
contradictory fast distance suppress conviction. Stretch and RSI can offset;
strong direction is never opposed merely because RSI is extreme.

### Per-strategy confidence and direction

```text
score = sum(contributions)
gross = sum(abs(contributions))
agreement = abs(score)/gross if gross > 0 else 0
strength = abs(score)/100
confidence = strength * agreement * optional_quality
```

Optional quality is 1 for trend and the book factor described above for momentum
and reversion. Quality factors, score strength and agreement appear as explicit
zero-contribution evidence. Component weights sum to 100 and multipliers are in
0–1, giving bounded scores without hiding contradictions by post-hoc clipping.
Confidence is a bounded evidence-quality measure, not a success probability.

An individual assessment is LONG for score>=25, SHORT for score<=-25; otherwise
NEUTRAL with `below_strategy_dead_zone`. Its raw score/confidence are retained
for aggregation even when its individual direction is neutral. A zero score
has zero confidence. Impossible arithmetic yields UNAVAILABLE with nulls and
`invalid_feature_values`. Nonfinite/malformed typed objects or invalid settings
are rejected at input validation. No invalid value is silently converted to a
directional zero, saturation, NaN or Infinity.

## Settings

All settings use the process environment prefix `STRATEGY_`; uppercase suffixes
correspond to the fields below. No `.env` loading or dependency was added.

| Field(s) | Default |
| --- | --- |
| `enabled_strategies` | trend_following, momentum_continuation, mean_reversion in that order |
| `min_absolute_strategy_score` | 25 |
| `candidate_score_threshold` | 40 |
| `min_candidate_confidence` | 0.55 |
| `rsi_neutral_low`, `rsi_neutral_high` | 45, 55 |
| `rsi_extreme_low`, `rsi_extreme_high` | 30, 70 |
| `max_acceptable_spread_bps` | 15 |
| `trend_efficiency_floor`, `strong_trend_efficiency` | 0.25, 0.55 |
| `relative_volume_baseline`, `relative_volume_exhaustion` | 1, 3 |
| `ema_separation_dead_zone`, `ema_separation_saturation` | 0.0005, 0.005 (fractions) |
| `price_distance_dead_zone`, `price_distance_saturation` | 0.001, 0.01 (fractions) |
| `roc_dead_zone`, `roc_saturation` | 0.1, 2 (percent) |
| `taker_bias_dead_zone`, `taker_bias_saturation` | 0.1, 0.6 |
| `reversion_stretch_dead_zone`, `reversion_stretch_saturation` | 1, 3 |
| `atr_soft_limit`, `atr_hard_limit` | 0.025, 0.05 (fractions) |
| `optional_context_missing_quality` | 0.75 |
| `max_feature_age_seconds` | 10 |
| `trend_weight`, `momentum_weight`, `mean_reversion_weight` | 1 each |

Enabled IDs must be unique/nonempty; all numeric settings are finite; aggregation
weights are positive and <=100. Score/confidence thresholds are positive and
bounded; candidate score threshold must cover the individual dead zone. RSI
thresholds strictly increase within 0–100; efficiency/quality factors are in
0–1; ramp lower bounds must precede upper bounds. Booleans are not numbers here.
Fixed component weights 30/30/20/20, 40/25/20/15, 60/40 and minimum trend
corroboration 2 are centralized immutable constants in the same settings module,
part of algorithm version `strategy-engine-v1`, not additional optimization knobs.

## Aggregation and candidate rules

Let w_i be the configured positive strategy weight; only READY assessments form
the set R. U includes all enabled strategies, including unavailable ones:

```text
W_ready = sum(w_i for i in R)
W_all = sum(w_i for i in U)
net = sum(w_i * score_i for i in R)
gross = sum(w_i * abs(score_i) for i in R)
composite_score = net / W_ready
agreement = abs(net) / gross if gross > 0 else 0
confidence = sum(w_i * confidence_i for i in R) / W_all * agreement
```

A ready neutral score participates and dilutes the mean; unavailable scores are
never fabricated or averaged. Coverage remains in the confidence denominator.
Opposition subtracts from net and reduces agreement. All-unready results have
null composite/confidence/agreement, neutral direction and no candidate; state
uses the stale/unavailable/warming precedence. At least one READY assessment
makes the aggregate READY, but does not guarantee a candidate.

A candidate requires **both** inclusive thresholds: `abs(composite_score)>=40`
and `confidence>=0.55`. Its direction follows score sign. Otherwise aggregate
direction is NEUTRAL and candidate null, with threshold/conflict/coverage reasons.
Candidate contributors are READY assessments with nonzero score in the final
direction (including an individually neutral subthreshold contribution if aligned).
Opposing assessments stay visible in the enclosing response.

Independent test examples with equal weights:

| Ready score inputs | Individual confidence | Composite / agreement / aggregate confidence | Candidate |
| --- | --- | --- | --- |
| 100,100,100 | 1,1,1 | 100 / 1 / 1 | LONG |
| -100,-100,-100 | 1,1,1 | -100 / 1 / 1 | SHORT |
| 60,60,-30 | 1,1,1 | 30 / 0.6 / 0.6 | None, score below 40 |
| 60,-60,0 | 1,1,1 | 0 / 0 / 0 | None |
| 90,90,unavailable | 0.9,0.9,null | 90 / 1 / 0.6 | LONG |
| 90,unavailable,unavailable | 0.9,null,null | 90 / 1 / 0.3 | None, coverage penalty |

These examples validate consensus math using independent typed assessments;
they do not claim all three real strategy families agree in the same regime.

## Deterministic identities and time

`evaluate(snapshot)` uses its feature generation timestamp as evaluation time;
it does not consult the engine clock. Explicit `now` is supported for age checks.
Exact same typed snapshot/settings/explicit evaluation time produces equal models
and deterministic serialization with the same evidence order. No input is mutated.
`latest/status` use an injectable wall clock and actual FeatureEngine reads for
live freshness; an old cached snapshot cannot silently be treated as current.

SHA-256 hashes use sorted canonical JSON, finite Decimal coefficient/exponent
representations and UTC timestamps. Decimal 1 and 1.000 and equivalent timezone
representations have equivalent identities, independent of Decimal context.

- `snapshot_id`: complete FeatureSnapshot, including read-time `generated_at`.
- `settings_id`: complete validated StrategySettings, including enabled ordering.
- `observation_id`: symbol/interval, closed-candle time, history reset count/reason,
  enabled strategies' required and optional **whole groups**, plus relevant source
  provenance. Book event/receipt timestamps are retained when book is relevant;
  selected-kline event/receipt refresh times are omitted. Connection identity,
  generation, stale state/reason and group readiness remain included.
- `candidate_id`: engine version + settings identity + observation identity + direction.

Repeated API reads or subsequent open-kline refreshes alone do not change a
closed-feature observation. Relevant group values, book observations, close time,
history reset or connection generation do. Irrelevant trade/mark countdowns do
not change it. Whole-group hashing deliberately can change identity for a field
within a relevant group that a particular formula does not read. Any setting
change can also change candidate identity even if the score happens to match.

There is no persistent suppression, action reservation or execution deduplication.
Future consumers must retain the relevant inputs/settings and apply their own
action policy; candidate IDs are analytical identities, not authorization tokens.

## API and lifecycle

| Endpoint | Result |
| --- | --- |
| `GET /strategies/status` | Engine/settings identity, on-demand mode, dependency definitions, weights and per-symbol readiness/direction/candidate availability |
| `GET /strategies/{symbol}/latest` | Source/evaluation times, snapshot/observation/settings IDs, all assessments/evidence, consensus and optional candidate |

Symbols are stripped/uppercased. Unknown symbols return sanitized 404 responses;
before lifespan initialization, 503. POST/PUT/PATCH/DELETE return 405. No endpoint
accepts arbitrary feature values. Decimal scores/ratios serialize as strings;
the API exposes no NaN/Infinity or executable order fields.

Application import and OpenAPI generation do not construct StrategyEngine,
FeatureEngine or network runtime. Lifespan reads settings and creates StrategyEngine
after FeatureEngine, before existing feed/feature tasks begin. It holds a provider,
fixed symbols, settings and three stateless strategy instances, with no history,
cache, growing assessment store, subscriber or task. Status evaluates each symbol
on demand. Reads share the existing application event loop.

Shutdown still cancels/awaits the feed and FeatureEngine tasks, closes the source,
removes the feature subscriber and clears feature history. There is no strategy
task to stop. With a disabled feed and no injected source there are zero feature
subscribers and unavailable strategy output. An injected offline source exercises
the actual FeatureEngine. Source failure makes hard dependencies stale and
suppresses candidates. Repeated lifespans receive a new StrategyEngine instance.

## Validation record

All commands use Python 3.11.9 from `backend/.venv/Scripts/python.exe`, with backend
as working directory. `python` below denotes that interpreter. Tests are offline.

| Stage | Command after `python -m pytest` | Exact result |
| --- | --- | --- |
| Clean baseline | No arguments (complete suite) | 1106 passed, 2 warnings in 3.37s |
| Batch 1 | `tests/test_strategy_contracts.py tests/test_strategy_scoring.py` | 184 passed in 0.44s |
| Batch 2 | `tests/test_strategy_contracts.py tests/test_strategy_scoring.py tests/test_strategies.py` | 267 passed in 0.70s |
| Batch 3 | `tests/test_strategy_engine.py tests/test_strategies.py tests/test_strategy_contracts.py tests/test_strategy_scoring.py` | 316 passed in 0.99s, including 49 engine tests |
| Batch 4 | `tests/test_strategy_api.py tests/test_feature_api.py tests/test_market_api.py tests/test_api.py` | 74 passed, 2 warnings in 2.42s, including 23 new API tests |
| Batch 5 edge-case diagnostic | `tests/test_strategies.py` | 2 failed, 103 passed in 1.62s; causes and correction below |
| Batch 5 after numerical fix | `tests/test_strategies.py tests/test_strategy_engine.py tests/test_strategy_contracts.py tests/test_strategy_scoring.py tests/test_strategy_api.py` | 362 passed, 2 warnings in 3.91s |
| Batch 5 final targeted | Same five modules, with input-preservation/evidence-order/clock test | 363 passed, 2 warnings in 2.02s |
| Final complete regression | No arguments (`python -m pytest`) | 1469 passed, 2 warnings in 5.12s |

The diagnostic found one production defect: inexact underflow while composing
confidence escaped the per-assessment handler. The targeted fix catches Decimal
arithmetic exceptions there and returns an unavailable assessment. One new test's
overflow input divided down to a representable exponent; its magnitude was
corrected, and a separate test verifies bounded scoring for the representable
extreme. Tests were not weakened; existing Phase 1–3 tests were retained.

Additional final validation:

- `python -m pip check`: exit 0, `No broken requirements found.`
- Application import/OpenAPI (`python -` validation script): PASS, eight read-only
  paths, typed Strategy API, no runtime constructed on import and no candidate
  order fields.
- Offline lifespan (`python -` validation script): PASS for disabled feed and
  injected source; feed/feature tasks cancelled, source closed, zero subscribers
  and no extra tasks left. Zero application network attempts under a socket guard.
  The Windows event loop was initialized before that guard to permit its internal
  loopback wake-up socket. Initial harness attempts exposed PowerShell argument
  quoting and that internal-socket constraint; neither required an application edit.
- Read-only AST/text/inventory audit: PASS, exactly 18 expected new files and seven
  modified files; no new exchange/private/account/execution/AI/storage dependency
  or call, credential/private-endpoint pattern, accidental file or trailing whitespace.
  Manual review and tests additionally cover bounded state, finite serialization,
  explicit clock use and absence of strategy side effects.
- `git diff --check`: exit 0, with only Windows LF-to-CRLF normalization notices.
- `git status` / `git diff --stat`: working changes remain on
  `phase-4-strategy-engine`; no staging, commit or push. Ordinary diff statistics
  count seven modified tracked files and omit the 18 new untracked files listed above.

No Phase 4 acceptance item remains unfinished. Operational and later-phase work
listed below is deliberately outside this completion claim.

## Warnings, limitations and deferred work

The two existing dependency warnings are Starlette's deprecation of `httpx`
TestClient support in favor of `httpx2`, and AnyIO's deprecated
`anyio.abc.BlockingPortal` alias. No dependency migration is included in Phase 4.
Git on this Windows checkout can also print LF-to-CRLF normalization notices.

Engineering thresholds are unoptimized defaults, with no profitability, win-rate,
statistical calibration or cost-adjusted performance claim. The three families
share correlated features; consensus is not independent statistical evidence.
Scores/confidence do not model fees, slippage, market impact, portfolio exposure,
positions, leverage or feasible order quantities.

Features inherit bounded-history reseeding, atomic-group readiness, reconnect
warm-up and lack of REST backfill from Phase 3. Flat efficiency and zero denominators
can make a whole group unavailable. Strategy age limits may be stricter than a
separately changed Hub threshold. Missing optional spread is a confidence policy,
not verified liquidity. Raw depth deltas are not a full order book and are unused;
top-of-book imbalance, funding and basis are not scored by these three strategies.

Evaluation is bounded by configured symbols and existing bounded feature windows,
but status reads recompute features and assessments synchronously. Sustained live
throughput/latency and multiworker orchestration have not been qualified. Extreme
but finite settings can be mathematically unrepresentable in the fixed Decimal
context; guarded arithmetic rejects such operations instead of producing a
directional value. Operators should retain ordinary validated engineering ranges.

Intentionally deferred: optional fourth strategy, backtest runner, durable
observation/candidate history and deduplication, strategy-to-decision/risk wiring,
TradeIntent generation, any gateway invocation or order simulation, private data,
account access/keys, testnet/live orders, AI/OpenAI, ML/RL, parameter optimization,
database/Redis, frontend changes and reconstructed full order books. None is
required to finish this analytical Phase 4 scope.
