# Phase 10 — Research Validation Lab

Status: **Batches 1–7 complete; ready for review.**
Final backend: **2771 passed, 0 failed, 0 skipped, 2 warnings in 539.39s (0:08:59)**.
Final frontend: **4 files, 100 passed in 26.66s**; types and production build passed.
Earlier batch checkpoints below are historical records, not the current stop point.
All existing uncommitted work is preserved. No commit, push, merge or branch change.

## Base and baseline

Branch: `phase-10-validation-lab`. HEAD at inspection: `2c45317` (preceded by
`9d36102`). Both preparation commits only add the Phase 10 task/spec above accepted
Phase 9 `2925f38d6423c28e92a39c9758766112bd197714`; `git merge-base HEAD main`
returns that exact accepted SHA.

Completed results were recovered from the interrupted session before editing;
rejected/uncompleted commands were not counted as successful checks. The full
backend result was recovered rather than rerunning it unnecessarily.

Commands below run in `backend` or `frontend` as appropriate. `python` means the
repository interpreter `.\.venv\Scripts\python.exe`; Windows npm uses `npm.cmd`.

| Baseline command | Exact completed result |
| --- | --- |
| `python -m pytest` | **2410 passed, 2 warnings in 328.41s (0:05:28)**; exit 0 |
| `python -m pip check` | `No broken requirements found.`; exit 0 |
| `python scripts/export_dashboard_contract.py --check` | `Dashboard schema and explanation catalog: verified`; exit 0 |
| `python tests/export_dashboard_examples.py --check` | `Four deterministic runtime dashboard fixtures verified`; exit 0 |
| `npm.cmd ci` | 133 packages added, 134 audited in 2m; 0 vulnerabilities; exit 0 |
| `npm.cmd run types` | Generated successfully; exit 0 |
| `git diff --exit-code -- src/types/generated.ts` | No content difference; exit 0; LF/CRLF notice |
| `npm.cmd test` after `npm ci` | **3 files, 77 tests passed in 23.36s**; exit 0 |
| `npm.cmd run build` after `npm ci` | TypeScript and Vite passed; 132 modules, build 274ms; exit 0 |

Recovered earlier frontend checks also passed: 77 tests in 66.40s and build in
2.87s. The post-`ci` results above are the final frontend baseline. Final bundle:
HTML 0.63kB (gzip 0.38), CSS 12.98kB (gzip 3.86), JS 497.29kB (gzip 137.77).

The existing backend warnings concern Starlette's deprecated `httpx` TestClient
integration and AnyIO's deprecated `anyio.abc.BlockingPortal` alias. No dependency
changes were made. Type generation changed working-copy line endings in
`frontend/src/types/generated.ts`; Git reports no content diff. That generator
output is preserved, not reset or overwritten.

## Batch 1 — accepted dataset layer

The following Batch 1 implementation and validation record is retained. Its
review-time deferrals and Git inventory are historical; Batch 2 is recorded below.

### Files

Created:

- `backend/src/domain/historical_dataset.py`
- `backend/src/application/historical_dataset.py`
- `backend/src/application/historical_dataset_codec.py`
- `backend/tests/test_historical_dataset.py`
- `backend/tests/test_historical_dataset_codec.py`
- `backend/tests/test_historical_dataset_replay.py`
- `docs/PHASE_10_REPORT.md`

Documentation modified: `CODEX_TASK.md`, `docs/ARCHITECTURE.md`,
`docs/MODULE_MAP.md`. No existing production module, formula, dependency, HTTP
route, dashboard contract or frontend behavior was changed.

### Architecture and reuse

The new offline adapter is:

```text
bounded local KlineEvent iterable + explicit symbol/interval scope
    -> validate_historical_dataset
    -> DatasetValidationResult
       -> INVALID: issues, no usable dataset
       -> VALID / VALID_WITH_GAPS: HistoricalDataset(manifest, canonical bars)
    -> HistoricalDatasetCodec (optional deterministic JSON bytes)
    -> existing HistoricalReplay / BacktestEngine via dataset.bars
```

Existing components are reused without edits:

- `KlineEvent` supplies the existing public market fields and typed validation.
- `symbols_for_replay`, `validate_bar` and `next_open_time` supply symbol scope,
  finalized OHLCV validation, UTC grid and exclusive interval-end conventions.
- Phase 6 `DatasetIdentity` and the public `strategies.identity.identity` helper
  supply the unchanged content hash chain and canonical SHA-256 conventions.
- Replay still evaluates at bar `t`'s exclusive close with an explicit historical
  clock, using the production Feature/Strategy/Decision engines and freshness
  gates. Entry requires the next exact bar's open; exits require the configured
  complete holding horizon. Defaults remain H=5, fee=5bps/side, slippage=2bps/side.
- Backtest outcomes remain independent signal observations. Phase 7 remains the
  separate shared-capital ledger: deterministic simultaneous arbitration,
  reservations before entry, known-mark valuation and explicit incomplete exposure.
  Neither its formulas nor its rank/sizing rules change.
- Phase 8's closed-bar live analytical view and Phase 9's SQLite checkpoint,
  recovery, compatibility and persistence worker stay separate. The dataset codec
  neither opens a database nor imports checkpoint state.

The current frontend Backtest page remains an educational description. Dataset
construction does not start a report, live runtime, API action or optimization.

### Validation, ordering and missing evidence

Scope must contain 1–128 unique supported `MarketSymbol` values and one historical
interval. Source label is a bounded ASCII label, not a path or URL. Input consists
only of finalized `KlineEvent` objects. Every timestamp must already have zero UTC
offset: naive and non-UTC timestamps fail, even if they denote an equivalent instant.
OHLC ordering, positive prices, nonnegative volumes/counts, taker-volume consistency,
finite numbers, interval alignment and final-bar availability reuse Phase 6 checks.

Rows are sorted by `(exclusive boundary, symbol)`. The builder accepts unsorted
input but never silently selects a winner for conflicting `(symbol, open_time)`
rows. A conflicting duplicate returns `INVALID`, with one conflict issue and no
dataset. Invalid results stop at the first fatal issue; they are not an exhaustive
inventory of all problems in an invalid source.

Identical duplicates are explicitly diagnosed once per key, with `count` equal to
the number of extra occurrences. Only one canonical row remains. Canonical typed
datasets and imported documents reject repeated or reversed canonical rows.
This distinguishes source duplicate diagnostics from duplicate replay evidence.

Optional declared `[start, end)` bounds must be supplied together, aligned to the
same UTC grid. Out-of-bounds bars fail validation; they are not trimmed. Without
declared bounds, coverage uses the earliest observed open and latest observed
exclusive close. Those inferred bounds cannot reveal missing data outside the
observed extent; callers should declare the intended range when known.

Each symbol gets observed/expected/missing bar counts, observed endpoints and
leading/internal/trailing gap ranges, including symbols with zero observations.
Each gap represents missing open-time slots in `[start, end)` and their exact count.
Month intervals use calendar month indices, not assumed 30-day durations. A gap
spanning years remains one range; missing bars are never materialized or repaired.
`gap_count` counts ranges across symbols; `missing_bar_count` counts symbol/bar
slots. A nonempty dataset with gaps is `VALID_WITH_GAPS`, not automatically invalid.

Coverage fraction = observed / expected, using a fixed 34-digit Decimal context.
Integer counts are authoritative when the ratio repeats. No price, candle,
book/trade/mark/funding context or analytical outcome is inferred from a gap.

### Dataset identity and codec

Schema: `historical-dataset-v1`.

1. Normalize valid rows to exclusive UTC boundaries and canonical exact Decimal
   values. Remove insignificant trailing zeros and the sign/scale of zero without
   rounding. All actual digits remain exact; ambient Decimal precision is ignored.
2. Feed sorted, unique rows into the unchanged Phase 6 `DatasetIdentity`: SHA-256
   seeded by `historical-final-klines-v1\n`, then each canonical `bar_<sha256>`
   fingerprint plus newline. All existing replay fields participate, including
   timestamps, OHLC, base/quote volumes, trade count and taker-buy volumes.
3. Store that digest as `content_checksum` and the unchanged `dataset_<digest>` as
   `replay_dataset_id` for reconciliation with Phase 6 reports.
4. Compute `dataset_id` with the existing `identity("historical_dataset", payload)`
   helper. Payload includes schema version, sorted symbols, interval, declared or
   inferred start/end and content checksum. Object keys are sorted for SHA-256.

No filesystem path, mtime, clock, hostname, random value, source label or duplicate
arrival order enters dataset identity. Scope/boundary changes alter the dataset
ID even when the bar-content checksum is unchanged. Source labels and duplicate
diagnostics are manifest provenance; changing them does not change canonical bar
evidence. They are caller assertions, not authenticated acquisition provenance.

The manifest also contains observed first-open/first-boundary/last-boundary,
input/canonical counts, duplicate/conflict counts, status, per-symbol coverage,
gap totals and duplicate diagnostics. Successful manifests have conflict count 0;
invalid evidence has no successful manifest.

Codec output is UTF-8 JSON plus newline with sorted object keys, compact separators,
Decimal strings and UTC microsecond timestamps ending in `Z`. Import requires an
explicit supported version, rejects unknown fields, repeated JSON object keys,
float/NaN/Infinity tokens, malformed timestamps, noncanonical row order and
inconsistent manifests/hashes. It recomputes the complete manifest from rows and
bounded duplicate provenance. Insignificant JSON whitespace is accepted.
`verify_historical_dataset` also revalidates frozen `model_copy` inputs.

Two canonical dataset replays before/after codec round-trip have byte-identical
Phase 6 reports. Compared with raw, unadapted Phase 6 input, all report values and
IDs match; incidental Decimal spelling in raw report JSON can differ. Existing
engines and their serialization are unchanged.

Golden two-bar fixture (`bar(0)`, `bar(1)`, BTCUSDT, 1m):

```text
dataset_id:
historical_dataset_d20a95789e2f878bc14ea4822da034102b6edfa6682e0bcb6d6c085d4b2c9d47
content_checksum:
8c2444db6cf4cc22511ee5ce4573a379ee8882b74ae22a178462f304a632ee53
canonical JSON SHA-256:
a0ad37102522b445a7617de5f3bbba0504fe699c57b1a3e504c4c17e23ec39d7
```

### Resource limits and usage

Batch 1 is a finite in-memory adapter with at most 100,000 input rows (including
duplicates), 128 symbols and 64MiB encoded JSON. An iterator exceeding the input
budget is stopped after one overflow sentinel. Canonical Decimal coefficients
are limited to 128 digits and absolute exponent 1000; trade counts are at most
`2**63 - 1`. These are resource limits, not trading or statistical thresholds.
Larger datasets need explicit future capacity work. A valid in-memory dataset
can exceed the separate JSON byte limit and then fail export. Gap computation
uses O(rows + symbols) retained state, not O(missing slots); sorting is O(rows log rows).
JSON parsing/export uses finite whole-document memory, with no compressed imports.

```python
from src.application.historical_dataset import validate_historical_dataset
from src.application.historical_dataset_codec import HistoricalDatasetCodec

result = validate_historical_dataset(local_final_bars, symbols=("BTCUSDT",), interval="1m")
dataset = result.require_dataset()  # raises if INVALID; inspect result.issues first
payload = HistoricalDatasetCodec.encode(dataset)
restored = HistoricalDatasetCodec.decode(payload)
# Existing offline engines consume restored.bars with the manifest's scope.
```

### Batch 1 validation

At the Batch 1 checkpoint, only focused tests and directly affected Phase 6
regressions were run, as explicitly requested for that review boundary. The
completed full-phase regression is recorded in the final release gate below.

| Command / stage | Exact result |
| --- | --- |
| Initial dataset/codec tests | 143 passed in 0.79s |
| Added edge and integration tests before fixes | 5 failed, 147 passed in 6.10s |
| After targeted fixes | 152 passed in 4.87s |
| `python -m pytest tests/test_historical_dataset.py tests/test_historical_dataset_codec.py tests/test_historical_dataset_replay.py -q` (final, including golden/permutation checks) | **154 passed in 4.90s**, exit 0 |
| `python -m pytest tests/test_historical_replay.py tests/test_backtest_contracts.py tests/test_backtest_engine.py -q` | **137 passed in 16.20s**, exit 0 |

The failing edge run exposed representation-dependent numeric limits, a missing
schema-version admission gap, and an overly broad byte-comparison assumption
between canonical input and raw Phase 6 Decimal spelling. Fixes normalize values
before replay and require the version. Regressions assert exact values/IDs against
raw replay and byte equality across canonical round-trips; no analytical assertion
or production formula was weakened.

Tests cover all equal-time permutations, identical/conflicting duplicates,
canonical-row duplicate rejection, every replay numeric field's identity impact,
strict UTC/scope/interval/bounds, malformed and nonfinite inputs, exact Decimal
round-trips under reduced ambient precision, leading/internal/trailing/absent-symbol
coverage, calendar-month gaps, centuries-long missing ranges, budgets and tampered
imports. Existing engines confirm next-open/fixed-horizon behavior, missing-entry
incompleteness, and unchanged earlier full replay frames after a future-bar mutation.

### Batch 1 review-time deferrals and risks

- Batches 2–7: walk-forward splits, causal regime labels, cost sensitivity,
  validation reports/registry, GET/API/frontend projections and final full-phase
  robustness/regression. No part of Batch 2 was started.
- No importer/downloader, exchange connection, CLI/file manager, compression,
  database, report storage or runtime integration. Caller owns file/iterator lifecycle.
- A checksum proves content consistency, not historical source authenticity or
  market realism. Valid numeric extremes may still be unusable analytical evidence.
- Declared complete coverage is not proof of correct exchange history. Inferred
  bounds cannot expose unknown data outside observed endpoints.
- No order-book reconstruction, strategy/decision/sizing/cost changes, private
  account APIs, credentials, execution, AI/ML or parameter optimization.
- The complete Phase 10 full backend/frontend regression remains required in
  Batch 7; this report covers the requested Batch 1 review only.

### Batch 1 review-time repository checks

`git diff --check` passed. Separate syntax, prohibited-import/call and whitespace
checks passed for all new Python files; the existing Phase 6 source-boundary test
also includes the new historical application modules. No prohibited integration
or secret was found. Git emits only working-copy LF/CRLF conversion notices.

`git diff --stat` (tracked content only; untracked new files are excluded):

```text
 CODEX_TASK.md        |  5 +++++
 docs/ARCHITECTURE.md | 25 +++++++++++++++++++++++++
 docs/MODULE_MAP.md   | 13 +++++++++++++
 3 files changed, 43 insertions(+)
```

New Python files contain 891 lines in total, plus this new report. They remain
untracked for review; no staging or commit was performed. Generated frontend
types still show as modified due to the baseline generator's line-ending change;
`git diff --exit-code -- frontend/src/types/generated.ts` passes with no content diff.

`git status --short`:

```text
 M CODEX_TASK.md
 M docs/ARCHITECTURE.md
 M docs/MODULE_MAP.md
 M frontend/src/types/generated.ts
?? backend/src/application/historical_dataset.py
?? backend/src/application/historical_dataset_codec.py
?? backend/src/domain/historical_dataset.py
?? backend/tests/test_historical_dataset.py
?? backend/tests/test_historical_dataset_codec.py
?? backend/tests/test_historical_dataset_replay.py
?? docs/PHASE_10_REPORT.md
```

**PHASE 10 BATCH 1 READY FOR REVIEW**

## Batch 2 — deterministic walk-forward validation

Batch 2 adds protocol/split contracts, chronological planning and an orchestration
layer around the existing analytical replay. Batch 1 production/tests and all
Phase 1–9 production modules remain unchanged. No new dependency was introduced.

### Files and contracts

Added in Batch 2:

- `backend/src/domain/walk_forward.py`
- `backend/src/application/walk_forward.py`
- `backend/src/application/walk_forward_evaluator.py`
- `backend/tests/test_walk_forward_protocol.py`
- `backend/tests/test_walk_forward_evaluator.py`

Documentation updated in Batch 2: `CODEX_TASK.md`, `docs/PHASE_10_REPORT.md`,
`docs/ARCHITECTURE.md`, `docs/MODULE_MAP.md`. The pre-existing frontend generated
types line-ending change is preserved; it has no semantic contract modification.

Models are `WalkForwardMode`, `WalkForwardProtocol`, `WalkForwardSplit`,
`WalkForwardPlan`, `WalkForwardEngineIdentity`, `WalkForwardEvidence`,
`WalkForwardWindowResult` and `WalkForwardEvaluation`. These are immutable research
artifacts with closed schemas, not execution or parameter-training interfaces.

Protocol version is `walk-forward-v1`; evaluator version is
`walk-forward-evaluator-v1`. The protocol records dataset ID/schema, canonical
symbol scope, interval, mode, minimum context, declared warmup, test size, step,
rolling length where applicable, overlap policy and partial-window policy.
Defaults are EXPANDING, context/warmup 50, test/step 20, overlap disabled, partial
windows INCLUDE. Rolling length is mandatory in ROLLING mode and must cover the
minimum context/warmup. Zero, negative, fractional and boolean counts are rejected.

### Boundary and mode semantics

Ranges use the dataset's UTC interval grid. Each interval slot is one boundary
regardless of symbol count. An entirely absent close group is an empty slot, not
an observation. An absent ETH row at a BTC close stays missing at that same time.
No missing slot is materialized as a candle or moved to another boundary.
Calendar-month intervals use calendar boundaries, not fixed day counts.

`context_start/context_end` and `test_start/test_end` delimit `[start, end)` by
bar open time, equivalently `(start, end]` by exclusive close/decision time.
`context_end == test_start`: the last context close is available at test_start;
the first test decision is at the next interval close, strictly later. Thus no
decision-producing test bar is used to warm its own preceding context.

- **EXPANDING:** context starts at the declared dataset start; the first test
  begins after minimum-context slots. Context end advances by the fixed step.
- **ROLLING:** the first test begins after rolling-context slots; each later
  context contains exactly that many immediately preceding slots. Its start and
  end slide together. Prior split state is never retained.
- **Overlap:** disabled by default. A step shorter than test size requires explicit
  opt-in; opting in without a shorter step is rejected. Each overlapping cohort
  has its own split/result namespace; no cross-window performance sum is produced.
- **Step larger than test:** allowed explicitly and flagged as
  `SKIPPED_TEST_BOUNDARIES`; it is a protocol choice, not outcome-based filtering.
- **Final partial window:** INCLUDE evaluates and flags `PARTIAL_TEST_WINDOW`.
  REJECT retains the split as `PARTIAL_WINDOW_REJECTED` with no fabricated metrics.

Splits expose structural ID, ordinal, dataset/protocol references, boundaries,
scheduled and observed boundary counts, required warmup, per-symbol context/test
coverage, insufficient symbols, status and warnings. With no scheduled test range,
the plan explicitly reports `INSUFFICIENT_CONTEXT` or `NO_TEST_BOUNDARIES`.

### Warmup, gaps and readiness

The production helper derives the required candle sample count from active
FeatureSettings:

```text
max(ema_long, rsi_period + 1, roc_period + 1, atr_period,
    volatility_window + 1, vwap_window, relative_volume_window + 1,
    largest_rolling_return_window + 1)
```

This is **50** under existing defaults. Tests reconcile this metadata calculation
against the actual FeatureEngine's public group sample requirements, including
larger EMA, RSI, ATR, ROC, volatility, volume, VWAP and return settings. An explicit
protocol warmup below the active feature requirement is rejected; settings are not
silently reduced. A longer declared warmup may impose a stricter requirement.

For every scoped symbol, the planner counts only the contiguous observed suffix
ending exactly at context_end. Earlier bars across a gap do not count toward that
suffix. A deficient symbol makes the split `INSUFFICIENT_CONTEXT`, with the symbol
and coverage retained; no analytical replay or fake zero metrics are returned for
that split. A later split can become evaluable after sufficient contiguous past
bars arrive. Old context gaps remain visible even after warmup recovers.

For admitted splits, actual FeatureHistory and readiness/freshness gates remain
authoritative. Test-period gaps can reset history, warm features again, and leave
eligible outcomes incomplete. Sample sufficiency does not guarantee every numeric
feature is defined (for example a flat efficiency denominator). Missing optional
trade/book/mark/funding streams remain unavailable; warmup does not invent them.

**Context is not parameter fitting. Walk-forward validation is not automatic
optimization.** No setting is learned from context, test returns or another split.

### Orchestration and test-only results

The evaluator validates the dataset and captures a fixed configuration before
awaiting. It reuses the following unchanged Phase 6 components:

1. `HistoricalReplay.frames`, its historical clock and owned Feature/Strategy/
   Decision engines. Each frames invocation creates a fresh Hub, history, clock,
   engines and feature task. A rolling split is also compared against an entirely
   independent BacktestEngine replay of precisely its own context and test rows.
2. `BacktestEvaluator.advance` then `accept` for **test bars only**. Context frames
   build analytical state but their decisions are never admitted to test outcomes.
3. `BacktestEvaluator.finish` and `calculate_metrics(..., cutoff=test_end)` for
   existing outcome math and boundary-censored metrics.
4. `DatasetIdentity`, settings/policy identity helpers and the repository's
   canonical SHA-256 `identity` helper.

Existing next-exact-bar-open entry, H=5 default holding horizon, fee=5bps/side and
slippage=2bps/side are unchanged. The evaluator never consumes a row after the
window's test_end, even when such rows exist in the full dataset. It does not borrow
an exit tail from another window. Pending outcomes keep existing missing-entry,
missing-horizon or dataset-ended reasons, with no fabricated exit or returns.
Metrics additionally flag horizons beyond the window cutoff as boundary-censored.

Decision-generation evidence ends at the decision's own close. Later entry/exit
bars can legitimately change that decision's eventual hypothetical outcome; they
cannot modify the earlier feature/strategy/decision frame. Only originating
decision boundaries in `(test_start, test_end]` enter test counts.

Window results retain split metadata, local input content ID, engine/settings IDs,
test-only HistoricalDecisions and outcomes, exact existing gross/cost/net metrics,
warnings and a result ID. Compact evidence records hash the actual bar, feature
snapshot and strategy snapshot and retain the decision ID, symbol and boundary.
Full feature frames are observed directly in tests, not retained in final results.
The existing numeric regime context inside HistoricalDecision is unchanged; Batch
2 adds no regime labels, buckets or regime metrics.

Zero ELIGIBLE decisions are valid (`VALID_NO_SIGNALS`). An empty test observation
range can also be evaluated after valid context, with `NO_TEST_OBSERVATIONS` and
gap coverage. Incomplete outcomes are marked `INCOMPLETE_OUTCOMES`; boundary
censoring is separate. Rejected windows remain in the result list. Analytical
exceptions propagate rather than returning partial fabricated metrics. Cancellation
and error tests verify feature tasks stop and Hub subscribers are removed.

### Identities and determinism

All identities use existing canonical SHA-256 conventions without clocks, UUIDs,
paths or machine metadata:

| Identity | Content |
| --- | --- |
| Dataset | Entire canonical dataset plus scope/bounds, unchanged from Batch 1 |
| Protocol (`walk_protocol`) | Version/schema, mode, sizes, warmup, overlap/partial policies and symbol/interval scope; excludes full dataset ID |
| Structural split (`walk_split`) | Semantic protocol ID, ordinal and context/test boundaries |
| Window input | Phase 6 DatasetIdentity over only the split's actual context and test rows |
| Window result (`walk_window`) | Split metadata excluding global dataset ID, local input ID, engine/settings IDs, status, evidence, decisions, outcomes, metrics and warnings |
| Evaluation (`walk_evaluation`) | Full dataset ID, protocol ID, engines/settings, plan status and ordered window result IDs |

The global dataset reference is still carried on each split. Therefore unrelated
future mutations change that reference and the whole evaluation ID, while earlier
structural/local result IDs remain identical. No-lookahead comparisons exclude only
the global provenance field, not decisions, metrics or evidence. These identities
are content checks, not authenticated source provenance.

Repeat-run tests require byte-identical evaluation JSON and successful typed JSON
round-trip. Tests also prove dataset, protocol, feature/strategy/decision/backtest
settings are unchanged and reduced ambient Decimal precision does not alter results.

### Direct no-lookahead evidence

- In both EXPANDING and ROLLING, 135-bar fixtures use 30-slot tests. Mutating bar
  95 (in a later window) leaves the first full window unchanged; mutating bar 120
  leaves the first two unchanged. The first window is required to contain completed
  outcomes, preventing empty-outcome equality from passing vacuously.
- Comparisons cover full captured replay frames (features, strategies, decisions),
  structural IDs/bounds, local input/result IDs, eligible decision IDs, completed
  outcome IDs, metrics and warnings. Later mutated-window evidence must differ.
- A direct t+1 mutation leaves every captured frame through t unchanged. A separate
  test changes a completed signal's later entry price: the originating eligible
  decision remains equal, while entry price, returns and outcome ID change.
- Adding a future ETH row within an already declared fixed scope leaves an earlier
  window unchanged. Reversing all equal-time symbol arrivals and overall input
  order gives identical splits, full frames, decisions, outcomes and result JSON.
- Independent replay comparisons prove context decisions are excluded from test
  metrics and rolling windows reconstruct only their declared context.

### Resource bounds and the missing-range correction

At most 256 splits, 200,000 cumulative replay rows (context plus test, counting
repeated use across windows) and 100,000 cumulative test rows are planned.
Budgets are checked before replay, including scheduled rejected windows. Individual
protocol size settings are bounded at 100,000 slots. These are resource guards,
not thresholds selected from returns. Over-budget requests fail explicitly.

An expanding **context slot count** is not capped by the dataset's input row limit.
The regression uses one stored bar over 100,100 minutes: the second split correctly
reports 100,050 context slots and one observed boundary, then rejects insufficient
context explicitly. Missing slots are counted arithmetically, not allocated as bars.
This fixes the earlier output-contract coupling between slots and stored rows.

The existing FeatureHistory limit (500 by default) still bounds analytical memory
inside each replay. Expanding context can be larger, but does not change that
production reseeding/eviction behavior. Planning and replay remain finite in-memory
work; this batch adds no distributed, persistent or cached evaluation service.

### Exact Batch 2 validation results

All commands used `backend/.venv/Scripts/python.exe` from `backend`. Completed
results were retained across usage-limit interruptions; no unnecessary full-suite
or post-documentation Python rerun was performed.

| Selection / command | Result |
| --- | --- |
| Initial protocol/split subset | 69 passed in 1.47s |
| Recovered initial complete focused run | 1 failed, 87 passed in 42.54s |
| Corrected horizon test plus new sparse-slot regression, before slot fix | 1 failed, 1 passed in 3.34s |
| Same two affected tests after slot fix | 2 passed in 2.64s |
| `python -m pytest tests/test_walk_forward_protocol.py tests/test_walk_forward_evaluator.py -q` | **91 passed in 50.42s**, exit 0 |
| `python -m pytest tests/test_historical_dataset.py tests/test_historical_dataset_codec.py tests/test_historical_dataset_replay.py -q` | **154 passed in 5.19s**, exit 0 |
| `python -m pytest tests/test_historical_replay.py tests/test_backtest_engine.py tests/test_backtest_evaluator.py tests/test_backtest_contracts.py tests/test_backtest_math.py -q` | **205 passed in 16.65s**, exit 0 |
| `python -m pytest tests/test_feature_history.py tests/test_feature_engine.py tests/test_feature_models_settings.py -q` | **195 passed in 0.80s**, exit 0 |

The recovered failure already matched Phase 6 decisions, outcomes and metrics;
its first cutoff simply contained no completed outcomes. The fixture now straddles
completed and censored horizons without altering any strategy or cost setting.
Future-mutation tests were strengthened to require nonempty completed evidence.
The sparse-range failure was corrected only in the new split output contract.
There are no outstanding test failures. DecisionEngine is reached through unchanged
HistoricalReplay, not a separate Batch 2 decision path.

### Batch 2 checkpoint limitations (subsequently extended)

- Full-phase backend/frontend regression remains for Batch 7. The baseline's two
  existing dependency deprecation warnings remain; dependencies were not changed.
- Context sufficiency requires every scoped symbol; one deficient symbol rejects
  that split rather than silently evaluating a different symbol universe.
- Warmup metadata mirrors existing feature sample contracts and is tested against
  FeatureEngine status. Future feature additions must update this admission rule.
- Tail censoring deliberately excludes outcomes whose required evidence crosses
  test_end. Window metrics are signal-level cohorts, not deployable portfolio PnL.
- Overlapping windows can contain the same analytical decision. This batch provides
  no aggregate metric; later reporting must not treat overlapping samples as independent.
- Frame hashes support reproducibility, not recovery of full snapshots without
  replay. Source authenticity, unavailable non-candle context and real fill quality
  remain outside these contracts.
- At this checkpoint, Batch 3 regime classification, Batch 4 cost comparisons,
  Batch 5 ValidationReport and Batch 6 API/frontend were still pending; subsequent
  sections record their implementation. No optimizer or experiment registry was added.
- No prior formula, dataset semantic, private/account service or execution boundary
  was changed. The historical Batch 2 review stop was later superseded by continuation.

### Final Batch 2 audits and working tree

Inspection of all three new production modules and the narrow AST/source audit
passed: no network acquisition/client, exchange account/private service, credential,
order/transfer/P2P execution, leverage execution, intent generation, RiskEngine or
PaperExecutionGateway invocation, AI/ML/optimizer integration or candle construction.
Identity paths contain no wall-clock/UUID source. Existing replay/evaluator calls,
test-window filtering, cutoff handling and deterministic ordering were reviewed.

`git diff --check` passed. Separate checks also found no whitespace errors in the
untracked Python files or this report. The only Git notices concern LF/CRLF
conversion. `git diff --exit-code -- frontend/src/types/generated.ts` returned 0
with no content diff. No frontend regeneration or line-ending cleanup was performed
in Batch 2. The merge-base remains the accepted Phase 9 SHA above.

Historical Batch 2 checkpoint inventory: **4 modified tracked files, 12 new untracked files**
(16 affected paths across both batches). Three tracked files have content changes;
the fourth is the generated-types line-ending change. The five new Batch 2 Python
files total **936 lines**. All 11 new Python files across both batches total
**1827 lines**, plus this report. No accidental artifact or additional file was found.

`git diff --stat` excludes the untracked implementation/tests/report:

```text
 CODEX_TASK.md        |  5 ++++
 docs/ARCHITECTURE.md | 64 ++++++++++++++++++++++++++++++++++++++++++++++++++++
 docs/MODULE_MAP.md   | 26 +++++++++++++++++++++
 3 files changed, 95 insertions(+)
```

`git status --short`:

```text
 M CODEX_TASK.md
 M docs/ARCHITECTURE.md
 M docs/MODULE_MAP.md
 M frontend/src/types/generated.ts
?? backend/src/application/historical_dataset.py
?? backend/src/application/historical_dataset_codec.py
?? backend/src/application/walk_forward.py
?? backend/src/application/walk_forward_evaluator.py
?? backend/src/domain/historical_dataset.py
?? backend/src/domain/walk_forward.py
?? backend/tests/test_historical_dataset.py
?? backend/tests/test_historical_dataset_codec.py
?? backend/tests/test_historical_dataset_replay.py
?? backend/tests/test_walk_forward_evaluator.py
?? backend/tests/test_walk_forward_protocol.py
?? docs/PHASE_10_REPORT.md
```

At this historical checkpoint no commit, push, merge, reset, cleanup or Batch 3
work had been performed. The current final inventory appears below.

**PHASE 10 BATCH 2 READY FOR REVIEW**

## Batch 3 — causal descriptive regimes

`domain/validation_regimes.py`, `application/validation_regimes.py` and
`tests/test_validation_regimes.py` are new. Walk-forward evidence now includes one
immutable assignment captured from the actual production feature frame at the
decision boundary. No Phase 1–9 engine or formula changed.

Fixed `causal-regimes-v1` engineering rule (never fitted to returns): signed
normalized EMA separation strictly above/below ±0.0005 with directional efficiency
>= 0.25 yields UPTREND/DOWNTREND; otherwise RANGE. Missing/stale regime evidence
yields UNKNOWN. Trailing ATR/close <= 0.005 is LOW, > 0.005 through 0.02 MEDIUM,
and > 0.02 HIGH. Missing/stale volatility evidence yields UNKNOWN independently.
Snapshot generation and closed-candle boundaries must equal the replay boundary.
No global distribution, future quantile or eventual outcome enters classification.
Definition and assignments have SHA-256 identities, evidence values and explicit
unknown reasons. Assignments are descriptive and never fed back into decisions.

Independent symbol, trend and volatility partitions retain all empty groups;
there is no Cartesian cross-product. Each uses existing Phase 6 metrics, including
decision/eligible/completed/incomplete counts, net/gross/cost returns, historical
win rate (wins divided by non-flat completed outcomes), normalized signal drawdown,
and separate count/min/max/mean confidence and signed score summaries. Fewer than
30 completed outcomes always produces SMALL_SAMPLE; empty groups add EMPTY_GROUP.
Confidence is evidence quality, not profit probability; historical hit rate is not
a future probability. The additive signal curve is not portfolio equity.

Batch 3 gate (repository virtual environment, exit 0):

- `python -m pytest tests/test_validation_regimes.py -q`: **44 passed in 5.00s**.
- Regime + Batch 1/2 + feature history/engine/settings + backtest
  metrics/engine/evaluator: **541 passed in 78.57s (0:01:18)**.
- `python -m pytest tests/test_indicators_context.py tests/test_indicators_trend_momentum.py -q`:
  **165 passed in 0.41s**.

Tests cover exact threshold edges, all labels, missing/stale dependencies,
independent buckets, empty/sparse/minimum samples, finite summaries, permutation
and ambient-precision stability, immutable values and fixed definitions. Future
price and future volatility mutations preserve earlier feature/strategy/decision
evidence and assignments, even when the eventual outcome changes.

## Batch 4 — fixed signal cost sensitivity

New `domain/validation_costs.py`, `application/validation_costs.py` and
`tests/test_validation_costs.py` reuse Phase 6 `outcome_returns` and metrics without
replay. Scenarios are baseline plus fixed per-side (fee, adverse slippage) bps
(0,0), (10,5), (20,10), deduplicated and sorted by assumptions, never returns.
Default baseline is (5,2); both inputs must be 0–100 bps in this research surface.
The upper bound keeps assumptions plausible and below the range where extreme
fee/slippage interactions could defeat monotonic adverse-cost interpretation.
This does not change the broader Phase 6 cost contract. Maximum four scenarios.

Raw entry/exit prices/times, horizon, direction, decisions, diagnostic counts,
excursions and incomplete reasons remain fixed. Complete returns alone are
recomputed by existing math; incomplete evidence stays incomplete. Baseline
outcomes retain exact identities; alternative outcome IDs hash source outcome
and scenario. Scenario IDs hash the cost model version and only fee/slippage.
Reports retain separate gross, cost and net aggregates, mean cost, normalized
signal drawdown and explicit per-decision net sign changes versus baseline.
No portfolio equity claim, strategy search, new signal generation or ranking.

Batch 4 gate, exit 0:

- `python -m pytest tests/test_validation_costs.py -q`: **29 passed in 1.29s**.
- Cost + regime + both walk-forward + Phase 6 math/evaluator suites:
  **232 passed in 56.86s**.

Tests independently cover LONG/SHORT prices from 1 to 1000 around raw entry 100,
zero-cost reconciliation, baseline equality, monotonic adverse costs, unchanged
provenance, incomplete preservation, deterministic order/identities, finite bounds,
duplicate scenarios, sign changes, ambient precision and a replay-forbidden test.

## Batch 5 — versioned reproducible report

New report domain, assembler, codec, validation-metric adapter, synthetic export
fixture and `scripts/export_validation_report.py` aggregate the existing evidence.
Dataset manifest, complete protocol/plan, engine/settings identities, compact
feature/strategy hashes, decisions/outcomes/regime assignments, per-window metrics,
symbol/regime partitions, fixed cost comparisons and limitations remain inspectable.
Report assembly does not rerun engines. No context decision enters test metrics.

Non-overlapping tests pool unique captured decisions with their originating-window
cutoffs. The adapter preserves Phase 6 metrics and carries the count of explicitly
window-censored incomplete outcomes into aggregate, regime and cost summaries.
It rejects completed exits borrowed across a cutoff. Overlapping test protocols
retain window results but deliberately expose no pooled aggregate; warning
OVERLAP_AGGREGATE_WITHHELD prevents duplicate evidence being counted as independent.
Rejected context, no evaluated test observations, valid no-signal windows, gaps,
incomplete outcomes and sparse/empty groups remain separate diagnostics.

`validation-report-v1` uses sorted compact JSON, exact Decimal strings and UTC
microsecond timestamps. SHA-256 of canonical content is both checksum and report
identity suffix. Optional generated_at is excluded from that content hash; a
normal deterministic export leaves it null. Decode rejects unsupported versions,
unknown fields, duplicate keys, float tokens, nonfinite values, checksum changes,
inconsistent evaluation identities and altered derived metrics. It rebuilds
summaries from captured evidence; this verifies integrity, not dataset authenticity.
Report bytes are capped at 32 MiB and captured test decisions at 20,000.

The Decimal literal conversion required by strict JSON round-trips was corrected
without making regime thresholds configurable. No Phase 1–9 formulas changed.

Batch 5 gate, exit 0:

- `python -m pytest tests/test_validation_report.py -q`: **21 passed in 9.16s**.
- All Batch 1–5 suites: **339 passed in 69.33s (0:01:09)**.
- `python scripts/export_validation_report.py --check`: two byte-identical
  synthetic reports verified, **162266 bytes**; identity
  `validation_report_87f1cf7913db4fdc29ff5077da29fc8a46784a0a898433460b68a11346c2ae8e`.

Offline usage: `python scripts/export_validation_report.py --output report.json`
exports the explicitly synthetic example. Add `--dataset canonical-dataset.json`
for a validated local public dataset and optionally `--mode ROLLING`; the fixed
default protocol and analytical settings are not fitted. `--check --output FILE`
checks an existing artifact against replay; `--check` alone compares two fresh
exports. There is no implicit write destination, network fetch or experiment store.

## Batch 6 — read-only telemetry and dashboard

**BATCH 6 COMPLETE**: backend 115 passing tests; frontend 95 passing tests at this
gate; TypeScript/build and generated contracts passed; 21 paths, all GET-only.

`GET /validation/status` and `GET /validation/latest` project one validated report
loaded once at lifespan startup from server-only `VALIDATION_REPORT_PATH` (or the
explicit create_app argument). No path means UNAVAILABLE/NO_REPORT_CONFIGURED;
missing and invalid reports have sanitized diagnostic codes, never local paths.
No HTTP read performs file loading, analytical replay, report computation or writes.
There is no report discovery/store, upload, reload, run, optimize or financial API.
Configuration changes require a backend restart. Existing paper lifecycle and
source behavior are unchanged; offline shutdown still leaves no hub subscribers.

The projection omits raw decisions/outcomes and local source labels; it includes
identities, counts, windows, coverage, fixed definitions, metric/group/cost summaries,
warnings and limitations. The existing dashboard contract exporter now also emits
`validation.schema.json`, with separate canonical generated TypeScript types.
The original generated.ts content remains unchanged; generator output now respects
the Windows working-tree newline convention and --check compares canonical text.

Backtest & Validation keeps its existing educational material and adds an on-demand
Validation panel. Simple mode explains context/test separation, sparse groups,
incomplete evidence, signal returns and costs. Advanced adds exact IDs, checksum,
engine/settings identities, thresholds, boundaries, coverage and distributions.
Scope selection and Simple/Advanced only change presentation. The client makes
credential-free GETs with a 5s timeout, cancellation and bounded retry; failed reads
clear previous report display. Ten new glossary entries retain the old numeric
regime explanation under its existing key. PAPER/VIRTUAL and historical-not-future
probability disclaimers remain visible.

Batch 6 gates, exit 0:

- Initial new API suite: **15 passed, 2 existing warnings in 6.83s**.
- Final new API + report + existing live-paper API gate: **115 passed, 2 warnings in 15.15s**.
- Full frontend: **4 files, 95 passed in 9.20s** (18 new validation tests).
- Dashboard/validation schema, existing four dashboard examples and new validation
  example export checks passed. Type generation --check passed.
- TypeScript/Vite build passed: 137 modules, **181ms**; main JS **501.06 kB**
  (gzip 139.32), on-demand Validation JS **25.31 kB** (gzip 6.05).
- `git diff --exit-code -- frontend/src/types/generated.ts`: exit 0.

The first regression caught a duplicate glossary key (fixed by preserving the old
key and using causal_regime), and the intentional route count increase from 19 to
21 (the test now checks every path is GET-only). Two new UI tests initially used
ambiguous text queries; they now assert the intended visible paragraph/window.
No production requirement or safety assertion was weakened.

Remaining build warning: the main bundle is just over Vite's 500 kB advisory after
adding glossary/schema support. Validation itself is split on demand; dependency
or unrelated-page restructuring is deliberately deferred.

## Batch 7 — release evidence

### Deterministic medium fixture and causality

`tests/validation_release_fixture.py` constructs 559 synthetic finalized bars over
280 one-minute slots and two symbols. ETHUSDT slot 120 is deliberately absent;
no bar is filled. The fixed protocol uses 50 warmup/minimum-context bars, 23 test
bars, a 23-bar step, partial-window inclusion and no overlap, producing 10 windows.
The continuation note's five-window count predates the 23-bar adjustment; the
current fixture and release assertion both explicitly require **10 windows**.
ROLLING uses exactly 50 context bars; EXPANDING retains all prior context. Fixed
repository strategy/decision/feature defaults and default H=5, fee=5/slip=2 bps
remain unchanged. The 23-bar boundary explicitly exercises both completed and
window-censored outcomes. Gapped context is rejected; later contiguous history
can recover. Later flat windows naturally produce no eligible signals.

`test_validation_release.py` replays both modes twice with reversed input order
under a strict network block. Entire canonical bytes match: dataset/protocol/split
identities, complete historical decisions/outcomes, actual frame hashes, regime
definition/assignments, cohort metrics, cost scenarios and final report ID.
Assertions require UPTREND/DOWNTREND/RANGE and LOW/MEDIUM/HIGH/UNKNOWN evidence,
completed and incomplete outcomes, no-signal and rejected-context cases. The
final report passes through the real cached projection and ASGI GET route.
The medium frontend fixture is generated from that projection, never hand-edited;
a component test renders its multiple symbols, 559 bars and explicit missing bar.

Future mutation changes only BTCUSDT slot 230's close/high/quote volume. Earlier
actual FeatureSnapshots, StrategySnapshots, DecisionRecords, regime assignments,
completed outcomes, window analyses and structural split IDs remain equal.
The later dependent window result changes. Both modes are tested. Repricing the
same captured evidence under all four costs preserves decision IDs and boundaries,
keeps zero-cost equal to gross, and cannot increase any completed net return as
adverse cost increases. No summary feeds back into a production analytical engine.

| Medium run | First replay + report | Canonical bytes | Report identity |
| --- | --- | --- | --- |
| EXPANDING | 22.894s | 1048278 | `validation_report_faea43dd61b75e1b0618e2a3f7827f272714dde3198bcf3c2f575d675ab8ecfc` |
| ROLLING | 8.550s | 1045983 | `validation_report_0dd423002ce03e9c6b6f2b78eb7874d1655863afb90b49da4d3e6416010f3848` |

Shared dataset ID:
`historical_dataset_53cd1b364efdc062e3857d5760b6a7254a1529cd6d712e13d6f94f1a34bf8ab5`.
EXPANDING protocol:
`walk_protocol_03f839a9c3cc13f4060e11a9c3115230f5dda906102747b8ffd1283947e7f029`.
ROLLING protocol:
`walk_protocol_acfd9221f866fe6b8be4c7be61fc34a0013ad7b5a9e43707898ad53baaeda367`.
These are measured local durations, not performance promises or CI time thresholds.

Regime definition identity:
`regime_definition_6c19d608d6c2588e6dad344205fccf30fdc2ce4626e6f1b053b6b40c498b5468`.
Default per-side cost scenario identities:

| Fee / slippage bps | Identity |
| --- | --- |
| 0 / 0 | `cost_scenario_24f524ebd0bf63c0754cdd48c626d971601514c1984ceba39ce48a60d3ac5d0e` |
| 5 / 2 (baseline) | `cost_scenario_34ead1eb52f360ac19130730bf047add2530639085b89c1e4c7c5e10d08a00ad` |
| 10 / 5 | `cost_scenario_b6b7332df89e38875a73a4949781503dd0b4841169435230cb4215184342596f` |
| 20 / 10 | `cost_scenario_e81dd1c05f5faa0948d1391a6dfab026b4cfec3decdf341f9681b7bf940e1f7c` |

Fresh independent EXPANDING replays intentionally revisit past context; cumulative
replay budgets cap this work. Cohorts are three independent partitions, with four
cost assumptions, not a symbols × regimes × costs Cartesian search.

### Bounds and release corrections

| Resource | Limit / behavior |
| --- | --- |
| Raw dataset | 100000 rows including duplicates, 128 symbols, 64 MiB JSON |
| Decimal input | 128 canonical coefficient digits, absolute exponent <= 1000 |
| Plan | 256 splits; 200000 cumulative replay rows; 100000 test rows |
| Missing time | Arithmetic interval slots; no materialized missing bars; 100050-slot sparse context regression retained |
| Regime groups | symbols + 8 per analysis; 4096 total report groups |
| Costs | Four unique fixed scenarios maximum; each input 0–100 bps per side |
| Report | 20000 captured test decisions; 32 MiB canonical JSON |
| API/browser | One startup-loaded projection; 8 MiB response cap on both sides before browser JSON parsing |
| Fixtures | Small projection 59657 bytes; medium projection 185105 bytes; test-only assets |

Bounds tests exercise model, assembler, codec, projection and streamed browser
responses (including missing Content-Length). No unbounded timeline expansion or
report registry is added. The synthetic export now honors an explicit --mode
ROLLING; its default EXPANDING identity and 162266-byte fixture remain unchanged.

The first release run correctly failed because 50-bar fixture tests completed all
eligible horizons. The protocol now uses the already established 23-bar boundary;
no score/decision/indicator threshold was changed. A test-only Windows teardown
error came from blocking pytest's internal socket pair: the network prohibition
is now scoped strictly around real replay, restored before framework teardown.
The successful release rerun had no such errors/warnings.

### Statistical interpretation and deliberately deferred scope

Historical validation is not a prediction of future profit.
Confidence is evidence/agreement quality, not probability of profit.
Historical hit rate is a sample statistic, not future win probability.
Cost scenarios are assumptions, not forecasts.
Regime labels are descriptive research categories, not execution instructions.

The report validates fixed signal-level outcomes. Phase 7 capital allocation and
portfolio equity are unchanged and are not rerun as a separate validation report
family. Normalized signal drawdown must not be interpreted as portfolio drawdown.
Overlapping windows keep individual evidence but withhold pooled metrics; signals
can also share horizons within one disjoint window, so observed samples are not
claimed statistically independent. No confidence intervals, inference test or
probability-of-profit estimate is added. Minimum sample 30 is a disclosure rule,
not a claim of statistical adequacy. Fixed regime thresholds do not adapt to the
dataset or interval. Sparse and empty partitions remain visible.

Dataset checksums cannot certify a historical provider or resolve survivorship
bias; manifest coverage outside declared bounds is unknown. Only finalized OHLCV
is available in these fixtures, with no depth reconstruction, execution-quality
model, funding debit, fills, market-impact calibration or live-data download.
Reports require offline export and restart for loading; no archive/discovery,
hot reload, database, cloud store, browser file picker or job runner is provided.
No private/account access, credentials, real/testnet orders, transfers/P2P,
leverage, intent/gateway/risk execution, AI/ML/RL, optimization or Phase 11 is added.

### Validation commands and audit evidence

- `python -m pytest tests/test_validation_release.py -q -s`: **4 passed in 132.01s (0:02:12)**.
- All ten Phase 10 test modules: **360 passed, 2 existing warnings in 207.85s (0:03:27)**.
- Final CLI mode fix + report/API bounds regression: **39 passed, 2 warnings in 12.83s**.
- Initial complete backend run: **5 failed, 2766 passed, 2 warnings in 566.08s
  (0:09:26)**. All failures were exact pre-Phase-10 OpenAPI route expectations in
  decision, feature, strategy, persistence and portfolio test files. Inspection
  confirmed the only additions were the two specified validation GETs. Assertions
  now explicitly retain them and all GET-only/no-execution-field constraints.
  No feature, strategy, decision, portfolio or persistence production code changed
  for this compatibility correction.
- The five formerly failing assertions: **5 passed, 2 warnings in 3.17s**.
- Their complete affected modules plus validation API: **119 passed, 2 warnings
  in 43.76s**, before the final full-suite rerun.
- Earlier completed frontend gate, including lazy dashboard navigation:
  **4 files, 100 passed in 8.33s**. The final requested rerun passed the same
  **100 tests in 26.66s**, with no code changes between runs.
- `npm.cmd ci`: **133 packages added, 134 audited in 55s; 0 vulnerabilities**.
- `npm.cmd run types`, `npm.cmd run types -- --check`: passed; original generated.ts diff is empty.
- `npm.cmd run build`: final TypeScript and Vite passed; **137 modules, 400ms**
  (earlier completed build: 498ms);
  main JS **501.06 kB** (gzip 139.32), Validation chunk **25.95 kB** (gzip 6.32).
- `python -m pip check`: **No broken requirements found.**
- Dashboard schema/catalog, all four prior runtime fixtures, both validation
  projection fixtures and `export_validation_report.py --check`: verified.
- The explicit `--mode ROLLING --check` CLI also reproduces the small example:
  **162260 bytes**, `validation_report_38f42c0607763ac6fa6c2a1ef9469f70da24cd7a86730ea812ae45ac96400050`.
- Explicit import/OpenAPI + offline lifespan with a valid configured report:
  **21 paths, 21 GET-only, 0 mutation routes; network blocked, all tasks stopped,
  0 subscribers after shutdown**.
- AST import/call audit across **17 Phase 10 production modules** found no network,
  private/execution/gateway/AI/ML/optimizer imports or prohibited intent/risk calls.
  The CLI/export helpers also operate exclusively on explicit local files.
  Frontend reads use fixed same-origin GET paths with credentials omitted.
- Changed/new-file scans found no credential assignments, private-account endpoints,
  key material, untracked databases/env files/debug logs/caches/build output.
  Legitimate generated fixtures are 59.7/185.1 kB, not large historical dumps.
- CI runs `python -m pytest` once, including the four release tests. It does not
  invoke the expensive release test module a second time. Separate canonical
  report and small/medium projection checks verify checked-in frontend artifacts;
  the medium projection check performs one EXPANDING replay, not the four-test
  reproducibility/mutation suite. Both generated TypeScript contracts are checked.
  Market data, live paper and persistence are explicitly disabled in the backend
  CI environment. Validation requires no downloaded market data, external HTTP,
  account access or credentials; normal dependency installation still uses the
  package registries. No remote GitHub Actions result is claimed.

The two backend warnings are existing Starlette/httpx TestClient and AnyIO
BlockingPortal deprecations. Dependencies were not changed. The remaining Vite
501.06 kB advisory is documented; lazy-loading keeps validation code separate.

### Complete file inventory

Created production, offline tools and generated contracts:

```text
backend/scripts/export_validation_report.py
backend/src/api/validation.py
backend/src/application/historical_dataset.py
backend/src/application/historical_dataset_codec.py
backend/src/application/validation_costs.py
backend/src/application/validation_example.py
backend/src/application/validation_metrics.py
backend/src/application/validation_regimes.py
backend/src/application/validation_report.py
backend/src/application/validation_report_codec.py
backend/src/application/validation_telemetry.py
backend/src/application/walk_forward.py
backend/src/application/walk_forward_evaluator.py
backend/src/domain/historical_dataset.py
backend/src/domain/validation_costs.py
backend/src/domain/validation_regimes.py
backend/src/domain/validation_report.py
backend/src/domain/walk_forward.py
frontend/src/api/validation.schema.json
frontend/src/api/validation.ts
frontend/src/hooks/useValidation.ts
frontend/src/pages/Validation.tsx
frontend/src/types/validation.generated.ts
```

Modified production/tooling/generated help:

```text
backend/scripts/export_dashboard_contract.py
backend/src/application/explanations.py
backend/src/main.py
frontend/scripts/generate-types.mjs
frontend/src/help/catalog.json
frontend/src/layouts/Dashboard.tsx
frontend/src/pages/Backtest.tsx
```

Created tests, exporters and test fixtures:

```text
backend/tests/export_validation_example.py
backend/tests/test_historical_dataset.py
backend/tests/test_historical_dataset_codec.py
backend/tests/test_historical_dataset_replay.py
backend/tests/test_validation_api.py
backend/tests/test_validation_costs.py
backend/tests/test_validation_regimes.py
backend/tests/test_validation_release.py
backend/tests/test_validation_report.py
backend/tests/test_walk_forward_evaluator.py
backend/tests/test_walk_forward_protocol.py
backend/tests/validation_release_fixture.py
frontend/src/test/fixtures/validation.json
frontend/src/test/fixtures/validation.medium.json
frontend/src/test/validation.test.tsx
```

Modified existing test files (only deliberate API route expectations/assertions):

```text
backend/tests/test_decision_api.py
backend/tests/test_feature_api.py
backend/tests/test_live_paper_api.py
backend/tests/test_paper_persistence_failures.py
backend/tests/test_paper_portfolio_engine.py
backend/tests/test_strategy_api.py
```

Created documentation: `docs/PHASE_10_REPORT.md`. Modified documentation:
`CODEX_TASK.md`, `README.md`, `backend/README.md`, `frontend/README.md`,
`docs/ARCHITECTURE.md`, `docs/MODULE_MAP.md`, `docs/USER_GUIDE.md`.
Modified CI: `.github/workflows/backend-ci.yml`.

The canonical generator removed line-ending-only changes from the original
`frontend/src/types/generated.ts` and `frontend/src/api/dashboard.schema.json`;
neither has a semantic diff. No dependencies or lockfiles changed. Browser
verification is through generated contracts, jsdom component/client/navigation
tests and TypeScript/Vite; no manual browser visual review is claimed.

## Final release gate — 2026-09-21

The interrupted full rerun completed successfully and its exit-0 result was
recovered from the existing process, without launching another full suite:

```text
python -m pytest
collected 2771 items
2771 passed, 2 warnings in 539.39s (0:08:59)
```

**0 failed, 0 skipped.** This includes all **2410 accepted baseline tests plus
361 Phase 10 tests**. A final `--collect-only -q` over the ten Phase 10 modules
confirmed **361 collected in 0.91s**. The earlier dedicated Phase 10 run had 360
passing tests; the extra real-CLI mode regression was subsequently included in
the passing 39-test focused gate and this complete 2771-test regression. Collection
is reported as collection, not as a second targeted execution.

The full-suite log is `hinto-phase10-final-rerun-20260921.log` in the local temporary
directory. The earlier five-failure run is retained above for auditability; it is
superseded by this passing rerun. No production code changed after this full run
started. Final changes only complete documentation and status wording.

| Final command / check | Actual result |
| --- | --- |
| `python -m pip check` | `No broken requirements found.`; exit 0 |
| `python scripts/export_dashboard_contract.py --check` | Schema and explanation catalog verified; exit 0 |
| `python tests/export_dashboard_examples.py --check` | All four existing runtime fixtures verified; exit 0 |
| `python scripts/export_validation_report.py --check` | Two deterministic default exports match; **162266 bytes**; original report ID retained; exit 0 |
| `python scripts/export_validation_report.py --mode ROLLING --check` | Two deterministic ROLLING exports match; **162260 bytes**; exit 0 |
| `python tests/export_validation_example.py --check` | Small projection verified; exit 0 |
| `python tests/export_validation_example.py --medium --check` | Medium projection verified; exit 0 |
| `npm.cmd test` | **4 files, 100 passed in 26.66s**, 0 failed, 0 skipped; exit 0 |
| `npm.cmd run types` | Both canonical contracts generated; exit 0 |
| `npm.cmd run types -- --check` | Both canonical contracts verified; exit 0 |
| `npm.cmd run build` | TypeScript passed; Vite **137 modules, 400ms**; exit 0 |
| `git diff --exit-code -- frontend/src/types/generated.ts frontend/src/api/dashboard.schema.json` | No diff, including no accidental newline-only change; exit 0 |
| Explicit application import/OpenAPI inspection | **21 paths, all 21 GET-only**, no POST/PUT/PATCH/DELETE operations |
| Explicit offline lifespan smoke | Valid report loaded; DNS/socket connections blocked during replay and lifespan; **3 background tasks stopped; 0 subscribers** |
| Final changed/new-file inventory | **21 tracked modified + 39 untracked new = 60 paths**; no staging |
| New Python syntax/whitespace audit | **30 files passed** |
| Accidental artifact inventory | No untracked/tracked runtime caches, local environment files, databases, logs, dependency trees or build output; no private-key blocks |
| `git diff --check` | Exit 0; only Git's existing LF/CRLF conversion notices |

The final frontend execution includes lazy-loaded Dashboard navigation, Simple and
Advanced presentation, no-report and failed-refresh states, sparse samples, causal
regimes, fixed costs, incomplete evidence, historical-not-prediction explanations,
absence of financial controls, and oversized streamed response rejection. Generated
fixtures still derive from the actual backend projection.

The previous production-path AST/source audit remains applicable to all 17 new
production modules and the export CLI; no production module changed since that
audit. It found no private/account/credential/signing, order/transfer/P2P,
leverage/liquidation, intent/risk/gateway execution, AI/ML/RL, optimization,
return-based fitting or automatic strategy-ranking integration. Existing Phase
1–9 engine and portfolio formulas remain unchanged.

Review of all six modified legacy test files confirms only intentional route/schema
expectation changes: the live-paper assertion was updated in Batch 6; the other
five were corrected after the first complete regression. API safety, forbidden
execution fields, persistence behavior and portfolio/decision/strategy checks were
preserved; several now assert GET-only across every route explicitly.

All seven batch acceptance gates and the final backend, frontend, types, build,
dependencies, contracts, exports, OpenAPI, offline lifecycle, source-boundary and
Git hygiene gates pass. No unresolved acceptance failure remains. The two existing
dependency deprecations and Vite's 501.06 kB main-bundle advisory remain documented
warnings. The lazy Validation chunk remains 25.95 kB. Statistical, data-authenticity
and local-report-loading limitations described above are deliberately retained.

No commit, push, merge, history rewrite, working-tree discard or Phase 11 work was
performed. Normal ignored virtual environments, caches, node_modules and dist from
the requested checks remain local and are not added to the review diff.

## Final Git evidence

`git branch --show-current`: `phase-10-validation-lab`.
`git merge-base HEAD main`: `2925f38d6423c28e92a39c9758766112bd197714`.
The branch remains up to date with its local origin tracking reference; no fetch,
commit or push was performed in this final continuation.

`git status --short` (all changes preserved, none staged):

```text
 M .github/workflows/backend-ci.yml
 M CODEX_TASK.md
 M README.md
 M backend/README.md
 M backend/scripts/export_dashboard_contract.py
 M backend/src/application/explanations.py
 M backend/src/main.py
 M backend/tests/test_decision_api.py
 M backend/tests/test_feature_api.py
 M backend/tests/test_live_paper_api.py
 M backend/tests/test_paper_persistence_failures.py
 M backend/tests/test_paper_portfolio_engine.py
 M backend/tests/test_strategy_api.py
 M docs/ARCHITECTURE.md
 M docs/MODULE_MAP.md
 M docs/USER_GUIDE.md
 M frontend/README.md
 M frontend/scripts/generate-types.mjs
 M frontend/src/help/catalog.json
 M frontend/src/layouts/Dashboard.tsx
 M frontend/src/pages/Backtest.tsx
?? backend/scripts/export_validation_report.py
?? backend/src/api/validation.py
?? backend/src/application/historical_dataset.py
?? backend/src/application/historical_dataset_codec.py
?? backend/src/application/validation_costs.py
?? backend/src/application/validation_example.py
?? backend/src/application/validation_metrics.py
?? backend/src/application/validation_regimes.py
?? backend/src/application/validation_report.py
?? backend/src/application/validation_report_codec.py
?? backend/src/application/validation_telemetry.py
?? backend/src/application/walk_forward.py
?? backend/src/application/walk_forward_evaluator.py
?? backend/src/domain/historical_dataset.py
?? backend/src/domain/validation_costs.py
?? backend/src/domain/validation_regimes.py
?? backend/src/domain/validation_report.py
?? backend/src/domain/walk_forward.py
?? backend/tests/export_validation_example.py
?? backend/tests/test_historical_dataset.py
?? backend/tests/test_historical_dataset_codec.py
?? backend/tests/test_historical_dataset_replay.py
?? backend/tests/test_validation_api.py
?? backend/tests/test_validation_costs.py
?? backend/tests/test_validation_regimes.py
?? backend/tests/test_validation_release.py
?? backend/tests/test_validation_report.py
?? backend/tests/test_walk_forward_evaluator.py
?? backend/tests/test_walk_forward_protocol.py
?? backend/tests/validation_release_fixture.py
?? docs/PHASE_10_REPORT.md
?? frontend/src/api/validation.schema.json
?? frontend/src/api/validation.ts
?? frontend/src/hooks/useValidation.ts
?? frontend/src/pages/Validation.tsx
?? frontend/src/test/fixtures/validation.json
?? frontend/src/test/fixtures/validation.medium.json
?? frontend/src/test/validation.test.tsx
?? frontend/src/types/validation.generated.ts
```

The `??` entries above are the separately inventoried **39 untracked source,
test, generated-contract and documentation files**; the preceding ` M` entries
are **21 tracked modifications**. All untracked files are below 1 MiB; the largest
is the 185105-byte medium frontend projection. No accidental runtime artifact
appears in this inventory.

`git diff --stat` (tracked changes only; excludes all 39 untracked new files):

```text
 .github/workflows/backend-ci.yml                 |   6 +-
 CODEX_TASK.md                                    |   5 +
 README.md                                        |  20 +++-
 backend/README.md                                |  33 ++++++-
 backend/scripts/export_dashboard_contract.py     |   6 +-
 backend/src/application/explanations.py          |  10 ++
 backend/src/main.py                              |   6 ++
 backend/tests/test_decision_api.py               |   4 +-
 backend/tests/test_feature_api.py                |   4 +-
 backend/tests/test_live_paper_api.py             |   5 +-
 backend/tests/test_paper_persistence_failures.py |   3 +-
 backend/tests/test_paper_portfolio_engine.py     |   3 +-
 backend/tests/test_strategy_api.py               |   4 +-
 docs/ARCHITECTURE.md                             | 115 +++++++++++++++++++++++
 docs/MODULE_MAP.md                               |  42 +++++++++
 docs/USER_GUIDE.md                               |  34 ++++++-
 frontend/README.md                               |  25 ++++-
 frontend/scripts/generate-types.mjs              |  20 +++-
 frontend/src/help/catalog.json                   |  50 ++++++++++
 frontend/src/layouts/Dashboard.tsx               |   4 +-
 frontend/src/pages/Backtest.tsx                  |   5 +-
 21 files changed, 380 insertions(+), 24 deletions(-)
```

`git diff --check` passed. No unresolved blocker remains.

PHASE 10 READY FOR REVIEW
