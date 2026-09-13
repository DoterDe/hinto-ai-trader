import type { LiveDashboardSnapshot } from "./generated";
export type Snapshot = LiveDashboardSnapshot;
export type Analysis = Snapshot["decisions"][number];
export type Market = Snapshot["market"][number];
export type Page =
  | "Overview"
  | "Market"
  | "Signals & Decisions"
  | "Paper Portfolio"
  | "Backtest & Validation"
  | "System / Settings"
  | "Guide / How It Works";
export const pages: Page[] = [
  "Overview",
  "Market",
  "Signals & Decisions",
  "Paper Portfolio",
  "Backtest & Validation",
  "System / Settings",
  "Guide / How It Works",
];
