import os

import pytest


@pytest.fixture(autouse=True)
def offline_market_data_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ordinary tests independent of network and local feed overrides."""
    for name in tuple(os.environ):
        if name.startswith(("BINANCE_MARKET_DATA_", "FEATURE_", "STRATEGY_", "DECISION_", "BACKTEST_", "PORTFOLIO_", "LIVE_PAPER_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("BINANCE_MARKET_DATA_ENABLED", "false")
    # Existing phase tests exercise their own lifecycle. Phase 8 integration
    # tests explicitly enable the new opt-in consumer with injected public data.
    monkeypatch.setenv("LIVE_PAPER_ENABLED", "false")
