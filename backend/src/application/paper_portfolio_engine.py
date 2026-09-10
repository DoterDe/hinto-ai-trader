"""Explicit offline shared-capital replay through the existing analytical pipeline."""

from collections.abc import Iterable, Sequence
from contextlib import aclosing

from src.application.backtest_identity import BACKTEST_ENGINE_VERSION, DatasetIdentity, settings_identity
from src.application.backtest_settings import BacktestSettings
from src.application.decision_identity import DECISION_ENGINE_VERSION, policy_identity
from src.application.decision_settings import DecisionSettings
from src.application.feature_settings import FeatureSettings
from src.application.historical_replay import HistoricalReplay
from src.application.paper_portfolio_identity import PORTFOLIO_ENGINE_VERSION
from src.application.paper_portfolio_ledger import PaperPortfolioLedger
from src.application.paper_portfolio_metrics import portfolio_metrics
from src.application.paper_portfolio_settings import PaperPortfolioSettings
from src.application.strategy_engine import ENGINE_VERSION as STRATEGY_ENGINE_VERSION
from src.application.strategy_settings import StrategySettings
from src.domain.market_data import KlineEvent
from src.domain.paper_portfolio import PaperPortfolioReport, PaperPortfolioRunMetadata
from src.strategies.identity import identity

LIMITATIONS = (
    "virtual_capital_only_not_exchange_account_or_execution",
    "bar_end_availability_and_next_open_assume_zero_latency",
    "fixed_notional_gross_exposure_does_not_net_long_and_short",
    "capacity_gates_apply_to_new_reservations_not_forced_liquidation",
    "passive_equity_losses_can_raise_existing_exposure_fractions_above_limits",
    "unknown_holding_marks_permanently_block_new_reservations",
    "dataset_end_open_exposure_has_no_final_mark_or_fabricated_exit",
    "drawdown_and_exposure_maxima_are_known_close_snapshot_observations",
    "closed_pnl_totals_exclude_separately_reported_outstanding_entry_costs",
    "no_liquidity_impact_latency_funding_margin_liquidation_or_taxes",
    "finite_run_audit_and_curve_memory_scales_with_input",
    "historical_simulation_does_not_predict_future_returns",
)


class PaperPortfolioEngine:
    def __init__(self, *, symbols: Sequence[str], interval: str = "1m",
                 settings: PaperPortfolioSettings | None = None, backtest_settings: BacktestSettings | None = None,
                 feature_settings: FeatureSettings | None = None, strategy_settings: StrategySettings | None = None,
                 decision_settings: DecisionSettings | None = None) -> None:
        self.settings = PaperPortfolioSettings.model_validate(settings) if settings is not None else PaperPortfolioSettings()
        self.backtest_settings = BacktestSettings.model_validate(backtest_settings) if backtest_settings is not None else BacktestSettings()
        self.replay = HistoricalReplay(symbols=symbols, interval=interval, feature_settings=feature_settings,
                                       strategy_settings=strategy_settings, decision_settings=decision_settings)

    async def run(self, bars: Iterable[KlineEvent]) -> PaperPortfolioReport:
        ledger = PaperPortfolioLedger(symbols=self.replay.symbols, interval=self.replay.interval,
                                      settings=self.settings, backtest_settings=self.backtest_settings)
        dataset = DatasetIdentity()
        group_bars, group_observations = [], []
        current = started = ended = None
        # One next-time frame can delimit a group; only the completed group's
        # immutable bars/decisions enter the ledger. No provider/future read there.
        async with aclosing(self.replay.frames(bars)) as frames:
            async for frame in frames:
                if current is not None and current != frame.bar.event_time:
                    ledger.advance(group_bars, group_observations)
                    group_bars.clear()
                    group_observations.clear()
                dataset.add(frame.bar)
                if started is None:
                    started = frame.bar.open_time
                current = ended = frame.bar.event_time
                group_bars.append(frame.bar)
                group_observations.append(frame.observation)
            if group_bars:
                ledger.advance(group_bars, group_observations)
        final_state = ledger.finish()
        feature_id = identity("feature_settings", self.replay.feature_settings)
        strategy_id = identity("settings", self.replay.strategy_settings)
        decision_id = policy_identity(self.replay.decision_settings, self.replay.symbols)
        backtest_id = settings_identity(self.backtest_settings)
        portfolio_id = ledger.policy.policy_id
        run_id = identity("paper_portfolio_run", (PORTFOLIO_ENGINE_VERSION, BACKTEST_ENGINE_VERSION,
            STRATEGY_ENGINE_VERSION, DECISION_ENGINE_VERSION, dataset.value, feature_id, strategy_id,
            decision_id, backtest_id, portfolio_id, self.replay.symbols, self.replay.interval))
        metadata = PaperPortfolioRunMetadata(run_id=run_id, dataset_id=dataset.value,
            engine_version=PORTFOLIO_ENGINE_VERSION, started_from=started, ended_at=ended,
            symbols=self.replay.symbols, interval=self.replay.interval, input_count=dataset.count,
            duplicate_decision_reads=ledger.duplicate_reads, feature_settings_id=feature_id,
            strategy_settings_id=strategy_id, decision_policy_id=decision_id, backtest_settings_id=backtest_id,
            portfolio_policy_id=portfolio_id,
            status="INCOMPLETE" if ledger.expiries or any(item.status == 'INCOMPLETE' for item in ledger.positions) else "COMPLETE")
        decisions, reservations, expiries, positions, closes, curve = (
            ledger.decisions, ledger.reservations, ledger.expiries, ledger.positions, ledger.closes, ledger.curve)
        metrics = portfolio_metrics(initial_equity=self.settings.initial_virtual_equity, input_count=dataset.count,
            decisions=decisions, reservations=reservations, expiries=expiries, positions=positions, closes=closes,
            curve=curve, final_state=final_state, backtest_settings=self.backtest_settings, symbols=self.replay.symbols)
        return PaperPortfolioReport(metadata=metadata, decisions=decisions, reservations=reservations,
            expiries=expiries, positions=positions, closes=closes, curve=curve, final_state=final_state,
            metrics=metrics, limitations=LIMITATIONS)
