# Phase 9 — Durable Paper Persistence, Recovery & Soak Validation

## Scope and baseline

Branch: `phase-9-paper-persistence-recovery`. Phase 8 base/merge-base:
`8e19f8e6238cdd8791c25b6155f2f9bb29f5ac32`; the branch initially added only Phase 9
preparation commits `512bcbe` and `bd40a2d`. Existing local Phase 9 work was preserved
through interrupted sessions. No commit, push, merge or Phase 10 work was performed.

Before implementation, the repository virtual environment passed **2262 backend
tests, 2 existing warnings in 79.27s**. Frontend baseline: **60 passed in 16.59s**;
TypeScript/Vite passed (131 modules; 487.61 kB JavaScript, 135.37 kB gzip). `pip check`
was clean, generated contracts were reproducible, and `npm ci` reported 133 packages
added, 134 audited and zero vulnerabilities.

Validated environment: Windows, Python 3.11.9, bundled SQLite 3.45.1, Node 22.12.0,
npm 11.0.0. No backend/frontend dependency or lockfile change was required.

Phase 9 persists **virtual paper state only**. Production strategy, decision,
cost, sizing, arbitration, fixed-horizon and accounting formulas are unchanged.
Phase 1 risk/execution services remain separate and are not made durable here.

## Architecture and settings

```text
Public finalized observations -> existing closed-bar admission and analytics
  -> LivePaperCoordinator -> LivePaperPortfolio transition
  -> canonical PaperCheckpoint -> one SQLite worker -> atomic COMMIT
  -> published durable boundary -> read-only telemetry/dashboard

Restart -> open/validate store -> verify latest checkpoint and compatibility
  -> restore accounting/history/admission/dedupe -> register consumer
  -> start public source -> accept new admissible observations
```

`PaperPersistence` manages storage and recovery. `DurablePaperStore` owns one local
stdlib SQLite connection on one dedicated worker thread. The recovery adapter is
isolated in `paper_recovery_state.py`; it restores bounded state into the existing
engines without introducing alternate analytical formulas. There is no ORM,
network storage, concurrent writer or event-loop database I/O. Encoding remains
synchronous and scales with the configured bounded payload.

| Environment variable | Default | Constraint |
| --- | --- | --- |
| `PAPER_PERSISTENCE_ENABLED` | `true` | Strict boolean |
| `PAPER_PERSISTENCE_PATH` | `./data/paper_runtime.sqlite3` | Local `.db`, `.sqlite`, `.sqlite3` file |
| `PAPER_PERSISTENCE_CHECKPOINT_HISTORY` | `32` | 1–256 |
| `PAPER_PERSISTENCE_EVENT_HISTORY` | `5000` | 1–100000 |
| `PAPER_PERSISTENCE_BUSY_TIMEOUT_MS` | `5000` | 1–60000 |
| `PAPER_PERSISTENCE_RESUME_POLICY` | `strict` | No fallback mode |

Paths reject URI/UNC, traversal, tilde and directory forms. Relative paths resolve
from the process working directory: starting from `backend/` uses
`backend/data/paper_runtime.sqlite3`. Keep the directory/path stable across restarts.
Settings validation, app import and OpenAPI generation open no database. A disabled
paper runtime opens no store. Tests opt in only with temporary database paths.

## Schema, payload, identities and durability

Database schema version **1**, checkpoint payload version **1**. Four tables:

| Table | Purpose |
| --- | --- |
| `schema_metadata` | Explicit supported schema version |
| `paper_sessions` | Session identity, latest checkpoint pointer and continuity fence |
| `paper_checkpoints` | Sequenced complete canonical payloads and integrity metadata |
| `paper_audit_events` | Append-on-write metadata with bounded retention |

Foreign keys are enabled; WAL, `synchronous=FULL`, a 1000-page WAL auto-checkpoint and
the configured busy timeout are explicit. DML uses bound parameters. The single
in-process owner guard and expected-latest-checkpoint comparison prevent accidental
stale writes; they are not a distributed or multi-process coordination protocol.

Each checkpoint contains:

- stable session ID/creation time, checkpoint time and durable candle boundary;
- engine versions, symbol universe, interval and all relevant settings identities;
- authoritative reservations, active/incomplete positions, known net-PnL marks,
  bounded holding-bar fingerprints, realized totals, peak equity, lifetime counts
  and ordered decision dedupe evidence;
- admission watermark and bounded sealed fingerprints, excluding unapplied future
  returned groups;
- bounded per-symbol closed-candle history, reset provenance, analytical clock and
  logical generation, plus last closed analytical observations with their generations;
- bounded diagnostic events, captures, latest per-symbol analyses, recent closes
  and curve points, counters and last problem.

Partial pending candle groups, input queues, process timers, unfinished analysis,
raw WebSocket history, future observations and full depth books are excluded.
Derived exposure, marked equity and drawdown are recomputed using existing math.
The recovery cache belongs to the isolated closed-bar analytical pipeline: it is
never published as a new current price into the ordinary live MarketDataHub.

Canonical JSON sorts object keys while preserving semantically ordered arrays,
including dedupe eviction order. Decimals are exact strings; timestamps are aware
UTC with microseconds. Floats must be finite; null remains explicit. SHA-256 covers
the canonical payload. Decode validates models, bounds, chronology, versions and
canonical re-encoding; malformed JSON, duplicate/unknown fields and non-finite
values are rejected. There is no pickle or arbitrary-object deserialization.

A UUID is generated once for a new session and persisted. It does not influence
analytics. Checkpoint identity derives from session, boundary and payload checksum.
Existing decision/reservation/entry/close identities are retained. Bounded ordered
holding-bar fingerprints reconstruct the existing dataset digest, preserving close
IDs without serializing Python hash objects. Tests compare IDs across restarts.

Commit order is strict:

```text
completed admitted portfolio transition
-> validate/encode full checkpoint
-> BEGIN IMMEDIATE
-> insert checkpoint + update session head + append audit + apply retention
-> COMMIT
-> publish durable checkpoint/boundary
```

Before COMMIT, the previous checkpoint is authoritative; after COMMIT, the complete
new checkpoint is authoritative, including when acknowledgement fails. Failed
writes roll back, mark persistence degraded/error and halt further paper transitions.
Telemetry distinguishes memory and durable boundaries and never calls unsaved state
durable. A recovery failure leaves read-only diagnostics available without starting
the public producer or paper consumer. No automatic older-checkpoint fallback exists.

## Recovery, continuity and shutdown

Strict recovery checks runtime, feature, strategy, decision, portfolio and backtest
versions; symbols/interval; runtime settings including Hub freshness; feature and
strategy settings; decision and portfolio policies; and cost/backtest settings.
Incompatible identities never reinterpret positions under new rules or silently
start a replacement session. Schema, checksum, canonical payload and accounting
invariants are validated before state restoration.

Recovery restores the admission watermark, sealed fingerprints, ordered dedupe,
bounded history and reset/generation provenance before subscribing or starting the
source. Old decisions are not re-evaluated. Identical last-candle duplicates are
ignored/diagnosed. Conflicting duplicates cannot rewrite durable history and fail
closed through continuity invalidation. Evicted old fingerprints do not remove
the monotonic admission watermark's protection against reprocessing old boundaries.

Active positions and reservations survive an intentional clean shutdown unchanged
at the last committed boundary. Already incomplete exposure stays incomplete. A
missed entry bar expires the reservation; a missing holding bar invalidates its
valuation and leaves explicit INCOMPLETE exposure. Newest prices never repair
missing historical evidence. There is no historical downloader or fabricated gap.

A separate checksummed continuity fence records observed loss after a checkpoint
in session metadata and bounded audit. It refers to the checkpoint and records
watermark/generation/reason/time. It does **not** rewrite that checkpoint or advance
the committed candle boundary. Recovery reapplies the fence so restart cannot
revive exposure already known to be incomplete. Storage failure while saving a
fence also halts; the last committed checkpoint/fence pair remains authoritative.

Two source-generation races were fixed and tested during final validation:

1. A returned batch list keeps its captured source token across each persistence
   await; connection rotation cannot relabel old grouped bars as a new generation.
2. Recovery bootstrap ends as soon as any new group starts collecting, including
   a partial multi-symbol group. A later rotation discards that group and cannot
   combine bars admitted under different generations.

Generation, queue-loss, publication/receipt age and stale-data checks remain active.
Internal analytical failures durably fence lost continuity when storage is healthy.
Intentional shutdown is distinct: the consumer stops before the source emits
STOPPED. Outstanding SQLite work settles before connection/thread teardown; nested
analytical subscriptions, timers and worker tasks are released. Explicitly disabled
persistence retains the prior Phase 8 memory-only shutdown behavior.

## Retention and maintenance

Checkpoint and audit retention are applied transactionally on writes. Lowering a
storage history limit takes effect on the next successful write. Runtime retention
covers candle history, decisions/events/dedupe, recent closes, curve points, sealed
fingerprints, pending group capacity and per-position evidence (holding horizon).
Latest analysis is bounded by symbol count; reservations/positions by the symbol
universe and existing policy. No unbounded production history was added.

**Logical SQLite history is bounded; allocated database/WAL file size is not
guaranteed to shrink automatically without SQLite maintenance such as
checkpointing/VACUUM.** Deleted pages may be reused. WAL checkpointing is distinct
from a paper checkpoint, and VACUUM is not automatic. The storage stress samples page/file
allocation after explicit offline WAL truncation, not after VACUUM.

No maintenance CLI or HTTP/browser reset was added. To explicitly start a fresh
virtual session, stop the backend, preserve the database and any remaining sidecars
together, then configure a different unused local path. Do not edit checksums,
remove the latest checkpoint or discard a live WAL to force recovery. Concurrent
external database writers/checkpointers and multiple backend workers are unsupported.

## API, dashboard and CI

The existing `/paper/status` and `/paper/snapshot` responses gain required
`persistence` metadata: enablement, storage health, state/reason, stable session
identity/creation time, recovered flag, schema, checkpoint identity/checksum/time,
durable and current memory boundaries, unsaved changes, compatibility and retained
counts. Host database paths are not exposed. GET projection performs no SQL I/O,
analytical evaluation, time advancement, reservation, entry or close.

There are still **19 application paths, all GET-only**; no mutation/reset path or
execution contract is added. The other Phase 8 telemetry paths remain
`/paper/portfolio`, `/paper/positions`, `/paper/decisions`, `/paper/events`,
`/paper/curve`, `/explain/modules` and `/explain/terms`.

Overview and System show a reusable persistence panel. Simple mode explains storage
and recovery plainly; Advanced includes checkpoint/session metadata and both
boundaries. Guide/help explains durable state, recovery and unknown valuation.
The status vocabulary is DISABLED, NEW_SESSION, RECOVERING, RECOVERED, DURABLE,
DEGRADED, INCOMPATIBLE, CORRUPT and ERROR. Runtime/feed health stays separate from
storage health. PAPER / VIRTUAL ONLY remains visible; no financial action controls.

The shared glossary gains seven persistence terms and the module catalog gains
three entries (13 total). Backend-exported schema, examples, help and TypeScript
contracts were updated together. Test fixtures remain offline examples, never
fallback product prices. CI explicitly disables public feed/runtime/default storage;
the complete backend suite enables individual temporary databases in relevant
tests. No CI test writes the project database or connects to Binance.

Normal CI includes the 120-bar-per-run restart test and 300-transaction storage
test through `python -m pytest`. The extended 2,000-bar/20,000-commit workload is an
explicit local release-validation command, intentionally excluded from every-push
CI to keep runtime reasonable. Neither mode relies on persistent runner disk or
shared SQLite state. The CI changes were inspected locally; a new hosted GitHub
run was not triggered because no push was performed.

## Validation evidence

All Python commands use the repository virtual environment from `backend/`.
PowerShell uses `.\.venv\Scripts\python.exe` and `npm.cmd`.

| Stage / targeted selection | Exact result |
| --- | --- |
| Contracts/settings/canonical codec | 63 passed in 0.63s |
| Contracts + initial SQLite store | 80 passed in 6.67s |
| Initial checkpoint integration | 6 passed in 10.75s |
| Affected storage + Phase 8 | 122 passed in 27.81s |
| Initial recovery + checkpoint | 23 passed in 138.35s |
| Initial persistence/Phase 8 lifecycle | 14 passed in 3.57s |
| API + contract | 95 passed in 5.14s |
| Initial frontend persistence coverage | 77 passed in 21.84s |
| Original source race + affected tests | 35 passed in 30.38s |
| Exact resumed source-token race regression | 1 passed in 1.42s |
| Checkpoint/recovery/coordinator/lifecycle | 56 passed in 166.68s |
| Corrected new failures + race + soak | 8 passed in 32.67s |
| Actual SQL failures/subprocess crash + lifecycle | 27 passed in 20.39s |
| Internal-error fence + affected Phase 8/lifecycle/failures | 20 passed in 11.63s |
| Required config/version identities + equal-time permutation | 21 passed in 34.02s |
| Complete affected Phase 7–9 regression selection | 775 passed, 2 warnings in 342.58s (5:42) |

Selections overlap; their counts are not additive. Initial frontend TypeScript/Vite
also passed (132 modules; 497.16 kB JavaScript, 137.75 kB gzip).

The resumed race test was explicitly run before broader work:
`python -m pytest tests/test_paper_checkpointing.py::test_rotation_between_returned_groups_cannot_relabel_old_bars_as_new_generation -q`.

The 775-test selection covers `test_paper_persistence*`, `test_paper_checkpointing`,
`test_paper_recovery`, `test_sqlite_paper_store`, `test_live_*`,
`test_paper_portfolio_*`, market Hub, feature engine/history/subscription/edge cases
and strategy/decision APIs. Contracts, deterministic codec, SQL atomicity,
corruption/version/config rejection, duplicate/conflict/gap behavior, cancellation,
source rotation, permutation invariance and both lifecycle modes are included.

Failure tests exercise exceptions before/during transactions, actual SQL INSERT,
UPDATE and COMMIT failures, locked/busy timeout, writer exceptions, and real child
process termination with `os._exit(17)` before and immediately after COMMIT. Reopen
observes the whole previous/new checkpoint as appropriate. Checksummed continuity
fences and healthy/failed fence writes are independently tested. These are not
physical power-loss or actual disk-exhaustion experiments.

Two new tests initially failed during development: the partial-group recovery
regression exposed the real bootstrap race (1 failed, 4 passed in 2.22s); the first
soak wrapper required a completed position too early at bar 60 (1 failed, 1 passed
in 25.55s). The race was fixed. The harness now checks every restart prefix and
all decision/reservation/entry/close identities and requires completed outcomes at
the final horizon. Tests were not weakened to mask runtime failures; the corrected
sets and broader regressions passed as recorded above.

### Extended offline soak

Command: `python tests/soak_paper_persistence.py --bars 2000 --restart-every 100 --storage-checkpoints 20000 --output ../docs/PHASE_9_SOAK_RESULTS.json`.

The harness runs 2,000 analytical bars continuously and the same 2,000 bars in
100-bar restart segments, comparing exact authoritative state at every prefix and
the final state. It checks ordered decision hashes, unique reservation/entry/close
IDs, accounting, histories, reset provenance and admission/dedupe state. It then
performs 20,000 smaller valid atomic storage checkpoints to stress retention.
These are distinct workloads, not 20,000 full analytical bars. The ordinary pytest
soak uses 120 bars per run, 12 segments and 300 storage transactions.

Extended soak completed successfully (exit 0). Exact machine-readable output is
[PHASE_9_SOAK_RESULTS.json](PHASE_9_SOAK_RESULTS.json):

| Measurement | Result |
| --- | --- |
| Full analytical stream | 2 runs × 2,000 bars |
| Restart segments / exact prefix comparisons | 20 / 20 |
| Final authoritative equality | true |
| Unique reservations / entries / closes | 1 / 1 / 1 |
| Orphan workers, tasks or subscribers | 0 |
| Storage transactions | 20,000 |
| Retained checkpoints / audit rows | 3 / 5 |
| Database after 100, 10,001 and 20,000 writes + WAL truncation | 53,248 bytes; 13 pages; 1 free page at each sample |

Maximum observed RAM counts: candles 50, decisions 5, events 5, ordered dedupe 5,
curve 7, recent closes 1 (limit 3), sealed groups/fingerprints 3, holding evidence 4
(limit 5), pending groups 0 (limit 3). These are observations, not claims that every
configured capacity was reached. This fixture produces one completed position;
broader trade/cohort/arbitration behavior is covered separately by Phase 7–9 tests.
No threshold was tuned to manufacture additional trades.

Authoritative SHA-256:
`1c0e724a113c4077bbd2aae2b9a8ce6cf451b07081aa92f21ffe55d0677b1c2e`.
Ordered decision sequence SHA-256:
`bc88a82b00ea16aa442546c0adcd10dc85c0de0b14d3574125ec6aee99ddd16b`.

### Final acceptance commands

- `python -m pytest`: **2410 collected; 2410 passed, 0 failed, 0 skipped,
  2 warnings in 1879.75s (0:31:19)**; process exit **0**. All 2,262 baseline tests
  plus 148 Phase 9 tests passed. The interrupted terminal's final result could not
  be recovered and no pytest process remained, so this complete run was repeated
  with output saved to a temporary log. The successful extended soak and frontend
  validation were not repeated.
- `python -m pip check`: **No broken requirements found.**
- `python scripts/export_dashboard_contract.py --check`: **Dashboard schema and explanation catalog: verified**.
- `python tests/export_dashboard_examples.py --check`: **Four deterministic runtime dashboard fixtures verified**.
- Application import/OpenAPI validation: **19 GET-only paths**, persistence schema
  present, no execution contracts, finite JSON serialization, no database created.
- `npm ci`: **133 packages added, 134 audited in 1m; 0 vulnerabilities**.
- `npm run types`: passed; generated file SHA-256 unchanged:
  `180A8077C1D05D1DD1E09C8C0DF1B239D78B6BDEBCCEC4185AF3C1617050B735`.
- `npm test`: **3 test files passed; 77 tests passed in 24.30s** (17 added to baseline).
- `npm run build`: TypeScript passed; Vite passed in **293ms**, **132 modules**.
  HTML 0.63 kB (gzip 0.38), CSS 12.98 kB (gzip 3.86), JavaScript **497.29 kB
  (gzip 137.77)**. No build warnings/errors.

Final explicit offline lifecycle/OpenAPI/source-audit selection: **8 passed in
7.73s**. Command:

```powershell
python -m pytest tests/test_paper_persistence_lifecycle.py tests/test_paper_persistence_failures.py::test_phase9_openapi_is_get_only_and_contains_no_execution_contract tests/test_paper_persistence_failures.py::test_phase9_source_has_no_prohibited_integrations tests/test_live_paper_contract_export.py::test_phase8_runtime_has_no_execution_or_private_network_dependency -q
```

This directly exercises enabled/disabled temporary storage, recovery-before-feed,
corrupt/schema-incompatible startup, preservation of clean-stop open exposure,
durable analytical-failure invalidation and zero orphan workers/tasks/subscribers.
The source audits check Phase 8 and Phase 9 imports/calls for prohibited execution,
private/network, remote storage, AI/ML and optimizer dependencies. A separate scan
of all 52 changed/new files found no credential patterns or database/bytecode
artifacts; no project runtime database was created. Review of the production diff
confirmed no credentials, private endpoints or financial action path was introduced.

The final repository-path audit inspected 188 tracked and 21 untracked paths.
None contain drive prefixes, absolute Windows paths or malformed `D:` components.
The absolute paths previously shown by Codex were display formatting only. All
seven new production modules and all 21 intended new files are present. Runtime
databases/sidecars, temporary recovery data, caches/bytecode, frontend build output
and local `.env` are not tracked. Ignore checks for these artifacts pass;
`.env.example` adds only the six public virtual-persistence settings.

There are **148 new backend tests** across eight files: contracts 63, SQLite 22,
checkpointing 7, recovery 18, lifecycle 5, API 11, soak 2 and failures/audits 20.
The original 2,262 tests remain in the complete regression selection.

## Warnings, limits and deferred work

The two existing backend warnings concern Starlette's deprecated httpx TestClient
integration and AnyIO's deprecated BlockingPortal alias. Dependencies were not
changed to suppress them. Git may print LF-to-CRLF notices for this Windows
checkout; these are distinct from whitespace-check failures.

Local SQLite 3.45.1 predates the fix described in the official
[WAL-reset advisory](https://www.sqlite.org/wal.html#walreset) (fixed in 3.51.3 and
listed backports). Its trigger requires concurrent multi-connection writes or
checkpoints. This runtime has one connection/worker and does not exercise that
trigger. A supported Python environment update bundling patched SQLite remains
an operational recommendation; concurrent external database use is unsupported.

Remaining limits and risks:

- FULL durability depends on operating system, filesystem and device sync behavior.
  Checksums detect accidental corruption, not hostile tampering or deletion.
- Full bounded-payload encoding and storage latency increase with configured symbol
  and history limits. Slow storage can cause feed queue/freshness rejection; the
  runtime fails closed rather than inventing continuity.
- The final full run took substantially longer than the earlier focused runs.
  Its extra wall time was not profiled; these checks do not establish a production
  storage-latency or live-feed throughput guarantee.
- Soak coverage is deterministic/offline with explicit replay time. It does not
  establish real Binance network throughput, hardware power-loss resistance or
  performance at all maximum settings. No browser visual QA was performed.
- No migrations, automatic repair, older-checkpoint fallback, maintenance CLI,
  automatic VACUUM, multi-process writer, replication or cloud backup was added.
- Offline bars remain missing; incomplete exposure can keep valuation unknown.
  There is no historical downloader, full order book or exchange-accurate fill,
  funding, liquidation or profitability guarantee.
- No private/account API, credential store, real/testnet execution, transfers/P2P,
  leverage, TradeIntent/ApprovedTradeIntent creation, RiskEngine/PaperExecutionGateway
  invocation, AI/ML/RL or automatic optimization was added to this runtime.

## Changed-file inventory and final repository checks

Created **21 files** (7 production Python modules, 8 backend test modules, 2 backend
test helpers/tools, 2 frontend files and 2 report artifacts):

```text
backend/src/application/paper_persistence.py
backend/src/application/paper_persistence_codec.py
backend/src/application/paper_persistence_settings.py
backend/src/application/paper_position_evidence.py
backend/src/application/paper_recovery_state.py
backend/src/domain/paper_persistence.py
backend/src/infrastructure/sqlite_paper_store.py
backend/tests/persistence_fixtures.py
backend/tests/soak_paper_persistence.py
backend/tests/test_paper_checkpointing.py
backend/tests/test_paper_persistence_api.py
backend/tests/test_paper_persistence_contracts.py
backend/tests/test_paper_persistence_failures.py
backend/tests/test_paper_persistence_lifecycle.py
backend/tests/test_paper_persistence_soak.py
backend/tests/test_paper_recovery.py
backend/tests/test_sqlite_paper_store.py
docs/PHASE_9_REPORT.md
docs/PHASE_9_SOAK_RESULTS.json
frontend/src/components/Persistence.tsx
frontend/src/test/persistence.test.tsx
```

Modified **31 tracked files**:

```text
.env.example
.github/workflows/backend-ci.yml
.gitignore
CODEX_TASK.md
README.md
backend/README.md
backend/src/application/backtest_identity.py
backend/src/application/explanations.py
backend/src/application/live_paper_coordinator.py
backend/src/application/live_paper_portfolio.py
backend/src/application/live_paper_telemetry.py
backend/src/main.py
backend/tests/conftest.py
backend/tests/live_paper_fixtures.py
backend/tests/test_live_paper_api.py
docs/ARCHITECTURE.md
docs/MODULE_MAP.md
docs/USER_GUIDE.md
frontend/README.md
frontend/src/api/dashboard.schema.json
frontend/src/components/Common.tsx
frontend/src/help/catalog.json
frontend/src/layouts/Dashboard.tsx
frontend/src/pages/Guide.tsx
frontend/src/pages/Overview.tsx
frontend/src/pages/System.tsx
frontend/src/test/fixtures/blocked.json
frontend/src/test/fixtures/disabled.json
frontend/src/test/fixtures/incomplete.json
frontend/src/test/fixtures/running.json
frontend/src/types/generated.ts
```

`git diff --check` passed (exit 0). Git printed only the documented Windows
LF-to-CRLF notices. The 21 new files also passed a separate whitespace/newline
check. All 31 tracked modifications are unstaged; all 21 new files are untracked.
No commit, push, merge, branch switch or history rewrite was performed.

`git status`:

```text
On branch phase-9-paper-persistence-recovery
Your branch is up to date with 'origin/phase-9-paper-persistence-recovery'.

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
	modified:   .env.example
	modified:   .github/workflows/backend-ci.yml
	modified:   .gitignore
	modified:   CODEX_TASK.md
	modified:   README.md
	modified:   backend/README.md
	modified:   backend/src/application/backtest_identity.py
	modified:   backend/src/application/explanations.py
	modified:   backend/src/application/live_paper_coordinator.py
	modified:   backend/src/application/live_paper_portfolio.py
	modified:   backend/src/application/live_paper_telemetry.py
	modified:   backend/src/main.py
	modified:   backend/tests/conftest.py
	modified:   backend/tests/live_paper_fixtures.py
	modified:   backend/tests/test_live_paper_api.py
	modified:   docs/ARCHITECTURE.md
	modified:   docs/MODULE_MAP.md
	modified:   docs/USER_GUIDE.md
	modified:   frontend/README.md
	modified:   frontend/src/api/dashboard.schema.json
	modified:   frontend/src/components/Common.tsx
	modified:   frontend/src/help/catalog.json
	modified:   frontend/src/layouts/Dashboard.tsx
	modified:   frontend/src/pages/Guide.tsx
	modified:   frontend/src/pages/Overview.tsx
	modified:   frontend/src/pages/System.tsx
	modified:   frontend/src/test/fixtures/blocked.json
	modified:   frontend/src/test/fixtures/disabled.json
	modified:   frontend/src/test/fixtures/incomplete.json
	modified:   frontend/src/test/fixtures/running.json
	modified:   frontend/src/types/generated.ts

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	backend/src/application/paper_persistence.py
	backend/src/application/paper_persistence_codec.py
	backend/src/application/paper_persistence_settings.py
	backend/src/application/paper_position_evidence.py
	backend/src/application/paper_recovery_state.py
	backend/src/domain/paper_persistence.py
	backend/src/infrastructure/sqlite_paper_store.py
	backend/tests/persistence_fixtures.py
	backend/tests/soak_paper_persistence.py
	backend/tests/test_paper_checkpointing.py
	backend/tests/test_paper_persistence_api.py
	backend/tests/test_paper_persistence_contracts.py
	backend/tests/test_paper_persistence_failures.py
	backend/tests/test_paper_persistence_lifecycle.py
	backend/tests/test_paper_persistence_soak.py
	backend/tests/test_paper_recovery.py
	backend/tests/test_sqlite_paper_store.py
	docs/PHASE_9_REPORT.md
	docs/PHASE_9_SOAK_RESULTS.json
	frontend/src/components/Persistence.tsx
	frontend/src/test/persistence.test.tsx

no changes added to commit (use "git add" and/or "git commit -a")
```

`git diff --stat`:

```text
 .env.example                                      |   8 +
 .github/workflows/backend-ci.yml                  |   7 +-
 .gitignore                                        |   6 +
 CODEX_TASK.md                                     |   9 +
 README.md                                         |  23 ++-
 backend/README.md                                 | 129 +++++++++++++-
 backend/src/application/backtest_identity.py      |   9 +-
 backend/src/application/explanations.py           |  14 +-
 backend/src/application/live_paper_coordinator.py | 109 ++++++++++--
 backend/src/application/live_paper_portfolio.py   |   5 +-
 backend/src/application/live_paper_telemetry.py   |   3 +
 backend/src/main.py                               |  26 ++-
 backend/tests/conftest.py                         |   3 +-
 backend/tests/live_paper_fixtures.py              |   2 +
 backend/tests/test_live_paper_api.py              |   3 +-
 docs/ARCHITECTURE.md                              |  67 ++++++-
 docs/MODULE_MAP.md                                |  32 +++-
 docs/USER_GUIDE.md                                |  58 +++++-
 frontend/README.md                                |  24 ++-
 frontend/src/api/dashboard.schema.json            | 204 +++++++++++++++++++++-
 frontend/src/components/Common.tsx                |   4 +-
 frontend/src/help/catalog.json                    |  74 +++++++-
 frontend/src/layouts/Dashboard.tsx                |   4 +-
 frontend/src/pages/Guide.tsx                      |   4 +
 frontend/src/pages/Overview.tsx                   |   4 +-
 frontend/src/pages/System.tsx                     |   6 +-
 frontend/src/test/fixtures/blocked.json           |  19 ++
 frontend/src/test/fixtures/disabled.json          |  19 ++
 frontend/src/test/fixtures/incomplete.json        |  19 ++
 frontend/src/test/fixtures/running.json           |  19 ++
 frontend/src/types/generated.ts                   |  58 +++++-
 31 files changed, 894 insertions(+), 77 deletions(-)
```

The stat covers tracked changes only: **31 files, +894 / -77**. It excludes the
**21 created files** listed above. No files were staged to inflate that summary.
All required local acceptance checks passed. Hosted CI and browser visual QA were
not run; the operating limits and deferred work above remain explicit.

PHASE 9 READY FOR REVIEW
