"""Bounded active-horizon evidence, preserving the Phase 6/7 dataset hash."""

from src.application.backtest_identity import DatasetIdentity


class PositionEvidenceIdentity(DatasetIdentity):
    def __init__(self, limit: int, fingerprints: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.limit = limit
        self.fingerprints: list[str] = []
        for fingerprint in fingerprints:
            self.add_fingerprint(fingerprint)

    def add_fingerprint(self, fingerprint: str) -> None:
        if len(self.fingerprints) >= self.limit:
            raise ValueError('position evidence exceeds fixed holding horizon')
        super().add_fingerprint(fingerprint)
        self.fingerprints.append(fingerprint)
