# Phase 9 — Persistence & Recovery Contract

This document is the compact architectural contract for Phase 9. `CODEX_TASK.md` remains the authoritative implementation checklist.

## Purpose

Phase 9 makes the Phase 8 **virtual paper runtime** durable across backend restarts. It does not add exchange execution or private-account connectivity.

## Core invariant

A restart must never make the system behave as if a previously committed finalized bar, decision, reservation, virtual entry, or virtual close happened twice.

For the same complete observation sequence, an interrupted run with valid durable recovery must converge to the same virtual accounting state as an uninterrupted run.

## Durable boundary

The store records an explicit `durable_boundary`: the latest finalized close boundary whose complete paper-state transition has been atomically committed.

The durable boundary is not merely the newest market timestamp. It means:

1. the finalized bar group was admitted;
2. analytical evaluation completed;
3. portfolio transition completed;
4. the resulting paper state was serialized and validated;
5. the SQLite transaction committed successfully.

Only after step 5 may telemetry call that boundary durable.

## Storage

Use one local SQLite database, one authoritative writer and a small versioned schema.

Preferred logical records:

- schema metadata;
- paper session metadata;
- atomic checkpoints;
- bounded durable audit events.

The canonical checkpoint payload should contain the minimum state required to restore the paper session without replaying already committed decisions.

Do not use pickle or arbitrary object deserialization.

## Checkpoint integrity

Every checkpoint must have:

- schema version;
- session ID;
- durable boundary;
- configuration identities;
- canonical payload;
- deterministic checksum;
- committed timestamp.

Checksum failure, invalid JSON, unsupported version or incompatible configuration must fail closed.

## Recovery

Startup order:

```text
open SQLite
→ validate schema
→ load latest committed checkpoint
→ verify checksum/version/config
→ restore virtual paper state
→ restore watermark/dedupe state
→ register live consumer
→ start accepting new public observations
```

The public feed must not outrun recovery.

## Offline gaps

Phase 9 does not add historical REST backfill.

If the process was offline for required candle boundaries, those bars remain missing. Existing reservation-expiry / incomplete-position semantics apply. A newer live price must never be substituted for a missed historical bar.

## Compatibility

Resume is strict by default. Required identities include:

- engine/runtime version;
- symbols and interval;
- Feature settings;
- Strategy settings;
- Decision policy;
- PaperPortfolio policy;
- simulation cost settings.

An old session must not be interpreted under materially different rules.

## Persistence failure

If the in-memory portfolio advances but its authoritative checkpoint cannot be committed, persistence health becomes degraded/error and further state advancement must fail closed until consistency is re-established. The dashboard must not label the state durable.

## Retention

RAM and SQLite logical histories must stay bounded. Deleting old SQLite rows does not necessarily shrink the physical file; tests/documentation must distinguish logical retention from file-page reclamation/WAL checkpoint/VACUUM behavior.

## UI language

The dashboard should clearly distinguish:

- New virtual session
- Recovered virtual session
- Last durable checkpoint
- Durable / not durable
- Recovery incompatible
- Corrupt persistence state
- Unknown valuation after downtime

All values remain virtual simulation values.

## Explicitly not in Phase 9

No private Binance APIs, credentials, account balances, order placement, testnet orders, transfers, P2P execution, leverage/margin execution, AI trading, ML/RL, optimizer, cloud database, distributed writer or historical gap downloader.
