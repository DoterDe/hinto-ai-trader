"""Incremental normalized dataset identity and deterministic simulation identities."""

import hashlib
import re
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
        self.add_fingerprint(identity("bar", validate_bar(event)))

    def add_fingerprint(self, fingerprint: str) -> None:
        """Restore ordered validated record hashes without serializing hash objects."""
        if not isinstance(fingerprint, str) or re.fullmatch(r'bar_[0-9a-f]{64}', fingerprint) is None:
            raise ValueError('invalid canonical bar fingerprint')
        self._digest.update(fingerprint.encode("ascii"))
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
