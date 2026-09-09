"""Fixed typed Phase 3 snapshots; expected strategy scores are hand-calculated."""

from datetime import datetime, timedelta, timezone

from src.domain.features import FeatureSnapshot, Readiness

NOW = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)


def features(**updates: dict) -> FeatureSnapshot:
    values = {
        "trend": dict(ema_fast="100", ema_slow="100", ema_long="100", fast_slow_spread="0",
                      slow_long_spread="0", distance_from_fast="0", distance_from_slow="0", distance_from_long="0"),
        "momentum": dict(rsi="50", roc_percent="0", close_change="0"),
        "volatility": dict(true_range="1", atr="1", normalized_atr="0.01", atr_percent="1", realized_volatility=0.01),
        "volume": dict(rolling_vwap="100", relative_volume="1", taker_buy_ratio="0.5", taker_base_volume_delta_proxy="0"),
        "regime": dict(normalized_atr="0.01", normalized_ema_separation="0", directional_efficiency="0.4", relative_volume="1"),
        "microstructure": dict(bid="100", ask="100", midpoint="100", spread="0", spread_bps="0",
                               bid_quantity="1", ask_quantity="1", top_of_book_imbalance="0"),
    }
    groups = {name: dict(state="ready", reasons=(), required_samples=1 if name == "microstructure" else 50,
                        available_samples=1 if name == "microstructure" else 50,
                        values=fields | updates.get(name, {})) for name, fields in values.items()}
    for name in ("trade", "returns", "mark_funding"):
        groups[name] = dict(state="unavailable", reasons=("not_required",), values=None)
    return FeatureSnapshot(symbol="BTCUSDT", generated_at=NOW, interval="1m", state="partial", reasons=(),
        sources=tuple(dict(stream=stream, event_time=NOW, received_at=NOW, stale=False,
                           connection_id="public" if stream == "book_ticker" else "market", generation=1)
                      for stream in ("kline:1m", "book_ticker", "trade", "mark_price")),
        closed_candle_time=NOW - timedelta(milliseconds=1), closed_candles=50,
        history_resets=0, last_history_reset=None, **groups)


def state(snapshot: FeatureSnapshot, name: str, readiness: Readiness) -> FeatureSnapshot:
    data = getattr(snapshot, name).model_dump()
    data.update(state=readiness, reasons=(readiness.value,), values=None)
    group = FeatureSnapshot.model_fields[name].annotation(**data)
    return FeatureSnapshot.model_validate(snapshot.model_copy(update={name: group}))


def positive_trend() -> FeatureSnapshot:
    return features(trend=dict(ema_fast="102", ema_slow="101", ema_long="100",
                               distance_from_slow="0.02", distance_from_fast="0.01"),
                    momentum=dict(roc_percent="2"), regime=dict(directional_efficiency="0.55"))


def positive_momentum() -> FeatureSnapshot:
    return features(momentum=dict(roc_percent="2", rsi="70", close_change="1"),
                    volume=dict(relative_volume="2", taker_buy_ratio="0.8", taker_base_volume_delta_proxy="6"))


def positive_stretch() -> FeatureSnapshot:
    return features(trend=dict(distance_from_slow="0.03", distance_from_fast="0.02"),
                    momentum=dict(rsi="70"), regime=dict(directional_efficiency="0.25"))
