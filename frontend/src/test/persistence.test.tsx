import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Dashboard } from "../layouts/Dashboard";
import { parseSnapshot } from "../api/client";
import { Persistence } from "../components/Persistence";
import { terms } from "../help/Help";
import type { Snapshot } from "../types";
import ready from "./fixtures/running.json";
import incomplete from "./fixtures/incomplete.json";

type State = Snapshot["status"]["persistence"];
function state(status: State["status"]): State {
  return { ...parseSnapshot(ready).status.persistence, status,
    enabled: status !== "DISABLED", recovered: status === "RECOVERED",
    session_id: "session_offline_test", checkpoint_id: "checkpoint_offline_test",
    checksum: "a".repeat(64), database_healthy: ["DURABLE", "RECOVERED", "NEW_SESSION"].includes(status) };
}

describe("local paper persistence", () => {
  it.each([
    ["DISABLED", /Persistence disabled/],
    ["NEW_SESSION", /New virtual session/],
    ["RECOVERING", /Validating saved virtual state/],
    ["RECOVERED", /Waiting for new admissible public candles/],
    ["DURABLE", /Current virtual state is durable/],
    ["DEGRADED", /Further paper transitions are stopped/],
    ["INCOMPATIBLE", /saved session requires different settings/],
    ["CORRUPT", /cannot be trusted or recovered/],
    ["ERROR", /Local persistence is unavailable/],
  ] as const)("explains %s without financial controls", (status, message) => {
    render(<Persistence state={state(status)} />);
    expect(screen.getByText(message)).toBeVisible();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("session_offline_test")).not.toBeInTheDocument();
  });
  it("does not call pending changes durable", () => {
    render(<Persistence state={{ ...state("DURABLE"), has_uncommitted_changes: true }} />);
    expect(screen.getByText(/Saving new virtual state/)).toBeVisible();
    expect(screen.queryByText("Current virtual state is durable.")).not.toBeInTheDocument();
  });
  it("exposes identities and checksum only in Advanced", () => {
    const data = structuredClone(parseSnapshot(ready));
    data.status.persistence = state("DURABLE");
    render(<Dashboard telemetry={{ connection: "connected", data }} />);
    expect(screen.queryByText("session_offline_test")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect(screen.getByText("session_offline_test")).toBeVisible();
    expect(screen.getByText("a".repeat(64))).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /System \/ Settings/ }));
    expect(screen.getByText("checkpoint_offline_test")).toBeVisible();
    expect(screen.getByText("PAPER / VIRTUAL ONLY", { selector: "dd" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Simple" }));
    expect(screen.queryByText("session_offline_test")).not.toBeInTheDocument();
  });
  it("keeps incomplete valuation unknown after recovery", () => {
    const data = structuredClone(parseSnapshot(incomplete));
    data.status.persistence = state("RECOVERED");
    render(<Dashboard telemetry={{ connection: "connected", data }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Unknown valuation");
    expect(screen.getByText(/Missing candles during downtime/)).toBeVisible();
    expect(data.portfolio.state.marked_equity).toBeNull();
  });
  it("has all seven new help terms and searchable recovery guidance", () => {
    for (const key of ["persistence", "checkpoint", "recovery", "durable_boundary", "session_id", "crash_consistency", "configuration_compatibility"])
      expect(terms.find(t => t.key === key)?.explanation).toBeTruthy();
    render(<Dashboard telemetry={{ connection: "connected", data: parseSnapshot(ready) }} />);
    fireEvent.click(screen.getByRole("button", { name: /Guide \/ How It Works/ }));
    expect(screen.getByText(/An unfinished candle group is not saved/)).toBeVisible();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Crash consistency" } });
    expect(screen.getByRole("heading", { name: "Crash consistency" })).toBeVisible();
  });
  it.each(["status", "database_healthy", "has_uncommitted_changes", "schema_version"])("requires persistence field %s in server contract", key => {
    const data = structuredClone(ready);
    delete (data.status.persistence as Record<string, unknown>)[key];
    expect(() => parseSnapshot(data)).toThrow("contract");
  });
});
