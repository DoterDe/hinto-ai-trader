"""Stable analytical identities, independent of the time of an API read."""

from src.domain.decisions import DecisionOutcome, DecisionPolicy
from src.strategies.identity import identity

DECISION_ENGINE_VERSION = "decision-engine-v1"


def policy_identity(policy: DecisionPolicy, symbols: tuple[str, ...] = ()) -> str:
    return identity("decision_policy", (DecisionPolicy.model_validate(policy), tuple(sorted(symbols))))


def decision_identity(*, policy_id: str, symbol: str, observation_id: str,
                      candidate_id: str | None, outcome: DecisionOutcome,
                      strategy_settings_id: str, strategy_engine_version: str) -> str:
    return identity("decision", (DECISION_ENGINE_VERSION, policy_id, symbol,
        strategy_engine_version, strategy_settings_id, observation_id,
        candidate_id if candidate_id is not None else "NO_CANDIDATE", outcome))
