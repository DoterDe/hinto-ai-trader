# Current Codex Task — Phase 9: Durable Paper Persistence, Recovery & Soak Validation

## Working branch

`phase-9-paper-persistence-recovery`

## Accepted baseline

Phase 8 is merged and green on `main` at:

`8e19f8e6238cdd8791c25b6155f2f9bb29f5ac32`

Accepted GitHub CI baseline:

- backend: **2262 passed, 2 existing warnings**;
- frontend: **60 passed**;
- TypeScript/build: passed;
- dashboard schema/examples: reproducible;
- `pip check`: clean.

Before editing, confirm this branch is exactly based on that main commit and rerun the full baseline.

---

# Objective

Turn the Phase 8 in-memory live paper workstation into a durable research application whose **virtual paper session can survive a backend restart without inventing market evidence, re-executing old decisions, or silently changing portfolio state**.

Phase 9 has four deliverables:

1. **Local durable paper persistence** — persist only paper/runtime artifacts and configuration provenance to a local SQLite database.
2. **Strict deterministic recovery** — reconstruct the virtual paper session from the last valid durable checkpoint and continue only from new admissible public observations.
3. **Crash/restart/soak validation** — prove repeated restarts, long streams and injected failures do not duplicate decisions, reservations, entries or closes and do not leak memory/tasks.
4. **Explainable persistence UI** — expose storage/recovery health in the existing dashboard so a beginner can see whether the current virtual state is new, recovered, durable, degraded or incompatible.

This phase remains **PAPER / VIRTUAL ONLY**.

---

# Hard scope and safety boundaries

Phase 9 must NOT add or use:

- Binance private/account endpoints;
- API keys, API secrets, signing keys or account credentials;
- real exchange balances or positions;
- real order submission;
- Binance testnet order submission;
- deposits, withdrawals or transfers;
- P2P transaction automation or settlement;
- payment automation;
- leverage/margin execution;
- real liquidation logic;
- `TradeIntent` creation from the live-paper runtime;
- `ApprovedTradeIntent` creation from the live-paper runtime;
- Phase 1 `RiskEngine` invocation from the live-paper runtime;
- `PaperExecutionGateway` invocation from the live-paper runtime;
- AI/OpenAI API;
- ML/RL;
- automatic strategy optimization;
- return-based parameter fitting;
- cloud databases;
- Redis;
- remote storage services;
- historical REST backfill;
- fabricated gap candles;
- frontend financial action controls.

Persistence is for **virtual paper state only**. It must never become a credential store or exchange-account store.

---

# Baseline and inspection first

Before editing:

1. confirm branch: `phase-9-paper-persistence-recovery`;
2. confirm clean/expected working tree;
3. confirm merge-base with `main` is `8e19f8e6238cdd8791c25b6155f2f9bb29f5ac32`;
4. run the full backend suite and confirm 2262 baseline tests;
5. run frontend tests/build and confirm 60 tests plus successful production build;
6. read completely:
   - `AGENTS.md`;
   - `docs/ARCHITECTURE.md`;
   - `docs/PHASE_7_REPORT.md`;
   - `docs/PHASE_8_REPORT.md`;
   - `docs/MODULE_MAP.md`;
   - `docs/USER_GUIDE.md`;
7. inspect Phase 8 `LiveBarBatcher`, `LivePaperAnalysis`, `LivePaperCoordinator`, `LivePaperPortfolio`, telemetry, API and lifespan;
8. inspect Phase 7 paper portfolio types/math/policy;
9. inspect current CI and frontend contract export flow.

Do not redesign existing strategy, decision or portfolio formulas.

---

# Target architecture

```text
Public Binance market data
        ↓
MarketDataHub
        ↓
LiveBarBatcher / closed-bar admission
        ↓
FeatureEngine → StrategyEngine → DecisionEngine
        ↓
LivePaperCoordinator
        ↓
LivePaperPortfolio
        ↓
DurablePaperStore (SQLite, local only)
        ↓
atomic checkpoint + append-only audit metadata
        ↓
restart
        ↓
RecoveryManager
        ↓
validated recovered virtual session
        ↓
new admissible finalized public bars only
        ↓
Telemetry API → React dashboard
```

Persistence must sit **after deterministic paper state transitions**, not before analytical admission.

Do not let database reads become strategy evidence.

---

# Batch 1 — Persistence contracts and SQLite store

Implement a dedicated persistence layer, preferably under modules such as:

```text
backend/src/application/paper_persistence_settings.py
backend/src/application/paper_persistence_identity.py
backend/src/application/paper_persistence_codec.py
backend/src/infrastructure/sqlite_paper_store.py
backend/src/domain/paper_persistence.py
```

Exact names may differ if repository conventions suggest better names.

## Storage technology

Use local SQLite through Python's standard library `sqlite3` unless a compelling repository-level reason requires otherwise.

Do not add a heavy ORM.

Preferred database characteristics:

- local file only;
- explicit schema version;
- foreign keys enabled;
- WAL mode where supported;
- synchronous durability explicitly configured and documented;
- transactions for all checkpoint writes;
- parameterized SQL only;
- bounded retention/compaction;
- no network access.

Recommended env prefix:

`PAPER_PERSISTENCE_`

Suggested settings:

```text
PAPER_PERSISTENCE_ENABLED=true
PAPER_PERSISTENCE_PATH=./data/paper_runtime.sqlite3
PAPER_PERSISTENCE_CHECKPOINT_HISTORY=32
PAPER_PERSISTENCE_EVENT_HISTORY=5000
PAPER_PERSISTENCE_BUSY_TIMEOUT_MS=5000
PAPER_PERSISTENCE_RESUME_POLICY=strict
```

Validate paths/settings strictly.

Tests must use temporary directories/databases.

Never write tests into the real project database path.

## What may be persisted

Persist only what is required to restore the virtual runtime faithfully, for example:

- session ID;
- schema version;
- engine/runtime version;
- durable boundary/watermark;
- configuration identities;
- initial virtual equity;
- realized virtual PnL/equity state;
- peak virtual equity;
- active virtual reservations;
- active/incomplete virtual positions;
- position evidence required for deterministic close identity;
- known marks if they were authoritative at the durable boundary;
- recently completed virtual closes within bounded retention;
- dedupe identities needed to prevent reprocessing;
- bounded curve/audit state required by the UI;
- diagnostic counters where needed;
- checksum/integrity metadata.

Do NOT persist:

- API keys;
- secrets;
- exchange account IDs;
- real balances;
- real orders;
- private payloads;
- raw unbounded WebSocket history;
- reconstructed order book;
- future observations;
- unfinished analytical state that cannot be proven authoritative.

## Serialization

Create a deterministic versioned persistence codec.

Requirements:

- canonical JSON or equivalent stable encoding;
- explicit schema version;
- UTC aware timestamps only;
- Decimal values preserved exactly as strings/validated Decimals;
- no NaN/Infinity;
- deterministic ordering;
- content checksum (for example SHA-256) over canonical payload;
- corrupted payload/checksum fails closed;
- unknown future schema version fails closed;
- no pickle.

Do not deserialize arbitrary Python objects.

## Database schema

Keep schema intentionally small.

A reasonable design is:

```text
paper_sessions
paper_checkpoints
paper_audit_events
schema_metadata
```

or a similarly compact equivalent.

Do not create dozens of mutable domain tables unless needed.

A checkpoint may contain one canonical validated payload representing the authoritative paper state at one finalized boundary.

## Atomicity

The authoritative checkpoint write must be atomic.

A crash must result in either:

- the complete previous checkpoint; or
- the complete new checkpoint;

never a half-written paper state.

Use a transaction and test rollback/failure injection.

### Batch 1 acceptance

Add focused tests for:

- new empty database;
- schema creation;
- reopen existing database;
- deterministic encode/decode;
- Decimal/timestamp fidelity;
- checksum verification;
- corruption rejection;
- unknown schema rejection;
- strict settings/path validation;
- transaction rollback;
- bounded checkpoint retention;
- bounded audit retention;
- no credentials/private fields in schema/payload.

Run targeted tests and report exact count.

---

# Batch 2 — Paper state checkpointing

Integrate persistence with `LivePaperCoordinator` / `LivePaperPortfolio` without changing analytical formulas.

## Commit point

Persist a checkpoint only after a deterministic portfolio transition has completed successfully for a finalized boundary.

Preferred sequence:

```text
admit finalized close group
→ analytical evaluation
→ portfolio transition
→ authoritative in-memory state established
→ durable transaction/checkpoint
→ publish durable telemetry status
```

If checkpoint persistence fails:

- do not pretend the state is durable;
- enter an explicit degraded/error persistence condition;
- fail closed for further paper transitions if continuing would make recovery ambiguous;
- never silently continue indefinitely with "saved" status false while the UI claims durability.

Choose and document the exact fail-closed behavior.

## Checkpoint contents

The checkpoint must be sufficient to restore state without replaying already accepted decisions.

Persist dedupe/watermark information so a restarted process cannot duplicate:

- a decision;
- a reservation;
- a virtual entry;
- a completed close;
- a finalized close boundary.

## Identity

Every durable paper session needs a stable session ID.

The ID must be deterministic/content-derived or securely random once at session creation and then persisted. It must not affect strategy or portfolio decisions.

Checkpoint IDs should be deterministic from session + boundary + canonical payload checksum where practical.

## Database writes and event loop

Do not perform uncontrolled long blocking database operations on the event loop.

SQLite operations are small/local, but structure the store so blocking work is bounded and explicit. If using a thread boundary, lifecycle and ordering must remain deterministic and tested.

Do not introduce concurrent writers.

One runtime process = one authoritative writer.

### Batch 2 acceptance

Test:

- checkpoint after valid boundary;
- no checkpoint for rejected/unfinished observations;
- checkpoint exactly once per authoritative transition;
- identical duplicate input creates no extra state transition;
- conflicting/late input cannot rewrite durable history;
- database failure marks persistence unhealthy/fails closed;
- no half-updated checkpoint after injected exception;
- bounded histories remain bounded in RAM and DB.

Then run Phase 8 coordinator/lifecycle/portfolio regressions.

---

# Batch 3 — Strict restart recovery

Create a recovery layer such as `PaperRecoveryManager` or equivalent.

## Recovery startup flow

Preferred flow:

```text
open store
→ validate schema
→ load latest session/checkpoint
→ verify checksum
→ verify engine/schema compatibility
→ verify configuration identities
→ restore virtual state
→ restore watermark/dedupe state
→ start public feed consumer
→ accept only observations newer than durable boundary
```

The feed must not race ahead before recovery is complete.

## Strict configuration compatibility

Default `resume_policy=strict`.

A persisted session may resume only when required identities are compatible, including at least:

- live runtime version;
- feature settings identity;
- strategy settings identity;
- decision policy identity;
- paper portfolio policy identity;
- cost/backtest settings identity;
- symbol universe;
- interval.

If incompatible:

- do not reinterpret old positions under new rules;
- do not silently create a mixed session;
- expose `RECOVERY_INCOMPATIBLE` / equivalent explicit status/reason;
- require starting a new virtual session through an explicit local maintenance action or configuration, not an automatic guess.

Do not mutate persisted history to make it compatible.

## Offline gap semantics

There is no historical downloader in Phase 9.

If the backend was offline and required bars were missed:

- do not fabricate them;
- do not fill them from the newest price;
- when continuity cannot be proven, reservations expire or positions become `INCOMPLETE` according to existing Phase 8/7 semantics;
- marked equity may remain unknown;
- dashboard must explain why.

## Duplicate-after-restart semantics

If the first public event after restart repeats the last durable finalized candle:

- identical duplicate: diagnose/ignore;
- conflicting duplicate: fail closed/diagnose;
- it must not generate another decision/reservation/entry/close.

## Recovery status model

Extend telemetry with explicit persistence/recovery state close to:

```text
DISABLED
NEW_SESSION
RECOVERING
RECOVERED
DURABLE
DEGRADED
INCOMPATIBLE
CORRUPT
ERROR
```

Do not replace existing runtime status; persistence/recovery health is a separate dimension.

### Batch 3 acceptance

Test full process-equivalent restart scenarios:

- clean stop → restart → exact state equality;
- abrupt stop after durable checkpoint → restart;
- crash before checkpoint commit → previous checkpoint restored;
- crash after checkpoint commit → new checkpoint restored;
- repeated restart cycles;
- duplicate last candle after restart;
- missed boundary during downtime;
- active position recovery;
- reservation recovery;
- incomplete position recovery;
- unknown valuation recovery;
- incompatible settings;
- corrupted latest checkpoint;
- older valid checkpoint handling policy clearly tested;
- zero double-counted PnL;
- zero duplicated close IDs.

---

# Batch 4 — Persistence telemetry and dashboard UX

Extend the existing read-only dashboard contract.

## Backend telemetry

Expose safe persistence metadata, preferably inside `/paper/snapshot` and optionally one dedicated GET endpoint.

Useful fields:

- persistence enabled;
- database health;
- session ID;
- session created_at;
- recovered flag;
- recovery status/reason;
- schema version;
- latest durable boundary;
- latest checkpoint time;
- checkpoint ID;
- retained checkpoint count;
- retained durable audit event count;
- persistence lag (`in_memory_boundary` vs `durable_boundary`);
- configuration compatibility status;
- storage path only if sanitized/relative and safe; do not leak arbitrary host details unnecessarily.

All endpoints remain read-only.

No reset/delete-session HTTP endpoint in Phase 9.

## Dashboard

Update Overview/System/Guide as needed.

The user should be able to understand:

- "New virtual session";
- "Recovered virtual session";
- "Last durable checkpoint";
- "Current state is durable";
- "Persistence degraded";
- "Recovery incompatible";
- "Virtual state cannot be trusted/recovered";
- why an old position is incomplete after downtime.

Add help terms for:

- Persistence;
- Checkpoint;
- Recovery;
- Durable boundary;
- Session ID;
- Crash consistency;
- Configuration compatibility.

Simple mode should show plain language.

Advanced mode may show IDs/checksums/schema/config identities.

Never show recovery as an exchange/account reconnect.

Always retain `PAPER / VIRTUAL ONLY`.

### Batch 4 acceptance

Frontend tests must cover:

- new session;
- recovered session;
- durable checkpoint;
- persistence disabled;
- persistence degraded;
- incompatible recovery;
- unknown valuation after downtime;
- Simple/Advanced differences;
- no financial controls.

Regenerate backend→frontend contract deterministically.

---

# Batch 5 — Soak, restart and boundedness validation

Create deterministic offline soak/restart tooling/tests.

Do not use real Binance in CI.

## Long-stream validation

Run a sufficiently large injected public stream to make retention bugs visible.

Prefer at least tens of thousands of finalized bars in a dedicated non-slow test/tool if runtime permits.

Validate:

- RAM histories stay within configured bounds;
- DB checkpoint count stays within retention limit;
- durable audit count stays within retention limit;
- SQLite file growth stabilizes within expected compaction behavior rather than growing linearly forever from obsolete checkpoints;
- no duplicated decisions/reservations/entries/closes;
- no subscriber/task growth;
- deterministic final virtual state for repeated identical scenario.

If physical SQLite file size cannot shrink automatically after deletes, document WAL/VACUUM/checkpoint behavior and validate logical boundedness plus a maintenance strategy. Do not falsely claim byte-level boundedness when SQLite free pages remain allocated.

## Restart soak

Create repeated restart cycles, e.g.:

```text
stream segment
→ checkpoint
→ shutdown
→ reopen
→ recover
→ next segment
```

Repeat many times.

Final state must equal an equivalent uninterrupted reference run wherever no bars were intentionally missed.

## Failure injection

Cover at least:

- commit failure;
- disk write exception simulation;
- corrupted checkpoint;
- locked/busy database behavior within configured timeout;
- process restart between portfolio transition and durable publication where technically injectable.

Do not depend on actual disk exhaustion.

---

# Batch 6 — CI, documentation and final acceptance

Update CI so persistence/recovery tests run offline on Linux.

Do not require external services.

Update:

- `README.md`;
- `backend/README.md`;
- `frontend/README.md` if UI changed;
- `docs/ARCHITECTURE.md`;
- `docs/MODULE_MAP.md`;
- `docs/USER_GUIDE.md`;
- create `docs/PHASE_9_REPORT.md`;
- update this `CODEX_TASK.md` with completion status.

## Module map additions

Explain for a beginner:

- DurablePaperStore;
- checkpoint codec;
- RecoveryManager;
- persistence telemetry;
- session lifecycle.

For each explain:

- input;
- responsibility;
- output;
- failure behavior;
- what it cannot do.

## User guide

Explain:

- what is actually saved;
- what is not saved;
- how restart recovery works;
- why missing bars while offline cannot be reconstructed;
- why an incompatible config does not resume old positions;
- how to recognize a recovered session;
- what "durable" means;
- that all balances/PnL remain virtual.

---

# Explicit maintenance boundary

Phase 9 may need a way to intentionally start a fresh virtual session when persisted state is incompatible/corrupt.

Prefer an explicit local CLI/script, for example:

```text
python scripts/paper_session.py status
python scripts/paper_session.py archive-and-new
```

Exact commands are optional and should follow repository style.

If implemented:

- local filesystem only;
- clear confirmation flag for destructive/archive action;
- never touches exchange data;
- never deletes silently;
- preserve/rename/archive old database or session where practical;
- tests use temporary paths.

Do NOT add a browser button or HTTP financial mutation endpoint for this in Phase 9.

---

# Critical invariants

Phase 9 is not complete unless tests prove these:

1. A durable restart never duplicates a previously committed paper decision.
2. A durable restart never duplicates a reservation, virtual entry or close.
3. Realized PnL after restart is byte/value equivalent to uninterrupted execution for the same complete observation sequence.
4. Recovery never reads future market evidence.
5. A missed observation during downtime remains missing.
6. No cached current price repairs a historical missing bar.
7. A corrupt/incompatible checkpoint fails closed.
8. Checkpoint writes are atomic.
9. Persistence cannot contain credentials/private-account fields.
10. GET telemetry cannot mutate persistence or paper state.
11. Existing Phase 8 anti-lookahead and generation/freshness gates remain intact.
12. Runtime and database histories are logically bounded.
13. Shutdown leaves zero Phase 9 worker tasks/DB writer tasks/subscribers/timers.

---

# Testing discipline

After each batch:

1. run focused Phase 9 tests;
2. run the affected Phase 8 tests;
3. report exact test counts;
4. fix root causes, not assertions;
5. do not weaken prior tests.

Before final completion run:

Backend:

```bash
python -m pytest
python -m pip check
```

Frontend:

```bash
npm ci
npm run types
npm test
npm run build
```

Also run:

- persistence schema/codec reproducibility;
- clean restart equivalence;
- crash-before/after-commit checks;
- repeated restart soak;
- long-stream boundedness;
- SQLite logical retention check;
- OpenAPI audit;
- GET-only Phase 8/9 telemetry audit;
- disabled-persistence lifecycle;
- enabled-persistence lifecycle;
- corrupt/incompatible recovery paths;
- zero orphan tasks/subscribers;
- backend→frontend contract reproducibility;
- prohibited-integration source audit;
- `git diff --check`;
- `git status`;
- `git diff --stat`.

---

# Prohibited-integration source audit

Final audit must confirm Phase 9 adds no functional use of:

- private Binance/account endpoints;
- API credentials/secrets;
- real balances/positions;
- order submission;
- testnet submission;
- deposits/withdrawals/transfers;
- P2P automation;
- leverage/margin execution;
- `TradeIntent` / `ApprovedTradeIntent` creation from Phase 8/9 runtime;
- `RiskEngine` execution path;
- `PaperExecutionGateway` execution path;
- AI/OpenAI APIs;
- ML/RL;
- automatic optimization;
- remote databases/cloud persistence.

Documentation may mention future architecture only.

---

# Known intentional limitations after Phase 9

Unless deliberately addressed without expanding scope, Phase 9 may still have:

- no real exchange account connection;
- no real/testnet order execution;
- no P2P execution;
- no historical gap downloader;
- no distributed/multi-process writer support;
- no cross-machine replication;
- no cloud backup;
- no exchange-accurate fills/funding/liquidation;
- no strategy optimization;
- no guarantee of profitability;
- browser visual QA may remain unavailable in Codex environment.

Do not hide these limitations.

---

# Completion report

At completion provide exact evidence for:

1. branch and baseline;
2. files created/modified;
3. persistence settings;
4. SQLite schema/version;
5. transaction/durability mode;
6. checkpoint payload/version/checksum;
7. checkpoint commit point;
8. retention/compaction behavior;
9. session identity;
10. recovery compatibility checks;
11. duplicate-after-restart behavior;
12. offline-gap behavior;
13. active/reservation/incomplete recovery;
14. corruption behavior;
15. failure-injection results;
16. restart equivalence results;
17. long-stream/soak results;
18. DB logical boundedness;
19. lifecycle cleanup;
20. telemetry/API changes;
21. frontend changes/help terms;
22. backend→frontend contract checks;
23. OpenAPI/read-only audit;
24. prohibited-integration audit;
25. exact targeted test counts;
26. exact complete backend result;
27. exact frontend result;
28. build result;
29. `pip check`;
30. warnings;
31. known limitations;
32. `git status`;
33. `git diff --stat`.

End with exactly one of:

`PHASE 9 READY FOR REVIEW`

or

`PHASE 9 NOT READY`

with exact blockers.

Do NOT commit.
Do NOT push.
Do NOT merge.
Do NOT start Phase 10.
