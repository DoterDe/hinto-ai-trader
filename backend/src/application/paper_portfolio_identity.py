"""Canonical portfolio identities, containing only explicit simulation inputs."""

from src.application.paper_portfolio_settings import PaperPortfolioSettings
from src.strategies.identity import identity

PORTFOLIO_ENGINE_VERSION = "paper-portfolio-engine-v1"
PORTFOLIO_POLICY_VERSION = "paper-portfolio-policy-v1"


def portfolio_policy_identity(settings: PaperPortfolioSettings) -> str:
    return identity("portfolio_policy", (PORTFOLIO_POLICY_VERSION, PaperPortfolioSettings.model_validate(settings)))
