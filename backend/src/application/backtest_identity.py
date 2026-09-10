"""Incremental normalized dataset identity and deterministic simulation identities."""

import hashlib
from datetime import datetime

from src.application.backtest_settings import BacktestSettings
from src.application.historical_bars import validate_bar
from src.domain.market_data import KlineEvent
from src.strategies.identity import identity

BACKTEST_ENGINE_VERSION = "backtest-engine-v1"


class DatasetIdentity:
    def __init__(self) -> None:
        self._digest = hashlib.sha256(b"historical-final-klines-v1\n")
        self.count = 0

    def add(self, event: KlineEvent) -> None:
        # A fixed-length canonical record hash avoids ambiguous concatenation.
        self._digest.update(identity("bar", validate_bar(event)).encode("ascii"))
        self._digest.update(b"\n")
        self.count += 1

    @property
    def value(self) -> str:
        return "dataset_" + self._digest.hexdigest()


def settings_identity(settings: BacktestSettings) -> str:
    return identity("backtest_settings", BacktestSettings.model_validate(settings))


def outcome_identity(decision_id: str, settings_id: str, source_open_time: datetime,
                     evidence_id: str, status: str, reason: str) -> str:
    return identity("outcome", (BACKTEST_ENGINE_VERSION, decision_id, settings_id,
                                source_open_time, evidence_id, status, reason))
