import type { DecisionReasonCode, PortfolioReason } from "../types/generated";

const reasons: Record<DecisionReasonCode | PortfolioReason, string> = {
  eligibility_checks_passed:
    "The analytical requirements passed. Virtual portfolio capacity is checked separately.",
  no_candidate: "No qualifying aggregate candidate was produced.",
  invalid_strategy_snapshot:
    "The strategy snapshot failed contract validation.",
  source_stale: "Required source evidence is stale.",
  source_unavailable: "Required source evidence is unavailable.",
  source_warming_up:
    "More consecutive finalized candles are needed for warm-up.",
  snapshot_too_old: "The strategy observation exceeded its allowed age.",
  feature_too_old: "The feature observation exceeded its allowed age.",
  future_timestamp:
    "An observation timestamp was ahead of the evaluation clock.",
  timestamp_mismatch: "The candidate and source timestamps did not match.",
  candidate_id_mismatch: "The candidate identity did not match its evidence.",
  candidate_source_mismatch:
    "The candidate referred to different source evidence.",
  invalid_contributors: "The contributing strategy list was inconsistent.",
  invalid_candidate_provenance: "Candidate provenance could not be validated.",
  insufficient_agreement:
    "Strategy contributions did not agree strongly enough.",
  insufficient_contributors:
    "Too few strategies contributed to this candidate.",
  incomplete_strategy_coverage:
    "Some configured strategies lacked usable evidence.",
  incomplete_coverage_blocked:
    "The policy requires complete strategy coverage.",
  unsupported_symbol: "The symbol is outside the configured scope.",
  capacity_reserved:
    "Virtual capacity is reserved for the next exact bar open.",
  decision_not_eligible:
    "The upstream decision is not eligible for a virtual reservation.",
  duplicate_decision: "This decision has already been evaluated for capacity.",
  invalid_or_stale_portfolio_state:
    "Virtual portfolio valuation is unknown, invalid or stale.",
  nonpositive_equity: "Known virtual equity is not positive.",
  portfolio_drawdown_limit:
    "The portfolio drawdown reached its blocking threshold.",
  symbol_position_active:
    "This symbol already has an active position or reservation.",
  max_open_positions: "All open-plus-reserved position slots are occupied.",
  gross_exposure_limit:
    "The full proposed reservation would exceed gross exposure capacity.",
  symbol_exposure_limit:
    "The full proposed reservation would exceed the symbol exposure limit.",
};
export function explainReason(
  code: DecisionReasonCode | PortfolioReason,
): string {
  return reasons[code];
}
