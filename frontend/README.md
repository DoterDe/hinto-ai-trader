# Hinto paper dashboard

React/TypeScript frontend through Phase 9. All seven pages display public market
research or virtual simulation state. No credentials, financial controls or
execution requests exist. No original Hinto components/styles were copied.

## Run and verify

Tested Node **22.12.0**, npm **11.0.0**. Direct dependencies and the lockfile are
pinned. jsdom 28.1.0 is used because later releases require a newer Node minor.

```bash
npm ci
npm test
npm run build
npm run dev
```

`build` runs `tsc --noEmit` before Vite. There is no separate typecheck or lint
script. The installed formatter can be checked with
`node node_modules/prettier/bin/prettier.cjs --check "src/**/*.{ts,tsx,css}" "README.md"`.

In Windows PowerShell use `npm.cmd` if execution policy blocks `npm.ps1`; no policy
change is necessary. The dev server binds to `127.0.0.1:5173`. Start the backend
on `127.0.0.1:8000`. `/api/*` is proxied to the backend without that prefix.
The production bundle in `dist/` requires a same-origin `/api` reverse proxy;
`npm run preview` previews static assets and does not deploy the application.

## Structure and contracts

- `src/api/`: generated serialization schema and GET-only, five-second-timeout client.
- `src/types/`: generated TypeScript models plus small application aliases.
- `src/hooks/`: sequential polling, cancellation, capped failure retry.
- `src/layouts/`: shell, navigation, visible mode/health and local view preference.
- `src/pages/`: Overview, Market, Signals, Portfolio, Backtest, System and Guide.
- `src/components/`: cards, tables, badges, gap-preserving SVG curves and feature detail.
- `src/help/`: generated shared glossary/module catalog and centralized typed reason wording.
- `src/utils/`: finite number display, UTC time and current public-price selection.
- `src/test/`: offline component/client tests and backend-produced fixtures.

Regenerate after backend contract/help changes, from `backend/`:

```bash
python scripts/export_dashboard_contract.py
python tests/export_dashboard_examples.py
```

Then `npm run types` from `frontend/`. `--check` on either Python script verifies
committed output without writing. The schema declares serialized defaults as
required and accepts Decimal scientific notation actually emitted by Pydantic,
including `0E+33`; it still rejects NaN and Infinity. Decimal values remain strings
until display. JavaScript formatting is not an accounting or decision engine.

## Availability and explainability

`GET /paper/snapshot?limit=100` supplies one coherent read-only projection. The
poller waits two seconds after successful reads; failures retry after 4/8/15
seconds, capped at 15. There is no overlapping polling, and unmount aborts pending
requests. A failed response removes prior values from the current display.
Visibility recovery requests fresh telemetry. No API response body is shown as an
internal error trace.

Current feed observations and captured decision evidence have separate timestamps
and generations. Captured indicators never substitute a newer live-cache value.
The paper view deliberately omits optional book context. Unknown valuations stay
Unknown, and charts break at missing points. The portfolio's valuation timestamp
qualifies known values; "known" does not claim a fresh account balance.

Simple/Advanced persists only `hinto.view` in localStorage. It never sends a
mutation request. Help uses a keyboard-operable disclosure (Enter/Space to toggle,
Escape to close). Guide/module information works even when the backend is offline.
Technical configuration values are read-only. Disabled future cards are not
operational modules. Backtest is educational; no report run or fake performance
data is included in the application bundle. Synthetic fixtures are test-only.

Four exported runtime fixtures cover disabled, running, incomplete open exposure
and a real BLOCKED decision under a stricter contributor policy. Component tests
also cover missing symbols/optional stream metadata, loading and all three
decision outcomes. No browser visual inspection was performed for Phase 9;
no screenshot or manual visual verification is claimed.

## Local persistence and recovery

Overview and System read `status.persistence`; they never open SQLite or ask the
backend to save/reset a session. Simple mode explains new/recovered/durable,
disabled, degraded, corrupt and incompatible states. A pending save does not
claim durability for the newer state. Advanced adds session/checkpoint IDs,
checksum, schema, compatibility, memory boundary and retained counts. Paths and
credentials are absent. `PAPER / VIRTUAL ONLY` stays visible.

Guide and the shared catalog explain Persistence, Checkpoint, Recovery, Durable
boundary, Session ID, Crash consistency and Configuration compatibility. Unknown
valuation after downtime remains unknown; recovery is not an account reconnect.
The generated contract and four existing runtime fixtures include the additive
metadata. Persistence component tests cover all nine states, pending commits,
Simple/Advanced, missing valuation and absence of financial controls.

See [USER_GUIDE](../docs/USER_GUIDE.md), [MODULE_MAP](../docs/MODULE_MAP.md), and
[PHASE_9_REPORT](../docs/PHASE_9_REPORT.md) for semantics, evidence and limitations.
