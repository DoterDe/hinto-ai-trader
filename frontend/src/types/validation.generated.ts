/* Generated from the backend serialization schema. Run npm run types. */

export type State = "UNAVAILABLE" | "READY" | "INVALID";
export type Reason =
  | "NO_REPORT_CONFIGURED"
  | "REPORT_NOT_FOUND"
  | "REPORT_INVALID"
  | "REPORT_LOADED";
export type ReportId = string | null;
export type DatasetId = string | null;
export type Mode = "PAPER / VIRTUAL / RESEARCH ONLY";
export type ReadOnly = true;
export type ReportId1 = string;
export type ContentChecksum = string;
export type DatasetId1 = string;
export type DatasetStatus = "VALID" | "VALID_WITH_GAPS";
export type DatasetStart = string;
export type DatasetEnd = string;
export type TotalBars = number;
export type DuplicateCount = number;
export type MissingBarCount = number;
export type Symbol = string;
export type ObservedBars = number;
export type ExpectedBars = number;
export type MissingBars = number;
export type CoverageFraction = string;
export type FirstOpen = string | null;
export type LastBoundary = string | null;
export type Start = string;
export type End = string;
export type MissingBars1 = number;
/**
 * @maxItems 100001
 */
export type Gaps = DatasetGap[];
/**
 * @maxItems 128
 */
export type Coverage = DatasetCoverage[];
export type ProtocolId = string;
export type Version = "walk-forward-v1";
export type DatasetId2 = string;
export type DatasetSchemaVersion = "historical-dataset-v1";
/**
 * @minItems 1
 * @maxItems 128
 */
export type Symbols = [string, ...string[]];
export type Interval = string;
export type WalkForwardMode = "EXPANDING" | "ROLLING";
export type MinimumContextBoundaries = number;
export type WarmupBoundaries = number;
export type TestBoundaries = number;
export type StepBoundaries = number;
export type RollingContextBoundaries = number | null;
export type AllowTestOverlap = boolean;
export type PartialWindow = "INCLUDE" | "REJECT";
export type EvaluatorVersion = "walk-forward-evaluator-v1";
export type BacktestEngineVersion = string;
export type StrategyEngineVersion = string;
export type DecisionEngineVersion = string;
export type FeatureSettingsId = string;
export type StrategySettingsId = string;
export type DecisionPolicyId = string;
export type BacktestSettingsId = string;
export type RegimeDefinitionId = string;
export type Version1 = "causal-regimes-v1";
export type EmaSeparationDeadband = "0.0005";
export type DirectionalEfficiencyFloor = "0.25";
export type NormalizedAtrLowUpper = "0.005";
export type NormalizedAtrMediumUpper = "0.02";
export type MinimumCompletedSamples = 30;
export type SplitId = string;
export type ResultId = string;
export type Ordinal = number;
export type Status = string;
export type ContextStart = string;
export type ContextEnd = string;
export type TestStart = string;
export type TestEnd = string;
export type RequiredWarmup = number;
export type ContextBoundaryCount = number;
export type TestBoundaryCount = number;
export type ObservedTestBoundaries = number;
/**
 * @maxItems 128
 */
export type TestCoverage = DatasetCoverage[];
export type Warnings = string[];
export type EvaluatedDecisionCount = number;
export type EligibleCount = number;
export type BlockedCount = number;
export type NoActionCount = number;
export type CompletedCount = number;
export type IncompleteCount = number;
export type BoundaryCensoredCount = number;
export type WinCount = number;
export type LossCount = number;
export type FlatCount = number;
export type WinRate = string | null;
export type MeanGrossReturn = string | null;
export type MeanNetReturn = string | null;
export type SumGrossReturns = string;
export type SumSimulatedCosts = string;
export type SumNetReturns = string;
export type NormalizedMaxDrawdown = string;
export type Dimension = "symbol" | "trend" | "volatility";
export type Key = string;
export type Count = number;
export type Minimum = string | null;
export type Maximum = string | null;
export type Mean = string | null;
export type Warnings1 = string[];
/**
 * @maxItems 136
 */
export type Groups = ValidationGroupSummary[];
/**
 * @maxItems 4
 */
export type Costs =
  | []
  | [ValidationCostSummary]
  | [ValidationCostSummary, ValidationCostSummary]
  | [ValidationCostSummary, ValidationCostSummary, ValidationCostSummary]
  | [
      ValidationCostSummary,
      ValidationCostSummary,
      ValidationCostSummary,
      ValidationCostSummary,
    ];
export type ScenarioId = string;
export type ModelVersion = "phase6-cost-v1";
export type FeeBpsPerSide = string;
export type SlippageBpsPerSide = string;
export type IsBaseline = boolean;
export type MeanCostReturn = string | null;
export type SignChangedCount = number;
export type Warnings2 = string[];
/**
 * @maxItems 256
 */
export type Windows = ValidationWindowSummary[];
export type Warnings3 = string[];
export type Limitations = string[];

export interface ValidationSnapshot {
  status: ValidationStatus;
  report: ValidationProjection | null;
}
export interface ValidationStatus {
  state: State;
  reason: Reason;
  report_id: ReportId;
  dataset_id: DatasetId;
  mode: Mode;
  read_only: ReadOnly;
}
export interface ValidationProjection {
  report_id: ReportId1;
  content_checksum: ContentChecksum;
  dataset_id: DatasetId1;
  dataset_status: DatasetStatus;
  dataset_start: DatasetStart;
  dataset_end: DatasetEnd;
  total_bars: TotalBars;
  duplicate_count: DuplicateCount;
  missing_bar_count: MissingBarCount;
  coverage: Coverage;
  protocol_id: ProtocolId;
  protocol: WalkForwardProtocol;
  engines: WalkForwardEngineIdentity;
  regime_definition_id: RegimeDefinitionId;
  regime_definition: RegimeDefinition;
  windows: Windows;
  aggregate: ValidationAnalysisSummary | null;
  warnings: Warnings3;
  limitations: Limitations;
}
export interface DatasetCoverage {
  symbol: Symbol;
  observed_bars: ObservedBars;
  expected_bars: ExpectedBars;
  missing_bars: MissingBars;
  coverage_fraction: CoverageFraction;
  first_open: FirstOpen;
  last_boundary: LastBoundary;
  gaps: Gaps;
}
/**
 * Missing open-time slots in [start, end); no materialized missing bars.
 */
export interface DatasetGap {
  start: Start;
  end: End;
  missing_bars: MissingBars1;
}
export interface WalkForwardProtocol {
  version: Version;
  dataset_id: DatasetId2;
  dataset_schema_version: DatasetSchemaVersion;
  symbols: Symbols;
  interval: Interval;
  mode: WalkForwardMode;
  minimum_context_boundaries: MinimumContextBoundaries;
  warmup_boundaries: WarmupBoundaries;
  test_boundaries: TestBoundaries;
  step_boundaries: StepBoundaries;
  rolling_context_boundaries: RollingContextBoundaries;
  allow_test_overlap: AllowTestOverlap;
  partial_window: PartialWindow;
}
export interface WalkForwardEngineIdentity {
  evaluator_version: EvaluatorVersion;
  backtest_engine_version: BacktestEngineVersion;
  strategy_engine_version: StrategyEngineVersion;
  decision_engine_version: DecisionEngineVersion;
  feature_settings_id: FeatureSettingsId;
  strategy_settings_id: StrategySettingsId;
  decision_policy_id: DecisionPolicyId;
  backtest_settings_id: BacktestSettingsId;
}
export interface RegimeDefinition {
  version: Version1;
  ema_separation_deadband: EmaSeparationDeadband;
  directional_efficiency_floor: DirectionalEfficiencyFloor;
  normalized_atr_low_upper: NormalizedAtrLowUpper;
  normalized_atr_medium_upper: NormalizedAtrMediumUpper;
  minimum_completed_samples: MinimumCompletedSamples;
}
export interface ValidationWindowSummary {
  split_id: SplitId;
  result_id: ResultId;
  ordinal: Ordinal;
  status: Status;
  context_start: ContextStart;
  context_end: ContextEnd;
  test_start: TestStart;
  test_end: TestEnd;
  required_warmup: RequiredWarmup;
  context_boundary_count: ContextBoundaryCount;
  test_boundary_count: TestBoundaryCount;
  observed_test_boundaries: ObservedTestBoundaries;
  test_coverage: TestCoverage;
  warnings: Warnings;
  analysis: ValidationAnalysisSummary | null;
}
export interface ValidationAnalysisSummary {
  metrics: ValidationMetricSummary;
  groups: Groups;
  costs: Costs;
}
export interface ValidationMetricSummary {
  evaluated_decision_count: EvaluatedDecisionCount;
  eligible_count: EligibleCount;
  blocked_count: BlockedCount;
  no_action_count: NoActionCount;
  completed_count: CompletedCount;
  incomplete_count: IncompleteCount;
  boundary_censored_count: BoundaryCensoredCount;
  win_count: WinCount;
  loss_count: LossCount;
  flat_count: FlatCount;
  win_rate: WinRate;
  mean_gross_return: MeanGrossReturn;
  mean_net_return: MeanNetReturn;
  sum_gross_returns: SumGrossReturns;
  sum_simulated_costs: SumSimulatedCosts;
  sum_net_returns: SumNetReturns;
  normalized_max_drawdown: NormalizedMaxDrawdown;
}
export interface ValidationGroupSummary {
  dimension: Dimension;
  key: Key;
  metrics: ValidationMetricSummary;
  confidence: SampleSummary;
  composite_score: SampleSummary;
  warnings: Warnings1;
}
export interface SampleSummary {
  count: Count;
  minimum: Minimum;
  maximum: Maximum;
  mean: Mean;
}
export interface ValidationCostSummary {
  scenario_id: ScenarioId;
  assumptions: CostScenario;
  is_baseline: IsBaseline;
  metrics: ValidationMetricSummary;
  mean_cost_return: MeanCostReturn;
  sign_changed_count: SignChangedCount;
  warnings: Warnings2;
}
export interface CostScenario {
  model_version: ModelVersion;
  fee_bps_per_side: FeeBpsPerSide;
  slippage_bps_per_side: SlippageBpsPerSide;
}
