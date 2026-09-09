import os

import pytest


@pytest.fixture(autouse=True)
def offline_market_data_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ordinary tests independent of network and local feed overrides."""
    for name in tuple(os.environ):
        if name.startswith(("BINANCE_MARKET_DATA_", "FEATURE_", "STRATEGY_", "DECISION_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("BINANCE_MARKET_DATA_ENABLED", "false")
