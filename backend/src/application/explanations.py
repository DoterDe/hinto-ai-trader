"""Plain-language static help, shared by the read-only dashboard and guide."""

from typing import Annotated, Literal
from pydantic import Field
from src.domain.paper_portfolio import PortfolioModel


class ExplanationTerm(PortfolioModel):
    key: Annotated[str, Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')]
    label: Annotated[str, Field(min_length=1, max_length=100)]
    explanation: Annotated[str, Field(min_length=1, max_length=1000)]


class ModuleExplanation(PortfolioModel):
    key: str
    name: str
    purpose: str
    inputs: str
    outputs: str
    limitations: str
    source_path: str
    page: str
    can_move_money: Literal[False] = False


_TERMS = (
    ('walk_forward', 'Walk-forward validation', 'Replay fixed rules over chronological test windows. Earlier context warms indicators; no parameters are fitted to later results.'),
    ('context_window', 'Context window', 'Past bars used only to warm analytical state. Context decisions and outcomes are excluded from test metrics.'),
    ('out_of_sample', 'Out-of-sample test', 'A later chronological evaluation window separated from its past context. Fixed rules are evaluated, not trained or selected.'),
    ('causal_regime', 'Causal regime', 'A descriptive trend or volatility label using only feature evidence available at that decision boundary. UNKNOWN means required evidence was unavailable.'),
    ('cost_sensitivity', 'Cost sensitivity', 'Compare the same signals under fixed fee and adverse slippage assumptions. Decisions, horizons and raw price evidence do not change; no scenario is ranked as best.'),
    ('data_leakage', 'Data leakage', 'Using future evidence in an earlier decision or label would invalidate the comparison. Future mutation tests check that earlier evidence stays unchanged.'),
    ('dataset_identity', 'Dataset identity', 'A SHA-256 content identity for canonical finalized public bars and declared scope. Identical canonical input has the same identity; this does not certify external authenticity.'),
    ('sample_size', 'Sample size', 'Counts distinguish all decisions, eligible signals, completed outcomes and incomplete evidence. Groups with fewer than 30 completed outcomes are flagged as small samples.'),
    ('incomplete_outcome', 'Incomplete outcome', 'A next entry bar or complete holding horizon is absent or outside the test window. No exit or return is fabricated, and the signal is not counted as a win or loss.'),
    ('historical_hit_rate', 'Historical hit rate', 'Wins divided by wins plus losses among completed historical signals; flat and incomplete outcomes are excluded. The sample count is essential. This is not a future probability of profit.'),
    ('paper', 'PAPER / VIRTUAL ONLY', 'Public market information and simulated capital only. This workstation cannot place a real order or move funds.'),
    ('market_data', 'Market data', 'Public prices and observations. They describe a market, not your exchange account.'),
    ('features', 'Feature Engine', 'Turns observed market data into numerical measurements. Missing inputs stay unavailable.'),
    ('ema', 'EMA', 'An exponentially weighted moving average gives recent prices more weight. EMA relationships provide trend evidence, not a prediction.'),
    ('rsi', 'RSI', 'A bounded measure of recent price-movement strength. An extreme value does not mean the market must reverse.'),
    ('atr', 'ATR', 'Average true range measures recent movement size, including gaps. It describes volatility, not direction.'),
    ('vwap', 'VWAP', 'Volume-weighted average price over the configured candle window. Distance from it provides trend or mean-reversion context.'),
    ('volatility', 'Volatility', 'Variation in recent observed returns. Larger values mean larger historical movement, not certainty about the next move.'),
    ('spread', 'Spread', 'Best known ask minus bid. Wider spreads can imply worse immediate execution conditions; this runtime places no orders.'),
    ('basis', 'Mark/index basis', 'Difference between the public mark price and index price. It provides market context, not account profit.'),
    ('funding', 'Funding context', 'A public funding-rate observation and next funding time. Funding is not charged in this simulation.'),
    ('strategies', 'Strategy Engine', 'Independent deterministic rules evaluate the same feature snapshot and expose their evidence.'),
    ('trend_following', 'Trend following', 'Looks for corroborated trend measurements, scaled by directional efficiency and movement size.'),
    ('momentum_continuation', 'Momentum continuation', 'Combines recent momentum and candle-volume evidence. Optional missing book context reduces evidence confidence.'),
    ('mean_reversion', 'Mean reversion', 'Measures opposing evidence after a price stretch; strong trend or volatility can suppress that evidence.'),
    ('score', 'Composite score', 'A weighted signed analytical score from -100 to 100. Positive and negative values describe directional evidence, not expected returns.'),
    ('confidence', 'Evidence confidence', 'Confidence measures evidence quality, completeness and agreement. It is not probability of profit; 0.72 does not mean a 72% chance of making money.'),
    ('agreement', 'Agreement', 'How strongly strategy contributions point in the same direction. Opposing evidence lowers agreement and confidence.'),
    ('decisions', 'Decision Engine', 'Checks readiness, freshness, identity and explicit policy thresholds. It produces an inert analytical record.'),
    ('eligible', 'ELIGIBLE', 'The deterministic policy permits further paper evaluation. ELIGIBLE does not guarantee a profitable trade or approve an exchange order.'),
    ('blocked', 'BLOCKED', 'An analytical readiness, freshness, identity or policy check failed. Read the recorded reason to see which check.'),
    ('no_action', 'NO_ACTION', 'No qualifying analytical candidate is available. Warm-up or weak/mixed evidence can produce this ordinary abstention.'),
    ('reservation', 'Reservation', 'Virtual portfolio capacity reserved after a decision. It is not an exchange order. Entry requires the next exact finalized bar.'),
    ('virtual_position', 'Virtual position', 'A fixed virtual notional measured from the next bar open through the configured holding horizon. No assets are purchased or borrowed.'),
    ('marked_equity', 'Marked virtual equity', 'Realized virtual equity plus currently known unrealized net PnL. It is not an exchange balance. A missing required holding bar makes valuation Unknown.'),
    ('realized_equity', 'Realized virtual equity', 'Initial virtual capital plus net PnL from completed virtual positions. It excludes unfinished marks.'),
    ('pnl', 'PnL', 'Profit or loss in virtual simulation units. Gross PnL excludes assumed costs; net PnL includes them.'),
    ('unrealized_pnl', 'Unrealized net PnL', 'Directional movement from entry to the last known close, less entry-side costs. No exit cost is charged until the fixed horizon completes.'),
    ('exposure', 'Exposure', 'Fixed virtual notional that is open or reserved for one symbol. No exchange quantity or leverage is selected.'),
    ('gross_exposure', 'Gross exposure', 'Open plus reserved virtual notional. LONG and SHORT add without cancelling. New reservations must fit the configured marked-equity limit.'),
    ('drawdown', 'Drawdown', 'Distance below the previous known virtual equity peak: (peak - marked equity) / peak. At the limit, new reservations block; existing fixed horizons continue.'),
    ('fees', 'Simulated fees', 'A fixed cost assumption, 5 basis points per side by default. It is not a claim about current Binance fees.'),
    ('slippage', 'Simulated slippage', 'An assumed adverse price adjustment, 2 basis points per side by default. It does not model actual fills, liquidity or market impact.'),
    ('bps', 'Basis points', 'One basis point is 0.01%. A 5 bps assumption means 0.05% per side, not 5%.'),
    ('warmup', 'Warm-up', 'Indicators need enough consecutive finalized candles. Gaps or reconnects restart continuity; thresholds are not relaxed to show a result sooner.'),
    ('stale', 'Stale feed', 'Required observations are missing, disconnected, from an older connection generation, or older than their freshness limit.'),
    ('connection_generation', 'Connection generation', 'Each public reconnection starts a new observation generation. Captured decisions retain the generation admitted at their close; current feed diagnostics may describe a newer connection. Old-generation candles cannot enter new analysis.'),
    ('missing', 'Missing data', 'An absent required candle or mark stays absent. Late data cannot rewrite finalized portfolio history. Unknown is never converted to zero.'),
    ('backtest', 'Backtest', 'Offline evaluation of fixed rules on finalized historical public bars. Historical results do not predict future returns.'),
    ('paper_portfolio', 'Paper portfolio', 'A shared pool of virtual capital with deterministic capacity rules. It is not an exchange-accurate account or liquidation model.'),
    ('limits', 'Portfolio limits', 'Defaults: target 10%, gross 40%, symbol 15%, four open-plus-reserved slots, 20% drawdown. Allocation is all-or-none; confidence never scales size. Losses can raise existing exposure ratios.'),
    ('horizon', 'Fixed holding horizon', 'A decision at close t reserves entry at open t+1. H=5 means exit at close t+5 after five complete bars. Missing required bars leave an incomplete position.'),
    ('identity', 'Observation and policy IDs', 'Content hashes identify analytical evidence and fixed settings. They support reproducibility; they are not authenticated execution approvals.'),
    ('closed_view', 'Closed-bar analytical view', 'Paper decisions use finalized candles only. Real publication/receipt age and generation are checked before evaluation. Newer live-cache values and optional book context cannot enter an older decision.'),
    ('capacity', 'Virtual capacity', 'Reservations and active positions consume capacity immediately. Opposite directions do not cancel exposure or reverse existing positions.'),
    ('peak', 'Peak equity', 'Highest previously known marked virtual equity, starting with initial capital. It is the reference for drawdown.'),
    ('relative_volume', 'Relative volume', 'Current candle volume compared with its configured prior-window average. It is historical context, not a forecast.'),
    ('taker_proxy', 'Taker-volume proxy', 'Candle taker-buy volume supports a limited order-flow proxy. Raw depth deltas are not a reconstructed full order book.'),
    ('roc', 'ROC and returns', 'Rate of change and returns compare observed closes over fixed windows. Log returns are used for realized volatility.'),
    ('regime', 'Regime inputs', 'Numerical trend efficiency, EMA separation, ATR and relative volume. These are measurements, not learned market predictions.'),
    ('persistence', 'Persistence', 'Saves committed virtual paper state in a local SQLite file. It saves no exchange account, credentials, or real funds. Disabled persistence keeps state in memory only.'),
    ('checkpoint', 'Checkpoint', 'One complete saved state after a finalized paper transition. It includes reservations, positions, bounded closed-candle history and dedupe evidence. An unfinished candle group is not a checkpoint.'),
    ('recovery', 'Recovery', 'Validates and restores the last committed virtual session before consuming new public candles. Missing bars during downtime remain missing; current prices cannot repair them.'),
    ('durable_boundary', 'Durable boundary', 'The latest finalized candle boundary whose full checkpoint committed successfully. Newer in-memory changes are not yet durable. Saving continuity-loss metadata does not advance this boundary.'),
    ('session_id', 'Session ID', 'A stable identifier created once for a virtual session and preserved across recovery. It is not an exchange account identifier and does not influence decisions.'),
    ('crash_consistency', 'Crash consistency', 'A checkpoint transaction saves either the whole new state or leaves the previous state authoritative. A corrupt latest checkpoint stops recovery; silently falling back could duplicate committed accounting.'),
    ('configuration_compatibility', 'Configuration compatibility', 'Recovery requires the same symbols, interval, analytical versions and fixed settings. A mismatch stops the paper runtime instead of reinterpreting old virtual positions under new rules.'),
)
TERMS = tuple(ExplanationTerm(key=key, label=label, explanation=text) for key, label, text in _TERMS)


_MODULES = (
    ('public', 'Public Binance data', 'Observe public market prices.', 'Public WebSocket messages.', 'Normalized market events.', 'No account access; no full order-book reconstruction.', 'backend/src/infrastructure/binance/public_market_data.py', 'Market'),
    ('hub', 'MarketDataHub', 'Share latest observations and bounded subscriptions.', 'Normalized public events and connection generations.', 'Freshness, latest values and finalized-bar observations.', 'Queues can lose data; losses are diagnosed, never backfilled.', 'backend/src/application/market_data_hub.py', 'Market'),
    ('features', 'FeatureEngine', 'Measure observed market behavior.', 'Consecutive finalized candles and available public context.', 'FeatureSnapshot with indicators and readiness.', 'Warm-up and missing inputs remain explicit.', 'backend/src/application/feature_engine.py', 'Market'),
    ('strategies', 'StrategyEngine', 'Combine independent rule-based evidence.', 'FeatureSnapshot.', 'Strategy assessments, aggregate score and optional candidate.', 'Evidence confidence is not profit probability.', 'backend/src/application/strategy_engine.py', 'Signals & Decisions'),
    ('decisions', 'DecisionEngine', 'Apply analytical eligibility rules.', 'StrategySnapshot and fixed decision policy.', 'ELIGIBLE, BLOCKED or NO_ACTION with reasons.', 'No executable intent or order approval.', 'backend/src/application/decision_engine.py', 'Signals & Decisions'),
    ('coordinator', 'LivePaperCoordinator', 'Process exact finalized close groups.', 'Bounded, generation-tagged public candles.', 'Captured analysis, virtual portfolio transitions and diagnostics.', 'Late bars cannot rewrite history; no private data or execution.', 'backend/src/application/live_paper_coordinator.py', 'Overview'),
    ('policy', 'PaperPortfolioPolicy', 'Allocate limited virtual capacity deterministically.', 'Eligible decision and current virtual state.', 'RESERVED, REJECTED or IGNORED with a reason.', 'No quantity, leverage, pyramiding, reversal or profit forecast.', 'backend/src/application/paper_portfolio_policy.py', 'Paper Portfolio'),
    ('ledger', 'Virtual portfolio ledgers', 'Track fixed-horizon positions and assumed costs.', 'Reservations and subsequent exact finalized bars.', 'Virtual equity, exposure, closes and incomplete positions.', 'Phase 7 ledger retains a finite report; Phase 8 ledger keeps bounded live histories.', 'backend/src/application/live_paper_portfolio.py', 'Paper Portfolio'),
    ('codec', 'Checkpoint codec', 'Validate a deterministic virtual-state record.', 'Typed committed paper state.', 'Versioned canonical JSON and checksum.', 'Checksums detect corruption, not malicious tampering; no arbitrary Python objects.', 'backend/src/application/paper_persistence_codec.py', 'System / Settings'),
    ('store', 'DurablePaperStore', 'Save complete virtual checkpoints atomically.', 'Canonical checkpoints and continuity-loss metadata.', 'Bounded local SQLite checkpoints and audit metadata.', 'One local writer only; storage failure halts further paper transitions.', 'backend/src/infrastructure/sqlite_paper_store.py', 'System / Settings'),
    ('recovery', 'Paper recovery and session lifecycle', 'Restore a compatible virtual session before the public feed starts.', 'Latest committed checkpoint and current configuration identities.', 'Recovered ledger, closed history and admission watermark.', 'Corruption or incompatibility fails closed. Offline gaps cannot be downloaded or invented.', 'backend/src/application/paper_persistence.py', 'System / Settings'),
    ('telemetry', 'Telemetry API', 'Expose immutable current state for reading.', 'Runtime, persistence health and explanation catalog.', 'Read-only JSON endpoints.', 'GET cannot change accounting, save checkpoints, reset sessions or move money.', 'backend/src/api/live_paper.py', 'System / Settings'),
    ('dashboard', 'Explainable dashboard', 'Make each stage understandable.', 'Read-only telemetry and public market snapshots.', 'Seven pages, Simple/Advanced views and searchable help.', 'Presentation preferences never change backend rules.', 'frontend/src/App.tsx', 'Guide / How It Works'),
)
MODULES = tuple(ModuleExplanation(key=key, name=name, purpose=purpose, inputs=inputs, outputs=outputs,
    limitations=limitations, source_path=path, page=page) for key, name, purpose, inputs, outputs, limitations, path, page in _MODULES)
