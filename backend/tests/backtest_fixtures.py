"""Fixed historical observations; no clock, network or analytical shortcuts."""

from datetime import datetime, timedelta, timezone
from decimal import Context, Decimal, localcontext

from src.domain.market_data import KlineEvent

START = datetime(2020, 1, 1, tzinfo=timezone.utc)


def bar(index=0, *, symbol="BTCUSDT", opened="100", closed="101", **updates):
    start = START + timedelta(minutes=index)
    end = start + timedelta(minutes=1)
    with localcontext(Context(prec=34)):
        opening, closing = Decimal(opened), Decimal(closed)
        fields = dict(symbol=symbol, interval="1m", open_time=start, close_time=end,
            event_time=end, received_at=end, open=opening, close=closing,
            high=max(opening, closing) + Decimal("0.1"), low=min(opening, closing) - Decimal("0.1"),
            volume=Decimal(10), quote_volume=closing * 10, trade_count=index + 1, is_closed=True,
            taker_buy_volume=Decimal(8), taker_buy_quote_volume=closing * 8)
    return KlineEvent(**(fields | updates))


def wave_bars(count=80, *, symbol="BTCUSDT"):
    """A flat oscillation followed by a rise exercises a regime transition.

    Ten-bar efficiency responds before fourteen-bar Wilder RSI fully catches up.
    This is a synthetic contract fixture, not a fitted historical return series.
    """
    previous = Decimal(100)
    for index in range(count):
        current = previous + (Decimal("2.4") if index >= 60 or index % 2 == 0 else Decimal("-2.4"))
        yield bar(index, symbol=symbol, opened=str(previous), closed=str(current))
        previous = current


def historical_decision(event, *, direction="LONG", outcome="ELIGIBLE", identity=None):
    from src.domain.backtesting import HistoricalDecision
    from src.domain.decisions import DecisionRecord
    key = identity or f"decision_{event.symbol}_{event.trade_count}"
    candidate = outcome != "NO_ACTION"
    decision = DecisionRecord(decision_id=key, symbol=event.symbol, generated_at=event.close_time,
        source_strategy_timestamp=event.close_time, source_feature_timestamp=event.close_time,
        strategy_snapshot_id="snapshot_" + key, observation_id="observation_" + key,
        strategy_settings_id="strategy_settings_test", strategy_engine_version="strategy-engine-v1",
        candidate_id="candidate_" + key if candidate else None,
        direction=direction if candidate else "NEUTRAL", outcome=outcome, readiness="ready",
        composite_score=(80 if direction == "LONG" else -80) if candidate else None,
        confidence=Decimal(".8") if candidate else None, agreement=Decimal(1),
        contributing_strategies=("trend_following", "momentum_continuation") if candidate else (),
        incomplete_strategy_coverage=False, reasons=({'code': {
            'ELIGIBLE': 'eligibility_checks_passed', 'NO_ACTION': 'no_candidate',
            'BLOCKED': 'insufficient_agreement'}[outcome]},),
        policy_id="policy_test", engine_version="decision-engine-v1")
    return HistoricalDecision(source_bar_open_time=event.open_time,
        source_bar_close_time=event.close_time, decision=decision)
