# Phase 9 user guide

This workstation observes public market information, explains deterministic
analytical results, and simulates a portfolio with virtual capital. Every screen
is **PAPER / VIRTUAL ONLY**. Nothing on the dashboard can move money or access
your exchange account. Start both services using the [quick start](../README.md).

## Read the status before the numbers

Backend connectivity and public-feed health describe different things. A connected
backend can have a stale market feed. A green connection alone does not mean that
analytical evidence or portfolio valuation is current. Check the observation and
valuation timestamps; all displayed times are UTC.

| Runtime state | Meaning |
| --- | --- |
| DISABLED | The paper consumer is disabled, or no public/injected source is enabled. |
| STARTING | Runtime objects exist and startup has not completed. |
| WARMING_UP | Fresh candles are arriving, but required analytical history is not ready. |
| RUNNING | Required candle feeds and captured strategy readiness are healthy, and portfolio valuation is known. This does not promise a candidate or profit. |
| DEGRADED | A feed, continuity, or valuation problem needs attention. Read the displayed reasons and events. |
| STOPPING / STOPPED | Cleanup is in progress or finished. Unfinished virtual exposure is not forcibly closed. |
| ERROR | An internal runtime failure stopped processing. A safe diagnostic is shown. |

Default indicators need up to 50 consecutive closed candles: approximately 50
minutes with one-minute bars. There is no history download on startup. Reconnects,
queue loss, or broken continuity require fresh warm-up. Missing input can also make
the runtime DEGRADED during warm-up; it is not necessarily an internal ERROR.

## The seven screens

**Overview** gives the latest public price, captured pipeline readiness, virtual
equity, drawdown, exposure, reservations, positions, recent decisions and events.
The equity chart uses observed virtual portfolio snapshots. Read warnings before
interpreting a curve. Loading or backend failure never supplies demonstration
prices in place of live telemetry.

**Market** lists the configured public symbols. Select a symbol for bid/ask,
mark/index and funding context, stream freshness, and captured indicator values.
Current public prices and the last closed-bar analysis have separate timestamps.
An older captured EMA is not presented as a calculation from the newest public
price. Advanced view shows sample counts, source ages and connection generations.
A generation identifies one connection lifetime, not a quality score.

**Signals & Decisions** traces a captured observation through measurements,
strategy assessments, the composite result, DecisionEngine and portfolio policy.
Select **Explain** on a row. Read both the analytical reason and virtual portfolio
gate: an ELIGIBLE analytical result can still be rejected for virtual capacity.
Advanced view adds evidence contributions, observed thresholds and provenance IDs.
Historical decisions remain as captured when the current feed later becomes stale.

**Paper Portfolio** shows virtual initial, realized, marked and peak equity;
realized/unrealized PnL; assumed costs; gross and symbol exposure; reservations;
open/incomplete positions; and recent closes. Charts show equity, drawdown and
gross exposure fraction. An incomplete position keeps its unresolved exposure.
Its last historical mark is evidence from that time, not a valid current valuation.

**Backtest & Validation** reads an explicitly configured offline validation report
and explains existing signal and shared-capital validation services. No configured
report means an honest unavailable state; no performance is invented. The browser
cannot run a backtest, upload data or optimize settings. Historical validation is
not a prediction of future profit.

The Validation panel loads when this page is opened. Simple mode shows chronological
test windows, observed/missing coverage, eligible/blocked/no-action counts,
completed/incomplete outcomes, causal regime groups and fixed cost assumptions.
Context warms indicators and is excluded from test metrics. Use the scope selector
to inspect individual windows; overlapping tests deliberately have no pooled
aggregate. Missing evidence stays missing; a horizon outside its window is incomplete.
Groups with fewer than 30 completed outcomes are marked small, including empty
groups. UNKNOWN regime evidence is not interpreted as a neutral market.

Advanced adds report/dataset/protocol/split IDs, checksum, engine/settings identities,
warm-up/boundaries, exact fixed regime thresholds and fee/slippage assumptions.
Confidence is evidence/agreement quality, not probability of profit. Historical
hit rate is a sample statistic, not future win probability. Cost scenarios are
assumptions, not forecasts. Regime labels are descriptive research categories, not
execution instructions. The normalized signal curve is not portfolio equity.

To display a report, prepare it offline from `backend/` using
`python scripts/export_validation_report.py --output FILE` (synthetic example), or
also pass `--dataset CANONICAL_DATASET.json` for validated local public data.
Set server-only `VALIDATION_REPORT_PATH` to that report before starting the backend.
No configured path is sent to the browser. Reports load once at startup; replace
the file and restart to read a new export. A missing/corrupt/unsupported file has an
explicit unavailable/invalid status. `/validation/status` and `/validation/latest`
are GET-only. Failed browser refreshes clear the displayed report and retry.

**System / Settings** displays configured symbols, engine settings, costs, limits
and runtime health. Advanced view adds configuration identities and technical
fields. These are read-only. Future exchange-account, real-execution and P2P
analytics cards are disabled information; they are not connection buttons.

**Guide / How It Works** provides a module diagram, explanations and searchable
glossary. Module links navigate to the relevant page. Guide and basic System
information remain available without a backend connection.

## Understand the measurements

| Term | How to read it |
| --- | --- |
| Market data | Observed public trades, candles, best quotes and mark/funding context. It contains no account data. |
| Features | Measurements of supplied observations; they are not instructions to trade. |
| EMA | A smoothed price measure. Defaults are 9, 21 and 50 closed candles. |
| RSI | A 0–100 momentum measure using Wilder smoothing. An extreme value does not guarantee a reversal. |
| ATR | Typical true price range in price units; normalized ATR relates it to price. |
| ROC / returns | Changes relative to earlier closes; ROC is percent, simple returns are fractions. |
| Volatility | Variation in recent log returns, not a direction prediction. |
| VWAP / relative volume | Rolling quote/base volume ratio, and latest volume relative to its earlier baseline. |
| Taker-buy ratio / volume delta proxy | Descriptions of reported candle volume. They do not reconstruct market-wide order flow. |
| Spread / midpoint | Best ask minus bid, and their average. A quote is not a guaranteed fill. |
| Basis / funding | Public mark-versus-index context and a published funding rate. The simulation does not charge funding. |
| Strategy score | Signed evidence from one deterministic strategy, bounded from -100 to +100. LONG/SHORT describe analytical direction. |
| Composite Score | A weighted combination of ready strategy scores. Opposing evidence offsets; a neutral ready strategy can dilute it. |
| Confidence | Evidence quality/agreement, **not probability of profit**. A value of 0.72 does not mean a 72% chance of winning. |
| Agreement | Directional consistency of supplied evidence on a 0–1 scale. It is not independent market confirmation. |
| ELIGIBLE | The deterministic analytical gates passed. It is neither guaranteed profit nor an exchange order. |
| BLOCKED | Validation, freshness or a decision-policy gate failed; read the reasons. |
| NO_ACTION | No actionable analytical candidate exists for that valid source, including neutral or insufficiently ready evidence. |

The closed-bar paper analysis deliberately has no optional book/trade/funding
context. Its optional-context confidence penalty is preserved. The Market screen
can independently show current public context; it must not be read as evidence
that was used in an older decision. Raw depth deltas are not a full order book.

## Understand virtual accounting

| Term | Meaning |
| --- | --- |
| Reservation | **Virtual portfolio capacity, not an exchange order.** It fixes notional before the next exact bar is known. |
| Position | An observed simulated entry with a fixed holding horizon. No real quantity or leverage is selected. |
| Realized equity | Initial virtual capital plus net PnL from completed simulated positions. |
| Marked equity | Realized equity plus known open-position net PnL. **Simulated value, not a Binance balance.** |
| Peak equity | Highest known marked value observed so far, including initial equity. |
| Exposure | Fixed open plus reserved virtual notionals. LONG and SHORT add; they do not cancel. |
| Drawdown | `(peak - marked equity) / peak`. For example, 90,000 against a 100,000 peak is 10%. |
| PnL | **Simulated virtual profit or loss.** Realized PnL is from completed positions; unrealized PnL is a known open mark. |
| Fees / slippage | **Assumptions**: default 5 bps fees and 2 bps adverse slippage per side. One basis point is 0.01%. |

Defaults are 100,000 virtual initial units, 10% target notional per reservation,
40% maximum gross exposure, 15% maximum symbol exposure, four open-plus-reserved
positions and a 20% drawdown gate. One position per symbol, no partial allocation,
pyramiding or reversal. Confidence never changes position size.

A decision at closed bar t reserves capacity. Entry uses open(t+1) only when that
next finalized bar later arrives. Default exit is close(t+5). Entry is not the
source bar's close. Open PnL subtracts entry costs; completed PnL includes both
sides. No actual exchange fill, intrabar stop or liquidation is implied.

At or above the drawdown limit, new reservations block; existing positions can
finish their horizon when required bars exist. A missing entry expires capacity.
A missing holding bar makes valuation unknown, and later prices do not repair
the missing path. Shutdown does not invent an exit. With persistence enabled,
restart restores the last committed virtual session as explained below.

## What is saved, and what recovery means

Local persistence is on by default. It saves committed virtual reservations,
positions, PnL/peak, known marks, bounded recent history and the closed-candle/
dedupe evidence needed to continue without counting an old decision twice. It
does not save an exchange account, credentials, real funds, unfinished candle
groups, raw unbounded messages or future prices.

Overview and System show a separate **Virtual session & recovery** card:

| Persistence state | Meaning |
| --- | --- |
| DISABLED | State is memory-only and will not resume after this process exits. |
| NEW_SESSION | There was no prior checkpoint at the configured local path. The first complete transition has not yet been saved. |
| RECOVERING | Saved data and configuration are being checked before public observations can be consumed. |
| RECOVERED | The previous committed virtual session was restored. New public prices are still required. |
| DURABLE | The indicated checkpoint committed. If newer unsaved state is shown, only the earlier boundary is durable. |
| DEGRADED / ERROR | A persistence operation failed or storage is unavailable. Further paper transitions stop. |
| INCOMPATIBLE | Current symbols, interval, versions or fixed settings differ from the saved session. Old positions are not reinterpreted. |
| CORRUPT | Saved state failed integrity or structural checks. It cannot be presented as recovered. |

The **durable boundary** is the latest finalized candle boundary saved completely.
It is not proof that today's public feed is fresh. **Crash consistency** means a
transaction leaves either the complete previous checkpoint or the complete new
one. The **session ID** survives recovery and has no connection to an exchange
account. Advanced shows IDs, checksum, schema, memory boundary and compatibility;
Simple explains the state in plain language.

A clean stop preserves committed open exposure. If the next required bar was
missed while offline, an entry reservation expires or a holding position becomes
INCOMPLETE; valuation can become Unknown. The newest price cannot repair the
missing path. A saved continuity-loss marker preserves an already-known conflict
or loss without pretending another candle was processed.

Corrupt/incompatible recovery never silently creates a replacement session and
never falls back to older accounting. To intentionally start fresh, stop the
backend, preserve the old database and any sidecars, and explicitly choose a new
unused local `PAPER_PERSISTENCE_PATH`. There is no browser reset button or mutation
endpoint. Keep the process working directory/path stable between normal restarts.
Use one backend worker and no concurrent external database writer.

Recent saved lists have retention limits. **Logical history is bounded; physical
database size is not guaranteed to shrink automatically.** SQLite can reuse freed
pages. Maintenance and dependency-version notes are in the
[backend guide](../backend/README.md#retention-maintenance-and-limitations).

## Unknown values, history and controls

**Unknown** means required information is absent, invalid or cannot be represented
safely. It does not mean zero. A known zero remains zero. Null valuation breaks a
chart line; the dashboard does not bridge it with fabricated values. Recent lists
and charts are bounded windows, not a lifetime audit. Realized PnL totals can
therefore include earlier closes no longer visible in the recent-close table.

**Simple** view emphasizes plain explanations. **Advanced** reveals technical
evidence, IDs and settings. The choice is stored locally in the browser and sends
no backend mutation. Use Tab to reach controls and help; Enter or Space opens help,
Escape closes it. A skip link reaches the main content. No credential form or
financial control exists.

See the [module map](MODULE_MAP.md) for the internal path and the
[Phase 9 report](PHASE_9_REPORT.md) for exact tests and operational limitations.
No browser visual QA was performed for Phase 9. Component and keyboard tests do
not replace a future human visual/accessibility review.
