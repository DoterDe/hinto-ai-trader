/* Generated from the backend serialization schema. Run npm run types. */

export type AsOf = string;
export type Mode = "paper";
export type EngineVersion = "live-paper-v1";
export type AsOf1 = string;
export type LivePaperStatus =
  | "DISABLED"
  | "STARTING"
  | "WARMING_UP"
  | "RUNNING"
  | "DEGRADED"
  | "STOPPING"
  | "STOPPED"
  | "ERROR";
export type Reasons = string[];
export type Running = boolean;
export type StartedAt = string | null;
export type LatestUpdateAt = string | null;
export type SubscriberDroppedEvents = number;
export type LastBoundary = string | null;
export type Interval = string;
export type Symbol = string;
export type Boundary = string | null;
export type ClosedCandles = number;
export type Readiness =
  "ready" | "warming_up" | "stale" | "unavailable" | "partial";
export type StrategyReadiness =
  "ready" | "unavailable" | "stale" | "warming_up";
export type DecisionOutcome = "ELIGIBLE" | "BLOCKED" | "NO_ACTION";
export type Symbols = LiveSymbolSummary[];
export type Runtime = string;
export type Features = string;
export type Strategies = string;
export type Decisions = string;
export type Portfolio = string;
export type Costs = string;
export type Enabled = boolean;
export type BatchTimeoutMs = number;
export type EventHistoryLimit = number;
export type CurveHistoryLimit = number;
export type PositionHistoryLimit = number;
export type PendingBatchLimit = number;
export type QueueLimit = number;
export type EmaFast = number;
export type EmaSlow = number;
export type EmaLong = number;
export type RsiPeriod = number;
export type AtrPeriod = number;
export type RocPeriod = number;
export type VolatilityWindow = number;
export type RelativeVolumeWindow = number;
export type VwapWindow = number;
export type RollingReturnWindows = number[];
export type HistoryLimit = number;
export type StrategyId =
  "trend_following" | "momentum_continuation" | "mean_reversion";
export type EnabledStrategies = StrategyId[];
export type MinAbsoluteStrategyScore = string;
export type CandidateScoreThreshold = string;
export type MinCandidateConfidence = string;
export type RsiNeutralLow = string;
export type RsiNeutralHigh = string;
export type RsiExtremeLow = string;
export type RsiExtremeHigh = string;
export type MaxAcceptableSpreadBps = string;
export type TrendEfficiencyFloor = string;
export type StrongTrendEfficiency = string;
export type RelativeVolumeBaseline = string;
export type RelativeVolumeExhaustion = string;
export type EmaSeparationDeadZone = string;
export type EmaSeparationSaturation = string;
export type PriceDistanceDeadZone = string;
export type PriceDistanceSaturation = string;
export type RocDeadZone = string;
export type RocSaturation = string;
export type TakerBiasDeadZone = string;
export type TakerBiasSaturation = string;
export type ReversionStretchDeadZone = string;
export type ReversionStretchSaturation = string;
export type AtrSoftLimit = string;
export type AtrHardLimit = string;
export type OptionalContextMissingQuality = string;
export type MaxFeatureAgeSeconds = string;
export type TrendWeight = string;
export type MomentumWeight = string;
export type MeanReversionWeight = string;
export type MaxStrategySnapshotAgeSeconds = string;
export type MinDecisionAgreement = string;
export type MinContributingStrategies = number;
export type BlockIncompleteStrategyCoverage = boolean;
export type InitialVirtualEquity = string;
export type TargetPositionFraction = string;
export type MaxGrossExposureFraction = string;
export type MaxSymbolExposureFraction = string;
export type MaxOpenPositions = number;
export type MaxDrawdownFraction = string;
export type OnePositionPerSymbol = boolean;
export type HoldingPeriodBars = number;
export type FeeBpsPerSide = string;
export type SlippageBpsPerSide = string;
export type ChronologicalSegments = number;
export type AnalyticalView = "finalized_candles_only";
export type AsOf2 = string;
export type StaleAfterSeconds = number;
export type Stale = boolean;
export type ConnectionId = string;
export type EventType =
  "trade" | "kline" | "book_ticker" | "mark_price" | "depth";
export type EventTypes = EventType[];
export type ConnectionStatus =
  "disabled" | "connecting" | "connected" | "reconnecting" | "stopped";
export type ChangedAt = string;
export type Generation = number;
export type LastMessageAt = string | null;
export type ReconnectAttempt = number;
export type MalformedMessages = number;
export type Reason = string | null;
export type Connections = MarketConnectionState[];
export type Symbol1 = string;
export type Stale1 = boolean;
export type LastEventAt = string | null;
export type LastReceivedAt = string | null;
export type KlineInterval = string | null;
export type Stale2 = boolean;
export type Reason1 =
  | (
      | "missing"
      | "disconnected"
      | "awaiting_recovery"
      | "clock_skew"
      | "event_stale"
      | "receive_stale"
    )
  | null;
export type EventTime = string | null;
export type ReceivedAt = string | null;
export type EventAgeSeconds = number | null;
export type ReceiveAgeSeconds = number | null;
export type ConnectionId1 = string | null;
export type Generation1 = number | null;
export type SubscriberCount = number;
export type DroppedEvents = number;
export type IgnoredEvents = number;
export type Enabled1 = boolean;
export type PersistenceStatus =
  | "DISABLED"
  | "NEW_SESSION"
  | "RECOVERING"
  | "RECOVERED"
  | "DURABLE"
  | "DEGRADED"
  | "INCOMPATIBLE"
  | "CORRUPT"
  | "ERROR";
export type Reason2 = string | null;
export type DatabaseHealthy = boolean;
export type SessionId = string | null;
export type SessionCreatedAt = string | null;
export type Recovered = boolean;
export type SchemaVersion = 1;
export type DurableBoundary = string | null;
export type CheckpointAt = string | null;
export type CheckpointId = string | null;
export type Checksum = string | null;
export type RetainedCheckpoints = number;
export type RetainedAuditEvents = number;
export type InMemoryBoundary = string | null;
export type HasUncommittedChanges = boolean;
export type ConfigurationCompatible = boolean | null;
export type AsOf3 = string;
export type ValuationAsOf = string | null;
export type ValuationComplete = boolean;
export type Timestamp = string;
export type RealizedEquity = string;
export type UnrealizedNetPnl = string | null;
export type MarkedEquity = string | null;
export type PeakEquity = string;
export type Drawdown = string | null;
export type Symbol2 = string;
export type OpenNotional = string;
export type ReservedNotional = string;
export type OpenCount = number;
export type ReservationCount = number;
export type Exposures = PaperExposure[];
export type OpenNotional1 = string;
export type ReservedNotional1 = string;
export type GrossExposure = string;
export type GrossExposureFraction = string | null;
export type OpenCount1 = number;
export type ReservationCount1 = number;
export type InitialVirtualEquity1 = string;
export type GrossPnl = string;
export type FeeCost = string;
export type SlippageCost = string;
export type TotalCost = string;
export type NetPnl = string;
export type OutstandingEntryFeeCost = string;
export type OutstandingEntrySlippageCost = string;
export type OpenedCount = number;
export type CompletedCount = number;
export type ExpiredReservations = number;
export type AsOf4 = string;
export type ReservationId = string;
export type DecisionId = string;
export type Symbol3 = string;
export type Direction = "LONG" | "SHORT";
export type VirtualNotional = string;
export type DecisionTime = string;
export type ExpectedEntryTime = string;
export type PolicyId = string;
export type Reservations = PaperEntryReservation[];
export type PositionId = string;
export type Interval1 = string;
export type EntryTime = string;
export type EntryPriceRaw = string;
export type HoldingPeriodBars1 = number;
export type BarsHeld = number;
export type ExpectedNextOpen = string;
export type BacktestSettingsId = string;
export type Status = "OPEN" | "CLOSED" | "INCOMPLETE";
export type Reason3 =
  "holding" | "horizon_completed" | "missing_horizon_bar" | "dataset_ended";
export type LastMarkTime = string | null;
export type LastMarkPrice = string | null;
export type UnrealizedNetPnl1 = string | null;
export type Active = LivePosition[];
export type CloseId = string;
export type PositionId1 = string;
export type ExitTime = string;
export type ExitPriceRaw = string;
export type Closed = LiveClose[];
export type RetainedClosedCount = number;
export type CompletedCount1 = number;
export type Symbol4 = string;
export type AsOf5 = string;
export type Symbol5 = string;
export type EventTime1 = string;
export type ReceivedAt1 = string;
export type EventType1 = "kline";
export type Interval2 = string;
export type OpenTime = string;
export type CloseTime = string;
export type Open = string;
export type High = string;
export type Low = string;
export type Close = string;
export type Volume = string;
export type QuoteVolume = string;
export type TradeCount = number;
export type IsClosed = boolean;
export type TakerBuyVolume = string;
export type TakerBuyQuoteVolume = string;
export type Symbol6 = string;
export type EventTime2 = string;
export type ReceivedAt2 = string;
export type EventType2 = "trade";
export type AggregateTradeId = number;
export type FirstTradeId = number;
export type LastTradeId = number;
export type Price = string;
export type Quantity = string;
export type TradeTime = string;
export type BuyerIsMaker = boolean;
export type NormalQuantity = string | null;
export type Symbol7 = string;
export type EventTime3 = string;
export type ReceivedAt3 = string;
export type EventType3 = "book_ticker";
export type UpdateId = number;
export type BidPrice = string;
export type BidQuantity = string;
export type AskPrice = string;
export type AskQuantity = string;
export type TransactionTime = string;
export type Symbol8 = string;
export type EventTime4 = string;
export type ReceivedAt4 = string;
export type EventType4 = "mark_price";
export type MarkPrice = string;
export type IndexPrice = string;
export type EstimatedSettlePrice = string | null;
export type FundingRate = string;
export type NextFundingTime = string;
export type Boundary1 = string;
export type PublishedAt = string;
export type ReceivedAt5 = string;
export type ConnectionId2 = string;
export type ConnectionGeneration = number;
export type Symbol9 = string;
export type GeneratedAt = string;
export type Interval3 = string;
export type Reasons1 = string[];
export type Stream = string;
export type EventTime5 = string | null;
export type ReceivedAt6 = string | null;
export type Stale3 = boolean;
export type Reason4 = string | null;
export type ConnectionId3 = string | null;
export type Generation2 = number | null;
export type Sources = FeatureSource[];
export type ClosedCandleTime = string | null;
export type ClosedCandles1 = number;
export type HistoryResets = number;
export type LastHistoryReset = string | null;
export type Reasons2 = string[];
export type RequiredSamples = number;
export type AvailableSamples = number;
export type Price1 = string;
export type Quantity1 = string;
export type Reasons3 = string[];
export type RequiredSamples1 = number;
export type AvailableSamples1 = number;
export type Close1 = string;
export type SimpleReturn = string;
export type LogReturn = number;
export type Window = number;
export type Value = string;
export type RollingReturns = WindowReturn[];
export type Reasons4 = string[];
export type RequiredSamples2 = number;
export type AvailableSamples2 = number;
export type EmaFast1 = string;
export type EmaSlow1 = string;
export type EmaLong1 = string;
export type FastSlowSpread = string;
export type SlowLongSpread = string;
export type DistanceFromFast = string;
export type DistanceFromSlow = string;
export type DistanceFromLong = string;
export type Reasons5 = string[];
export type RequiredSamples3 = number;
export type AvailableSamples3 = number;
export type Rsi = string;
export type RocPercent = string;
export type CloseChange = string;
export type Reasons6 = string[];
export type RequiredSamples4 = number;
export type AvailableSamples4 = number;
export type TrueRange = string;
export type Atr = string;
export type NormalizedAtr = string;
export type AtrPercent = string;
export type RealizedVolatility = number;
export type Reasons7 = string[];
export type RequiredSamples5 = number;
export type AvailableSamples5 = number;
export type RollingVwap = string;
export type RelativeVolume = string;
export type TakerBuyRatio = string;
export type TakerBaseVolumeDeltaProxy = string;
export type Reasons8 = string[];
export type RequiredSamples6 = number;
export type AvailableSamples6 = number;
export type Bid = string;
export type Ask = string;
export type Midpoint = string;
export type Spread = string;
export type SpreadBps = string;
export type BidQuantity1 = string;
export type AskQuantity1 = string;
export type TopOfBookImbalance = string;
export type Reasons9 = string[];
export type RequiredSamples7 = number;
export type AvailableSamples7 = number;
export type MarkPrice1 = string;
export type IndexPrice1 = string;
export type Basis = string;
export type BasisPercent = string;
export type BasisBps = string;
export type FundingRate1 = string;
export type NextFundingTime1 = string;
export type SecondsUntilFunding = number;
export type Reasons10 = string[];
export type RequiredSamples8 = number;
export type AvailableSamples8 = number;
export type NormalizedAtr1 = string;
export type NormalizedEmaSeparation = string;
export type DirectionalEfficiency = string;
export type RelativeVolume1 = string;
export type Symbol10 = string;
export type GeneratedAt1 = string;
export type SourceFeatureTimestamp = string;
export type SnapshotId = string;
export type ObservationId = string;
export type SettingsId = string;
export type EngineVersion1 = string;
export type Symbol11 = string;
export type GeneratedAt2 = string;
export type SourceFeatureTimestamp1 = string;
export type SnapshotId1 = string;
export type StrategyDirection = "LONG" | "SHORT" | "NEUTRAL";
export type Score = string | null;
export type Confidence = string | null;
export type Reasons11 = string[];
export type RequiredFeatureGroups = (
  "trend" | "momentum" | "volatility" | "volume" | "regime" | "microstructure"
)[];
export type OptionalFeatureGroups = (
  "trend" | "momentum" | "volatility" | "volume" | "regime" | "microstructure"
)[];
export type Name = string;
export type Value1 = string | null;
export type Reference = string | null;
export type Normalized = string | null;
export type Weight = string;
export type Multiplier = string;
export type Contribution = string;
export type Code = string;
export type Evidence = StrategyEvidence[];
export type Assessments = StrategyAssessment[];
export type CompositeScore = string | null;
export type Confidence1 = string | null;
export type Agreement = string | null;
export type Reasons12 = string[];
export type CandidateId = string;
export type Symbol12 = string;
export type GeneratedAt3 = string;
export type SnapshotId2 = string;
export type ObservationId1 = string;
export type CompositeScore1 = string;
export type Confidence2 = string;
export type ContributingStrategies = StrategyId[];
export type Reasons13 = string[];
export type PortfolioDecisionId = string;
export type DecisionId1 = string;
export type Symbol13 = string;
export type GeneratedAt4 = string;
export type SourceStrategyTimestamp = string | null;
export type SourceFeatureTimestamp2 = string | null;
export type StrategySnapshotId = string;
export type ObservationId2 = string;
export type StrategySettingsId = string;
export type StrategyEngineVersion = string;
export type CandidateId1 = string | null;
export type DecisionReadiness = "ready" | "stale" | "unavailable";
export type CompositeScore2 = string | null;
export type Confidence3 = string | null;
export type Agreement1 = string | null;
/**
 * @maxItems 3
 */
export type ContributingStrategies1 =
  | []
  | [StrategyId]
  | [StrategyId, StrategyId]
  | [StrategyId, StrategyId, StrategyId];
export type IncompleteStrategyCoverage = boolean;
/**
 * @minItems 1
 * @maxItems 20
 */
export type Reasons14 =
  | [DecisionReason]
  | [DecisionReason, DecisionReason]
  | [DecisionReason, DecisionReason, DecisionReason]
  | [DecisionReason, DecisionReason, DecisionReason, DecisionReason]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ]
  | [
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
      DecisionReason,
    ];
export type DecisionReasonCode =
  | "eligibility_checks_passed"
  | "no_candidate"
  | "invalid_strategy_snapshot"
  | "source_stale"
  | "source_unavailable"
  | "source_warming_up"
  | "snapshot_too_old"
  | "feature_too_old"
  | "future_timestamp"
  | "timestamp_mismatch"
  | "candidate_id_mismatch"
  | "candidate_source_mismatch"
  | "invalid_contributors"
  | "invalid_candidate_provenance"
  | "insufficient_agreement"
  | "insufficient_contributors"
  | "incomplete_strategy_coverage"
  | "incomplete_coverage_blocked"
  | "unsupported_symbol";
export type Observed = string | null;
export type Threshold = string | null;
export type PolicyId1 = string;
export type EngineVersion2 = string;
export type PolicyId2 = string;
export type StateId = string;
export type EvaluatedAt = string;
export type PortfolioAction = "IGNORED" | "REJECTED" | "RESERVED";
export type PortfolioReason =
  | "capacity_reserved"
  | "decision_not_eligible"
  | "duplicate_decision"
  | "invalid_or_stale_portfolio_state"
  | "nonpositive_equity"
  | "portfolio_drawdown_limit"
  | "symbol_position_active"
  | "max_open_positions"
  | "gross_exposure_limit"
  | "symbol_exposure_limit";
export type DesiredNotional = string | null;
export type ReservationId1 = string | null;
export type Market = LiveMarketSnapshot[];
export type Decisions1 = LiveAnalysis[];
export type EventId = string;
export type Timestamp1 = string;
export type Category = "runtime" | "feed" | "batch" | "portfolio";
export type Severity = "info" | "warning" | "error";
export type Symbol14 = string | null;
export type Reason5 = string;
export type Explanation = string;
export type RelatedId = string | null;
export type Events = LivePaperEvent[];
export type OpenCountBeforeExits = number;
export type Curve = PaperPortfolioCurvePoint[];

export interface LiveDashboardSnapshot {
  as_of: AsOf;
  status: LiveStatusSnapshot;
  portfolio: LivePortfolioSnapshot;
  positions: LivePositionsSnapshot;
  market: Market;
  decisions: Decisions1;
  events: Events;
  curve: Curve;
}
export interface LiveStatusSnapshot {
  mode: Mode;
  engine_version: EngineVersion;
  as_of: AsOf1;
  status: LivePaperStatus;
  reasons: Reasons;
  running: Running;
  started_at: StartedAt;
  latest_update_at: LatestUpdateAt;
  subscriber_dropped_events: SubscriberDroppedEvents;
  last_boundary: LastBoundary;
  interval: Interval;
  symbols: Symbols;
  counters: Counters;
  configuration: LiveConfiguration;
  market: MarketStatus;
  persistence: PersistenceSnapshot;
}
export interface LiveSymbolSummary {
  symbol: Symbol;
  boundary: Boundary;
  closed_candles: ClosedCandles;
  feature_state: Readiness;
  strategy_state: StrategyReadiness;
  decision_outcome: DecisionOutcome | null;
}
export interface Counters {
  /**
   * This interface was referenced by `Counters`'s JSON-Schema definition
   * via the `patternProperty` "^[a-z][a-z0-9_]{0,63}$".
   */
  [k: string]: number;
}
export interface LiveConfiguration {
  identities: LiveConfigurationIds;
  runtime: LivePaperSettings;
  features: FeatureSettings;
  strategies: StrategySettings;
  decisions: DecisionSettings;
  portfolio: PaperPortfolioSettings;
  costs: BacktestSettings;
  analytical_view: AnalyticalView;
}
export interface LiveConfigurationIds {
  runtime: Runtime;
  features: Features;
  strategies: Strategies;
  decisions: Decisions;
  portfolio: Portfolio;
  costs: Costs;
}
export interface LivePaperSettings {
  enabled: Enabled;
  batch_timeout_ms: BatchTimeoutMs;
  event_history_limit: EventHistoryLimit;
  curve_history_limit: CurveHistoryLimit;
  position_history_limit: PositionHistoryLimit;
  pending_batch_limit: PendingBatchLimit;
  queue_limit: QueueLimit;
}
/**
 * Exchange-independent windows. Environment overrides use FEATURE_* names.
 */
export interface FeatureSettings {
  ema_fast: EmaFast;
  ema_slow: EmaSlow;
  ema_long: EmaLong;
  rsi_period: RsiPeriod;
  atr_period: AtrPeriod;
  roc_period: RocPeriod;
  volatility_window: VolatilityWindow;
  relative_volume_window: RelativeVolumeWindow;
  vwap_window: VwapWindow;
  rolling_return_windows: RollingReturnWindows;
  history_limit: HistoryLimit;
}
export interface StrategySettings {
  enabled_strategies: EnabledStrategies;
  min_absolute_strategy_score: MinAbsoluteStrategyScore;
  candidate_score_threshold: CandidateScoreThreshold;
  min_candidate_confidence: MinCandidateConfidence;
  rsi_neutral_low: RsiNeutralLow;
  rsi_neutral_high: RsiNeutralHigh;
  rsi_extreme_low: RsiExtremeLow;
  rsi_extreme_high: RsiExtremeHigh;
  max_acceptable_spread_bps: MaxAcceptableSpreadBps;
  trend_efficiency_floor: TrendEfficiencyFloor;
  strong_trend_efficiency: StrongTrendEfficiency;
  relative_volume_baseline: RelativeVolumeBaseline;
  relative_volume_exhaustion: RelativeVolumeExhaustion;
  ema_separation_dead_zone: EmaSeparationDeadZone;
  ema_separation_saturation: EmaSeparationSaturation;
  price_distance_dead_zone: PriceDistanceDeadZone;
  price_distance_saturation: PriceDistanceSaturation;
  roc_dead_zone: RocDeadZone;
  roc_saturation: RocSaturation;
  taker_bias_dead_zone: TakerBiasDeadZone;
  taker_bias_saturation: TakerBiasSaturation;
  reversion_stretch_dead_zone: ReversionStretchDeadZone;
  reversion_stretch_saturation: ReversionStretchSaturation;
  atr_soft_limit: AtrSoftLimit;
  atr_hard_limit: AtrHardLimit;
  optional_context_missing_quality: OptionalContextMissingQuality;
  max_feature_age_seconds: MaxFeatureAgeSeconds;
  trend_weight: TrendWeight;
  momentum_weight: MomentumWeight;
  mean_reversion_weight: MeanReversionWeight;
}
export interface DecisionSettings {
  max_strategy_snapshot_age_seconds: MaxStrategySnapshotAgeSeconds;
  min_decision_agreement: MinDecisionAgreement;
  min_contributing_strategies: MinContributingStrategies;
  block_incomplete_strategy_coverage: BlockIncompleteStrategyCoverage;
}
export interface PaperPortfolioSettings {
  initial_virtual_equity: InitialVirtualEquity;
  target_position_fraction: TargetPositionFraction;
  max_gross_exposure_fraction: MaxGrossExposureFraction;
  max_symbol_exposure_fraction: MaxSymbolExposureFraction;
  max_open_positions: MaxOpenPositions;
  max_drawdown_fraction: MaxDrawdownFraction;
  one_position_per_symbol: OnePositionPerSymbol;
}
export interface BacktestSettings {
  holding_period_bars: HoldingPeriodBars;
  fee_bps_per_side: FeeBpsPerSide;
  slippage_bps_per_side: SlippageBpsPerSide;
  chronological_segments: ChronologicalSegments;
}
export interface MarketStatus {
  as_of: AsOf2;
  stale_after_seconds: StaleAfterSeconds;
  stale: Stale;
  connections: Connections;
  symbols: Symbols1;
  subscriber_count: SubscriberCount;
  dropped_events: DroppedEvents;
  ignored_events: IgnoredEvents;
}
export interface MarketConnectionState {
  connection_id: ConnectionId;
  event_types: EventTypes;
  status: ConnectionStatus;
  changed_at: ChangedAt;
  generation: Generation;
  last_message_at: LastMessageAt;
  reconnect_attempt: ReconnectAttempt;
  malformed_messages: MalformedMessages;
  reason: Reason;
}
export interface Symbols1 {
  [k: string]: SymbolFreshness;
}
export interface SymbolFreshness {
  symbol: Symbol1;
  stale: Stale1;
  last_event_at: LastEventAt;
  last_received_at: LastReceivedAt;
  streams: Streams;
}
export interface Streams {
  [k: string]: StreamFreshness;
}
export interface StreamFreshness {
  event_type: EventType;
  kline_interval: KlineInterval;
  stale: Stale2;
  reason: Reason1;
  event_time: EventTime;
  received_at: ReceivedAt;
  event_age_seconds: EventAgeSeconds;
  receive_age_seconds: ReceiveAgeSeconds;
  connection_id: ConnectionId1;
  connection_status: ConnectionStatus | null;
  generation: Generation1;
}
export interface PersistenceSnapshot {
  enabled: Enabled1;
  status: PersistenceStatus;
  reason: Reason2;
  database_healthy: DatabaseHealthy;
  session_id: SessionId;
  session_created_at: SessionCreatedAt;
  recovered: Recovered;
  schema_version: SchemaVersion;
  durable_boundary: DurableBoundary;
  checkpoint_at: CheckpointAt;
  checkpoint_id: CheckpointId;
  checksum: Checksum;
  retained_checkpoints: RetainedCheckpoints;
  retained_audit_events: RetainedAuditEvents;
  in_memory_boundary: InMemoryBoundary;
  has_uncommitted_changes: HasUncommittedChanges;
  configuration_compatible: ConfigurationCompatible;
}
export interface LivePortfolioSnapshot {
  as_of: AsOf3;
  valuation_as_of: ValuationAsOf;
  valuation_complete: ValuationComplete;
  state: PaperPortfolioState;
  initial_virtual_equity: InitialVirtualEquity1;
  closed_pnl: PaperPnl;
  outstanding_entry_fee_cost: OutstandingEntryFeeCost;
  outstanding_entry_slippage_cost: OutstandingEntrySlippageCost;
  opened_count: OpenedCount;
  completed_count: CompletedCount;
  expired_reservations: ExpiredReservations;
}
export interface PaperPortfolioState {
  timestamp: Timestamp;
  realized_equity: RealizedEquity;
  unrealized_net_pnl: UnrealizedNetPnl;
  marked_equity: MarkedEquity;
  peak_equity: PeakEquity;
  drawdown: Drawdown;
  exposures: Exposures;
  open_notional: OpenNotional1;
  reserved_notional: ReservedNotional1;
  gross_exposure: GrossExposure;
  gross_exposure_fraction: GrossExposureFraction;
  open_count: OpenCount1;
  reservation_count: ReservationCount1;
}
export interface PaperExposure {
  symbol: Symbol2;
  open_notional: OpenNotional;
  reserved_notional: ReservedNotional;
  open_count: OpenCount;
  reservation_count: ReservationCount;
}
export interface PaperPnl {
  gross_pnl: GrossPnl;
  fee_cost: FeeCost;
  slippage_cost: SlippageCost;
  total_cost: TotalCost;
  net_pnl: NetPnl;
}
export interface LivePositionsSnapshot {
  as_of: AsOf4;
  reservations: Reservations;
  active: Active;
  closed: Closed;
  retained_closed_count: RetainedClosedCount;
  completed_count: CompletedCount1;
}
export interface PaperEntryReservation {
  reservation_id: ReservationId;
  decision_id: DecisionId;
  symbol: Symbol3;
  direction: Direction;
  virtual_notional: VirtualNotional;
  decision_time: DecisionTime;
  expected_entry_time: ExpectedEntryTime;
  policy_id: PolicyId;
}
export interface LivePosition {
  position: PaperPosition;
  unrealized_net_pnl: UnrealizedNetPnl1;
}
export interface PaperPosition {
  position_id: PositionId;
  reservation: PaperEntryReservation;
  interval: Interval1;
  entry_time: EntryTime;
  entry_price_raw: EntryPriceRaw;
  holding_period_bars: HoldingPeriodBars1;
  bars_held: BarsHeld;
  expected_next_open: ExpectedNextOpen;
  backtest_settings_id: BacktestSettingsId;
  status: Status;
  reason: Reason3;
  last_mark_time: LastMarkTime;
  last_mark_price: LastMarkPrice;
}
export interface LiveClose {
  position: PaperPosition;
  close: PaperPositionClose;
}
export interface PaperPositionClose {
  close_id: CloseId;
  position_id: PositionId1;
  exit_time: ExitTime;
  exit_price_raw: ExitPriceRaw;
  pnl: PaperPnl;
}
/**
 * Current public observations, explicitly separate from captured decisions.
 *
 * Depth arrays are deliberately excluded. No last-value price is fabricated
 * for an absent stream, and stream freshness accompanies every observation.
 */
export interface LiveMarketSnapshot {
  symbol: Symbol4;
  as_of: AsOf5;
  streams: Streams1;
  candle: KlineEvent | null;
  trade: TradeEvent | null;
  book_ticker: BookTickerEvent | null;
  mark_price: MarkPriceEvent | null;
  captured_analysis: LiveAnalysis | null;
}
export interface Streams1 {
  [k: string]: StreamFreshness;
}
export interface KlineEvent {
  symbol: Symbol5;
  event_time: EventTime1;
  received_at: ReceivedAt1;
  event_type: EventType1;
  interval: Interval2;
  open_time: OpenTime;
  close_time: CloseTime;
  open: Open;
  high: High;
  low: Low;
  close: Close;
  volume: Volume;
  quote_volume: QuoteVolume;
  trade_count: TradeCount;
  is_closed: IsClosed;
  taker_buy_volume: TakerBuyVolume;
  taker_buy_quote_volume: TakerBuyQuoteVolume;
}
export interface TradeEvent {
  symbol: Symbol6;
  event_time: EventTime2;
  received_at: ReceivedAt2;
  event_type: EventType2;
  aggregate_trade_id: AggregateTradeId;
  first_trade_id: FirstTradeId;
  last_trade_id: LastTradeId;
  price: Price;
  quantity: Quantity;
  trade_time: TradeTime;
  buyer_is_maker: BuyerIsMaker;
  normal_quantity: NormalQuantity;
}
export interface BookTickerEvent {
  symbol: Symbol7;
  event_time: EventTime3;
  received_at: ReceivedAt3;
  event_type: EventType3;
  update_id: UpdateId;
  bid_price: BidPrice;
  bid_quantity: BidQuantity;
  ask_price: AskPrice;
  ask_quantity: AskQuantity;
  transaction_time: TransactionTime;
}
export interface MarkPriceEvent {
  symbol: Symbol8;
  event_time: EventTime4;
  received_at: ReceivedAt4;
  event_type: EventType4;
  mark_price: MarkPrice;
  index_price: IndexPrice;
  estimated_settle_price: EstimatedSettlePrice;
  funding_rate: FundingRate;
  next_funding_time: NextFundingTime;
}
export interface LiveAnalysis {
  boundary: Boundary1;
  published_at: PublishedAt;
  received_at: ReceivedAt5;
  connection_id: ConnectionId2;
  connection_generation: ConnectionGeneration;
  features: FeatureSnapshot;
  strategy: StrategySnapshot;
  portfolio: PortfolioDecisionRecord;
}
export interface FeatureSnapshot {
  symbol: Symbol9;
  generated_at: GeneratedAt;
  interval: Interval3;
  state: Readiness;
  reasons: Reasons1;
  sources: Sources;
  closed_candle_time: ClosedCandleTime;
  closed_candles: ClosedCandles1;
  history_resets: HistoryResets;
  last_history_reset: LastHistoryReset;
  trade: FeatureGroupTradeFeatures;
  returns: FeatureGroupReturnFeatures;
  trend: FeatureGroupTrendFeatures;
  momentum: FeatureGroupMomentumFeatures;
  volatility: FeatureGroupVolatilityFeatures;
  volume: FeatureGroupVolumeFeatures;
  microstructure: FeatureGroupMicrostructureFeatures;
  mark_funding: FeatureGroupMarkFundingFeatures;
  regime: FeatureGroupRegimeFeatures;
}
export interface FeatureSource {
  stream: Stream;
  event_time: EventTime5;
  received_at: ReceivedAt6;
  stale: Stale3;
  reason: Reason4;
  connection_id: ConnectionId3;
  generation: Generation2;
}
export interface FeatureGroupTradeFeatures {
  state: Readiness;
  reasons: Reasons2;
  required_samples: RequiredSamples;
  available_samples: AvailableSamples;
  values: TradeFeatures | null;
}
export interface TradeFeatures {
  price: Price1;
  quantity: Quantity1;
}
export interface FeatureGroupReturnFeatures {
  state: Readiness;
  reasons: Reasons3;
  required_samples: RequiredSamples1;
  available_samples: AvailableSamples1;
  values: ReturnFeatures | null;
}
export interface ReturnFeatures {
  close: Close1;
  simple_return: SimpleReturn;
  log_return: LogReturn;
  rolling_returns: RollingReturns;
}
export interface WindowReturn {
  window: Window;
  value: Value;
}
export interface FeatureGroupTrendFeatures {
  state: Readiness;
  reasons: Reasons4;
  required_samples: RequiredSamples2;
  available_samples: AvailableSamples2;
  values: TrendFeatures | null;
}
export interface TrendFeatures {
  ema_fast: EmaFast1;
  ema_slow: EmaSlow1;
  ema_long: EmaLong1;
  fast_slow_spread: FastSlowSpread;
  slow_long_spread: SlowLongSpread;
  distance_from_fast: DistanceFromFast;
  distance_from_slow: DistanceFromSlow;
  distance_from_long: DistanceFromLong;
}
export interface FeatureGroupMomentumFeatures {
  state: Readiness;
  reasons: Reasons5;
  required_samples: RequiredSamples3;
  available_samples: AvailableSamples3;
  values: MomentumFeatures | null;
}
export interface MomentumFeatures {
  rsi: Rsi;
  roc_percent: RocPercent;
  close_change: CloseChange;
}
export interface FeatureGroupVolatilityFeatures {
  state: Readiness;
  reasons: Reasons6;
  required_samples: RequiredSamples4;
  available_samples: AvailableSamples4;
  values: VolatilityFeatures | null;
}
export interface VolatilityFeatures {
  true_range: TrueRange;
  atr: Atr;
  normalized_atr: NormalizedAtr;
  atr_percent: AtrPercent;
  realized_volatility: RealizedVolatility;
}
export interface FeatureGroupVolumeFeatures {
  state: Readiness;
  reasons: Reasons7;
  required_samples: RequiredSamples5;
  available_samples: AvailableSamples5;
  values: VolumeFeatures | null;
}
export interface VolumeFeatures {
  rolling_vwap: RollingVwap;
  relative_volume: RelativeVolume;
  taker_buy_ratio: TakerBuyRatio;
  taker_base_volume_delta_proxy: TakerBaseVolumeDeltaProxy;
}
export interface FeatureGroupMicrostructureFeatures {
  state: Readiness;
  reasons: Reasons8;
  required_samples: RequiredSamples6;
  available_samples: AvailableSamples6;
  values: MicrostructureFeatures | null;
}
export interface MicrostructureFeatures {
  bid: Bid;
  ask: Ask;
  midpoint: Midpoint;
  spread: Spread;
  spread_bps: SpreadBps;
  bid_quantity: BidQuantity1;
  ask_quantity: AskQuantity1;
  top_of_book_imbalance: TopOfBookImbalance;
}
export interface FeatureGroupMarkFundingFeatures {
  state: Readiness;
  reasons: Reasons9;
  required_samples: RequiredSamples7;
  available_samples: AvailableSamples7;
  values: MarkFundingFeatures | null;
}
export interface MarkFundingFeatures {
  mark_price: MarkPrice1;
  index_price: IndexPrice1;
  basis: Basis;
  basis_percent: BasisPercent;
  basis_bps: BasisBps;
  funding_rate: FundingRate1;
  next_funding_time: NextFundingTime1;
  seconds_until_funding: SecondsUntilFunding;
}
export interface FeatureGroupRegimeFeatures {
  state: Readiness;
  reasons: Reasons10;
  required_samples: RequiredSamples8;
  available_samples: AvailableSamples8;
  values: RegimeFeatures | null;
}
export interface RegimeFeatures {
  normalized_atr: NormalizedAtr1;
  normalized_ema_separation: NormalizedEmaSeparation;
  directional_efficiency: DirectionalEfficiency;
  relative_volume: RelativeVolume1;
}
export interface StrategySnapshot {
  symbol: Symbol10;
  generated_at: GeneratedAt1;
  source_feature_timestamp: SourceFeatureTimestamp;
  snapshot_id: SnapshotId;
  observation_id: ObservationId;
  settings_id: SettingsId;
  engine_version: EngineVersion1;
  assessments: Assessments;
  readiness: StrategyReadiness;
  direction: StrategyDirection;
  composite_score: CompositeScore;
  confidence: Confidence1;
  agreement: Agreement;
  reasons: Reasons12;
  candidate: StrategyCandidate | null;
}
export interface StrategyAssessment {
  strategy_id: StrategyId;
  symbol: Symbol11;
  generated_at: GeneratedAt2;
  source_feature_timestamp: SourceFeatureTimestamp1;
  snapshot_id: SnapshotId1;
  direction: StrategyDirection;
  score: Score;
  confidence: Confidence;
  readiness: StrategyReadiness;
  reasons: Reasons11;
  required_feature_groups: RequiredFeatureGroups;
  optional_feature_groups: OptionalFeatureGroups;
  evidence: Evidence;
}
export interface StrategyEvidence {
  name: Name;
  value: Value1;
  reference: Reference;
  normalized: Normalized;
  weight: Weight;
  multiplier: Multiplier;
  contribution: Contribution;
  code: Code;
}
export interface StrategyCandidate {
  candidate_id: CandidateId;
  symbol: Symbol12;
  generated_at: GeneratedAt3;
  snapshot_id: SnapshotId2;
  observation_id: ObservationId1;
  direction: StrategyDirection;
  composite_score: CompositeScore1;
  confidence: Confidence2;
  contributing_strategies: ContributingStrategies;
  reasons: Reasons13;
}
export interface PortfolioDecisionRecord {
  portfolio_decision_id: PortfolioDecisionId;
  upstream: DecisionRecord;
  policy_id: PolicyId2;
  state_id: StateId;
  evaluated_at: EvaluatedAt;
  action: PortfolioAction;
  reason: PortfolioReason;
  desired_notional: DesiredNotional;
  reservation_id: ReservationId1;
}
export interface DecisionRecord {
  decision_id: DecisionId1;
  symbol: Symbol13;
  generated_at: GeneratedAt4;
  source_strategy_timestamp: SourceStrategyTimestamp;
  source_feature_timestamp: SourceFeatureTimestamp2;
  strategy_snapshot_id: StrategySnapshotId;
  observation_id: ObservationId2;
  strategy_settings_id: StrategySettingsId;
  strategy_engine_version: StrategyEngineVersion;
  candidate_id: CandidateId1;
  direction: StrategyDirection;
  outcome: DecisionOutcome;
  readiness: DecisionReadiness;
  composite_score: CompositeScore2;
  confidence: Confidence3;
  agreement: Agreement1;
  contributing_strategies: ContributingStrategies1;
  incomplete_strategy_coverage: IncompleteStrategyCoverage;
  reasons: Reasons14;
  policy_id: PolicyId1;
  engine_version: EngineVersion2;
}
export interface DecisionReason {
  code: DecisionReasonCode;
  observed: Observed;
  threshold: Threshold;
}
export interface LivePaperEvent {
  event_id: EventId;
  timestamp: Timestamp1;
  category: Category;
  severity: Severity;
  symbol: Symbol14;
  reason: Reason5;
  explanation: Explanation;
  related_id: RelatedId;
}
export interface PaperPortfolioCurvePoint {
  state: PaperPortfolioState;
  cumulative_closed_pnl: PaperPnl;
  open_count_before_exits: OpenCountBeforeExits;
}
