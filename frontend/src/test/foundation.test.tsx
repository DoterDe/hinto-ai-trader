import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { Dashboard } from "../layouts/Dashboard";
import { getSnapshot, parseSnapshot, REQUEST_TIMEOUT_MS } from "../api/client";
import { number, numeric, percent, time } from "../utils/format";
import { Help, terms } from "../help/Help";
import ready from "./fixtures/running.json";
import disabled from "./fixtures/disabled.json";
import incomplete from "./fixtures/incomplete.json";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("backend contract", () => {
  it.each([ready, disabled, incomplete])(
    "accepts actual offline runtime exports",
    (data) => {
      expect(parseSnapshot(data)).toBe(data);
    },
  );
  it.each([
    null,
    {},
    { ...ready, mode: "live" },
    { ...ready, mode: undefined },
    { ...ready, status: { ...ready.status, status: undefined } },
    {
      ...ready,
      market: [
        {
          ...ready.market[0],
          candle: { ...ready.market[0].candle, event_type: undefined },
        },
      ],
    },
    {
      ...ready,
      portfolio: {
        ...ready.portfolio,
        state: { ...ready.portfolio.state, marked_equity: "Infinity" },
      },
    },
    {
      ...ready,
      portfolio: {
        ...ready.portfolio,
        state: { ...ready.portfolio.state, marked_equity: "-Infinity" },
      },
    },
    {
      ...ready,
      portfolio: {
        ...ready.portfolio,
        state: { ...ready.portfolio.state, marked_equity: "NaN" },
      },
    },
  ])("rejects malformed payloads", (data) => {
    expect(() => parseSnapshot(data)).toThrow("contract");
  });
  it("preserves decimal strings and nulls", () => {
    const payload = parseSnapshot(incomplete);
    expect(payload.portfolio.state.marked_equity).toBeNull();
    expect(typeof payload.portfolio.state.realized_equity).toBe("string");
  });
  it("fetches GET only without credentials", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(ready)));
    vi.stubGlobal("fetch", fetch);
    await getSnapshot(new AbortController().signal);
    expect(fetch).toHaveBeenCalledWith(
      "/api/paper/snapshot?limit=100",
      expect.objectContaining({ method: "GET", credentials: "omit" }),
    );
  });
  it("does not expose server exception bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("PRIVATE_TRACE", { status: 500 })),
    );
    await expect(getSnapshot(new AbortController().signal)).rejects.toThrow(
      "Backend unavailable",
    );
  });
  it("aborts timed out fetches", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url, options) =>
          new Promise((_, reject) =>
            options.signal.addEventListener("abort", () =>
              reject(new Error("aborted")),
            ),
          ),
      ),
    );
    const pending = expect(
      getSnapshot(new AbortController().signal),
    ).rejects.toThrow("aborted");
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);
    await pending;
  });
});

describe("safe presentation", () => {
  it("shows loading without inventing market or portfolio data", () => {
    render(<Dashboard telemetry={{ connection: "loading" }} />);
    expect(screen.getByText(/Loading public-data telemetry/)).toBeVisible();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
  it("shows an explicitly disabled runtime", () => {
    render(
      <Dashboard
        telemetry={{ data: parseSnapshot(disabled), connection: "connected" }}
      />,
    );
    expect(screen.getAllByText("DISABLED").length).toBeGreaterThan(0);
    expect(screen.getByText("Backend connected")).toBeVisible();
    expect(screen.queryByText("RUNNING")).not.toBeInTheDocument();
  });
  it.each([null, undefined, "", "NaN", Infinity, "1e999", false])(
    "keeps absent/nonfinite values Unknown",
    (value) => {
      expect(number(value)).toBe("Unknown");
      expect(percent(value)).toBe("Unknown");
      expect(numeric(value)).toBeNull();
    },
  );
  it("preserves a known zero and formats UTC", () => {
    expect(number("0")).toBe("0.00");
    expect(percent(".1")).toBe("10.00%");
    expect(time("2020-01-01T00:00:00Z")).toContain("UTC");
    expect(time("bad")).toBe("Unknown");
    expect(percent("1e308")).toBe("Unknown");
  });
  it("renders the overview from actual backend data", () => {
    render(
      <Dashboard
        telemetry={{ data: parseSnapshot(ready), connection: "connected" }}
      />,
    );
    expect(screen.getByRole("heading", { name: "Overview" })).toBeVisible();
    expect(
      screen.getByText(/PAPER \/ VIRTUAL ONLY/, { selector: ".mode-badge" }),
    ).toBeVisible();
    expect(screen.getByText("RUNNING")).toBeVisible();
    expect(screen.getByRole("img", { name: /Virtual equity/ })).toBeVisible();
    expect(screen.getByText("Backend connected")).toBeVisible();
  });
  it("shows Unknown and an explicit incomplete valuation", () => {
    render(
      <Dashboard
        telemetry={{ data: parseSnapshot(incomplete), connection: "connected" }}
      />,
    );
    expect(screen.getAllByText("Unknown").length).toBeGreaterThan(0);
    expect(screen.getByRole("alert")).toHaveTextContent("Unknown valuation");
  });
  it("shows stale and degraded state in text", () => {
    const data = structuredClone(parseSnapshot(ready));
    data.status.status = "DEGRADED";
    data.status.reasons = ["market_feed_stale"];
    render(
      <Dashboard
        telemetry={{ data: parseSnapshot(data), connection: "connected" }}
      />,
    );
    expect(screen.getAllByText(/DEGRADED/).length).toBeGreaterThan(0);
    expect(screen.getByText(/market feed stale/)).toBeVisible();
  });
  it("Simple / Advanced changes local presentation only", () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    render(
      <Dashboard
        telemetry={{ data: parseSnapshot(ready), connection: "connected" }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /System \/ Settings/ }));
    expect(
      screen.queryByRole("heading", { name: /Configuration identities/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect(
      screen.getByRole("heading", { name: /Configuration identities/ }),
    ).toBeVisible();
    expect(localStorage.getItem("hinto.view")).toBe("advanced");
    expect(fetch).not.toHaveBeenCalled();
  });
  it("keeps Guide and glossary usable offline", () => {
    render(<Dashboard telemetry={{ connection: "unavailable" }} />);
    fireEvent.click(
      screen.getByRole("button", { name: /Guide \/ How It Works/ }),
    );
    expect(
      screen.getByRole("heading", { name: "Observe. Explain. Simulate." }),
    ).toBeVisible();
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "confidence" },
    });
    expect(screen.getByText(/not probability of profit; 0.72/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /DecisionEngine/ }));
    expect(
      screen.getByText("ELIGIBLE, BLOCKED or NO_ACTION with reasons."),
    ).toBeVisible();
  });
  it("help is keyboard reachable and warns about profit probability", () => {
    render(<Help name="confidence" />);
    const help = screen.getByLabelText("About Evidence confidence");
    fireEvent.click(help);
    expect(screen.getByText(/not probability of profit/)).toBeVisible();
    expect(terms.find((t) => t.key === "limits")?.explanation).toContain(
      "confidence never scales size",
    );
  });
  it("renders unavailable backend and retries without cached equity", async () => {
    vi.useFakeTimers();
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(ready)))
      .mockRejectedValue(new Error("offline"));
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("Backend connected")).toBeVisible();
    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(screen.getByText("Backend unavailable")).toBeVisible();
    expect(screen.queryByText("RUNNING")).not.toBeInTheDocument();
    expect(
      screen.getByText(/PAPER \/ VIRTUAL ONLY/, { selector: ".mode-badge" }),
    ).toBeVisible();
  });
  it("aborts pending polling on unmount", async () => {
    let signal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((_url, options) => {
        signal = options.signal;
        return new Promise(() => {});
      }),
    );
    const view = render(<App />);
    await waitFor(() => expect(signal).toBeDefined());
    view.unmount();
    expect(signal?.aborted).toBe(true);
  });
});
