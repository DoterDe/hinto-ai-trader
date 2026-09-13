import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Dashboard } from "../layouts/Dashboard";
import { Curve } from "../components/Curve";
import { parseSnapshot } from "../api/client";
import { latestPrice } from "../utils/market";
import { Help } from "../help/Help";
import { explainReason } from "../help/reasons";
import type { Page } from "../types";
import ready from "./fixtures/running.json";
import disabled from "./fixtures/disabled.json";
import incomplete from "./fixtures/incomplete.json";
import blocked from "./fixtures/blocked.json";
import { MarketPage } from "../pages/Market";

function page(name: Page, payload: unknown = ready, advanced = false) {
  render(
    <Dashboard
      telemetry={{ data: parseSnapshot(payload), connection: "connected" }}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", {
      name: new RegExp(name.replaceAll("&", "\\&")),
    }),
  );
  if (advanced)
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
}

describe("research pages", () => {
  it.each([
    ["NO_ACTION", ready],
    ["ELIGIBLE", incomplete],
    ["BLOCKED", blocked],
  ] as const)("explains the actual backend %s result", (outcome, payload) => {
    page("Signals & Decisions", payload);
    expect(
      screen.getAllByText(outcome.replaceAll("_", " ")).length,
    ).toBeGreaterThan(0);
    const reason =
      parseSnapshot(payload).decisions[0].portfolio.upstream.reasons[0];
    expect(screen.getByText(explainReason(reason.code))).toBeVisible();
  });
  it("does not label absent optional stream metadata as fresh", () => {
    const data = structuredClone(parseSnapshot(disabled));
    data.market[0].streams = {};
    page("Market", data);
    expect(screen.queryByText("FRESH")).not.toBeInTheDocument();
    expect(screen.getAllByText("STALE / MISSING")).toHaveLength(3);
  });
  it("handles a selected symbol disappearing from the next snapshot", () => {
    const data = parseSnapshot(ready);
    const view = render(<MarketPage data={data} advanced={false} />);
    expect(
      screen.getByRole("heading", { name: /BTCUSDT.*market detail/ }),
    ).toBeVisible();
    view.rerender(
      <MarketPage data={{ ...data, market: [] }} advanced={false} />,
    );
    expect(screen.getByText("No configured symbols.")).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: /BTCUSDT.*market detail/ }),
    ).not.toBeInTheDocument();
  });
  it("shows captured indicator values separately from current market observations", () => {
    page("Market", ready, true);
    expect(
      screen.getByRole("heading", { name: /Captured closed-bar measurements/ }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: /Public stream freshness/ }),
    ).toBeVisible();
    fireEvent.click(
      screen.getByText("All captured feature values and source evidence"),
    );
    expect(
      screen.getByText(
        /Optional book, trade and funding context remains unavailable/,
      ),
    ).toBeVisible();
    expect(screen.getByText("injected_public · generation 1")).toBeVisible();
  });
  it("does not prefer an older trade over a newer candle price", () => {
    const market = structuredClone(parseSnapshot(ready).market[0]);
    market.trade = {
      symbol: market.symbol,
      event_time: "2020-01-01T00:00:00Z",
      received_at: "2020-01-01T00:00:00Z",
      price: "1",
      event_type: "trade",
      aggregate_trade_id: 1,
      first_trade_id: 1,
      last_trade_id: 1,
      quantity: "1",
      trade_time: "2020-01-01T00:00:00Z",
      buyer_is_maker: false,
      normal_quantity: null,
    };
    expect(latestPrice(market).value).toBe(market.candle?.close);
  });
  it("shows decisions, portfolio gates and a Why explanation", () => {
    page("Signals & Decisions");
    expect(
      screen.getByRole("heading", { name: /What happened, and why/ }),
    ).toBeVisible();
    const record = parseSnapshot(ready).decisions[0];
    expect(
      screen.getByText(explainReason(record.portfolio.reason), {
        exact: false,
      }),
    ).toBeVisible();
    expect(
      screen.getByText("evidence quality, not probability of profit"),
    ).toBeVisible();
    expect(
      screen.getAllByRole("button", { name: /^Explain BTCUSDT at/ }),
    ).toHaveLength(ready.decisions.length);
  });
  it("shows full provenance and selected evidence in Advanced view", () => {
    page("Signals & Decisions", ready, true);
    expect(
      screen.getByRole("heading", { name: /Observation provenance/ }),
    ).toBeVisible();
    expect(
      screen.getByText(
        parseSnapshot(ready).decisions[0].portfolio.upstream.decision_id,
      ),
    ).toBeVisible();
    const rows = screen.getAllByRole("button", { name: /^Explain BTCUSDT/ });
    fireEvent.click(rows[1]);
    expect(
      screen.getByText(
        parseSnapshot(ready).decisions[1].portfolio.upstream.decision_id,
      ),
    ).toBeVisible();
  });
  it("explains incomplete virtual exposure without hiding the last historical mark", () => {
    page("Paper Portfolio", incomplete);
    expect(screen.getByText("INCOMPLETE")).toBeVisible();
    expect(screen.getByText("missing horizon bar")).toBeVisible();
    expect(screen.getAllByText("Unknown").length).toBeGreaterThan(1);
    expect(
      screen.getByRole("heading", { name: /Open virtual positions/ }),
    ).toBeVisible();
    expect(
      screen.queryByRole("progressbar", { name: "Gross exposure" }),
    ).not.toBeInTheDocument();
  });
  it("shows complete closes, costs, capacity and three charts", () => {
    page("Paper Portfolio");
    expect(
      screen.getByRole("heading", {
        name: /Recently completed virtual positions/,
      }),
    ).toBeVisible();
    expect(
      screen.getByRole("progressbar", { name: "Gross exposure" }),
    ).toBeVisible();
    expect(screen.getAllByRole("img")).toHaveLength(3);
    expect(screen.getByText(/Funding is not charged/)).toBeVisible();
  });
  it.each(["Market", "Signals & Decisions", "Paper Portfolio"] as Page[])(
    "handles empty %s data",
    (name) => {
      page(name, disabled);
      expect(screen.getByRole("heading", { level: 1, name })).toBeVisible();
      expect(
        screen.getAllByText(/Unknown|No records|No captured measurements/)
          .length,
      ).toBeGreaterThan(0);
    },
  );
  it("keeps validation educational, including when offline", () => {
    render(<Dashboard telemetry={{ connection: "unavailable" }} />);
    fireEvent.click(
      screen.getByRole("button", { name: /Backtest & Validation/ }),
    );
    expect(
      screen.getByRole("heading", {
        name: "Three views of the same evidence.",
      }),
    ).toBeVisible();
    expect(
      screen.getByText(/does not display an executed report/),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /run backtest/i }),
    ).not.toBeInTheDocument();
  });
  it.each([
    "Overview",
    "Market",
    "Signals & Decisions",
    "Paper Portfolio",
    "Backtest & Validation",
    "System / Settings",
    "Guide / How It Works",
  ] as Page[])("has no financial controls on %s", (name) => {
    page(name, ready, true);
    expect(
      screen.getByText(/PAPER \/ VIRTUAL ONLY/, { selector: ".mode-badge" }),
    ).toBeVisible();
    const forbidden =
      /^(buy|sell|place order|connect binance|enable live|deposit|withdraw|transfer|api key|api secret|leverage)/i;
    for (const control of screen.queryAllByRole("button"))
      expect(control.textContent?.trim()).not.toMatch(forbidden);
    expect(
      screen.queryByLabelText(/api key|api secret|leverage/i),
    ).not.toBeInTheDocument();
  });
  it("future modules have no operational controls", () => {
    page("System / Settings");
    const heading = screen.getByRole("heading", { name: "Real Execution" });
    expect(heading.closest("section")).toHaveAttribute("aria-disabled", "true");
    expect(
      within(heading.closest("section")!).queryByRole("button"),
    ).not.toBeInTheDocument();
  });
});

describe("accessible truthful charts and help", () => {
  it("breaks the curve at unknown valuations", () => {
    const { container } = render(
      <Curve
        label="Test equity"
        points={[
          { timestamp: "2020-01-01T00:00:00Z", value: "100" },
          { timestamp: "2020-01-01T00:01:00Z", value: null },
          { timestamp: "2020-01-01T00:02:00Z", value: "90" },
        ]}
      />,
    );
    expect(container.querySelectorAll("path")).toHaveLength(2);
    expect(
      screen.getByText("Unknown valuations are gaps, not zero."),
    ).toBeVisible();
  });
  it("does not invent chart values for empty or unknown series", () => {
    render(
      <Curve
        label="Test equity"
        points={[{ timestamp: "2020-01-01T00:00:00Z", value: null }]}
      />,
    );
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText(/No known test equity values/)).toBeVisible();
  });
  it("opens an important explanation using only the keyboard", async () => {
    const user = userEvent.setup();
    render(<Help name="drawdown" />);
    await user.tab();
    expect(screen.getByLabelText("About Drawdown")).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(
      screen.getByText(/At the limit, new reservations block/),
    ).toBeVisible();
    await user.keyboard("{Escape}");
    expect(
      screen.getByText(/At the limit, new reservations block/),
    ).not.toBeVisible();
  });
});
