# Phase 8 Dashboard UX Specification

This document defines the user-facing experience for Phase 8. It is intentionally separate from trading logic.

## Core goal

A user who did not write the backend should be able to open the application and answer:

1. Is the system running correctly?
2. What market data is currently available?
3. What did each analytical engine conclude?
4. Why did the Decision Engine return ELIGIBLE/BLOCKED/NO_ACTION?
5. Why did the paper portfolio reserve/reject/ignore that decision?
6. What virtual positions exist now?
7. What is the current simulated equity, exposure and drawdown?
8. Which values are known, stale, warming up or unavailable?
9. What does every technical term mean?

The dashboard must never imply that simulated results are guaranteed future returns.

## Global layout

Desktop-first application shell:

```text
┌─────────────────────────────────────────────────────────────────┐
│ Hinto AI Trader     PAPER / VIRTUAL ONLY     Backend ● Connected│
├──────────────┬──────────────────────────────────────────────────┤
│ Overview     │                                                  │
│ Market       │                 Current page                     │
│ Signals      │                                                  │
│ Portfolio    │                                                  │
│ Backtest     │                                                  │
│ System       │                                                  │
│ Guide        │                                                  │
│              │                                                  │
│ Future       │                                                  │
│ • Real exec  │ disabled                                        │
│ • P2P        │ disabled                                        │
└──────────────┴──────────────────────────────────────────────────┘
```

Always-visible mode badge:

`PAPER / VIRTUAL ONLY`

Hover/click explanation:

> The application is using public market information and simulated capital. It cannot place a real order or move funds in Phase 8.

## Visual status language

Use consistent badges:

- RUNNING
- WARMING UP
- DEGRADED
- STALE
- UNKNOWN
- BLOCKED
- NO ACTION
- ELIGIBLE
- RESERVED
- REJECTED
- INCOMPLETE

Do not communicate state by color alone; always include text/icon.

## Simple / Advanced view

A global local-only display preference.

### Simple

Show:

- human wording;
- key numbers only;
- short reasons;
- expandable details.

Example:

```text
BTCUSDT
Decision: No action
Why: Strategies do not agree strongly enough.
```

### Advanced

Additionally show:

- decision IDs;
- observation IDs;
- individual strategy scores;
- evidence/readiness;
- composite score;
- confidence;
- agreement;
- exact timestamps;
- policy IDs/reason enums;
- cost assumptions.

The toggle must never change backend behavior.

## Overview page

Top row:

- Runtime status
- Public feed health
- Virtual marked equity
- Drawdown
- Gross exposure
- Open paper positions

Second row:

- Equity curve
- Exposure/drawdown mini charts

Third row:

- Latest Signals & Decisions
- Recent Runtime Events

Every card has an info control.

### Equity card help

**Marked virtual equity**

Current simulated value of the paper portfolio using the latest known marks. It is not a real exchange balance. If a required market value is missing, show `Unknown` rather than `0`.

### Drawdown card help

**Drawdown**

How far current marked virtual equity is below the highest previous known value.

Formula:

`(peak equity - current marked equity) / peak equity`

A drawdown limit can block new paper reservations. It does not predict what will happen next.

### Gross exposure card help

**Gross exposure**

Total virtual notional currently open or reserved. LONG and SHORT exposure are added; they do not cancel each other in Phase 8.

## Market page

Table columns in Simple view:

- Symbol
- Price
- Freshness
- Trend
- Momentum
- Volatility
- Status

Advanced drawer adds all Phase 3 feature fields currently available.

Indicator help examples:

### EMA

An exponentially weighted moving average. Recent prices affect it more strongly than older prices. The system uses EMA relationships as one piece of trend evidence.

### RSI

A bounded momentum indicator. It describes recent price movement strength; it does not mean the market must reverse at a specific value.

### ATR

A measure of recent trading range/volatility. It describes movement size, not direction.

### VWAP

Volume-weighted average price across the configured window. The current price's distance from VWAP can provide context for trend or mean-reversion strategies.

### Spread

Difference between best known bid and ask. Wider spread can indicate worse immediate execution conditions, but Phase 8 does not place real orders.

## Signals & Decisions page

Use a vertical explanation chain:

```text
Market observation
      ↓
Feature Engine
      ↓
Trend / Momentum / Mean Reversion
      ↓
Strategy aggregate
      ↓
Decision Engine
      ↓
Paper Portfolio Policy
```

For a selected decision, show each stage as a card.

### Feature Engine

**Input:** normalized public market observations.

**Output:** numerical measurements such as returns, EMA, RSI, ATR, VWAP, spread and basis context.

**Can move money:** No.

### Strategy Engine

**Input:** FeatureSnapshot.

**Output:** independent rule-based strategy assessments and an aggregate score.

**Can move money:** No.

### Decision Engine

**Input:** StrategySnapshot/Candidate.

**Output:** ELIGIBLE, BLOCKED or NO_ACTION with explicit reasons.

**Can move money:** No.

### Portfolio Policy

**Input:** eligible decision plus current virtual portfolio state.

**Output:** RESERVED, REJECTED or IGNORED.

**Can move money:** No. Reservations are virtual capacity only.

### Confidence wording

Never display merely:

`Confidence 72%`

without nearby explanation.

Preferred:

`Evidence confidence: 0.72`

Tooltip:

> Measures the quality/completeness/agreement of analytical evidence. It is not a 72% probability of making a profit.

### Why panel

Every selected row should have a `Why?` panel containing:

- upstream reason;
- strategy contributors;
- current portfolio gate;
- plain-language summary.

## Paper Portfolio page

Sections:

### Portfolio summary

- Initial virtual equity
- Realized equity
- Marked equity
- Realized PnL
- Unrealized PnL
- Simulated costs
- Peak equity
- Drawdown

### Capacity

Progress bars for:

- gross exposure vs max;
- open+reserved positions vs max;
- per-symbol exposure vs max;
- drawdown vs blocking threshold.

Do not use progress bars as promises/risk scores; label exact values.

### Reservations table

- Symbol
- Direction
- Virtual notional
- Decision time
- Expected next-bar entry boundary
- Status

Tooltip:

> A reservation reserves virtual portfolio capacity after a decision. It is not an exchange order.

### Open virtual positions

- Symbol
- Direction
- Virtual notional
- Entry time
- Entry price
- Last known mark
- Bars held / fixed horizon
- Unrealized simulated PnL
- Status

### Closed virtual positions

- Symbol
- Direction
- Entry/exit
- Gross PnL
- Fee assumption
- Slippage assumption
- Net PnL

## Backtest & Validation page

Explain the difference:

### Phase 6 signal validation

Evaluates eligible signals independently. Useful for understanding the strategy's historical signal behavior.

### Phase 7 portfolio simulation

Lets signals compete for one shared virtual capital pool with exposure and drawdown rules.

### Phase 8 live paper runtime

Applies the same ideas as current public market observations arrive, while still using virtual capital only.

Historical performance text must include:

> Historical simulation does not predict future performance.

## System page

Show readable configuration groups:

### Market feed
- symbols
- intervals
- freshness

### Features
- history/window settings

### Strategies
- strategy weights/thresholds

### Decisions
- DecisionEngine policy

### Paper portfolio
- initial virtual equity
- target fraction
- exposure limits
- max positions
- drawdown threshold

### Simulation costs
- fee assumption
- slippage assumption
- holding horizon

### Software
- backend version
- frontend version/build
- API health
- runtime state

Configuration values in Phase 8 are primarily explanatory/read-only. Do not add financial mutation controls.

## Guide / How It Works page

Display a clickable architecture map:

```text
Public Binance Market Data
          ↓
     MarketDataHub
          ↓
     FeatureEngine
          ↓
     StrategyEngine
          ↓
     DecisionEngine
          ↓
 PaperPortfolioPolicy
          ↓
  Virtual Paper Runtime
          ↓
       Dashboard
```

Clicking each block opens:

- Purpose
- Input
- Output
- Important limitations
- Related source module path
- Related dashboard page

Also include a glossary search.

## Future roadmap area

It is useful for architecture clarity to show future modules, but they must be visibly disabled:

### Exchange Account Adapter — Future

Would isolate exchange-specific private account integration from analytical engines. Not implemented in Phase 8.

### Real Execution — Future

Would require a separately reviewed execution/risk boundary. Not implemented in Phase 8.

### P2P Analytics — Future

May later analyze public P2P market/quote information. Phase 8 contains no P2P transaction automation, transfers or payment actions.

Do not display API-key inputs, deposit/withdraw controls, buy/sell execution buttons or P2P transaction buttons.

## Error and unknown states

Never use fake values.

Examples:

- backend offline → `Backend unavailable`;
- market stale → `Stale — last update 18s ago`;
- portfolio valuation unknown → `Unknown — a required holding bar is missing`;
- no strategy candidate → `No action — no eligible aggregate candidate`;
- warming up → display progress/history context if known.

## Accessibility

Minimum expectations:

- meaningful heading hierarchy;
- keyboard navigation;
- visible focus;
- table semantics;
- accessible labels for icon buttons;
- tooltip content reachable without hover only;
- status not represented by color alone;
- readable number formatting.

## Fresh implementation rule

The public Hinto repository is a UX reference only. Implement this UI from scratch using this project's Phase 1–8 API/domain semantics. Avoid copying components, styles or large source fragments from the reference project.
