import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "./fixtures/validation.json";
import medium from "./fixtures/validation.medium.json";
import { getValidation, parseValidation, MAX_VALIDATION_BYTES } from "../api/validation";
import { Validation, ValidationView } from "../pages/Validation";
import { Dashboard } from "../layouts/Dashboard";

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

const empty = { status: { state: "UNAVAILABLE", reason: "NO_REPORT_CONFIGURED", report_id: null, dataset_id: null,
  mode: "PAPER / VIRTUAL / RESEARCH ONLY", read_only: true }, report: null };

describe("read-only validation contract", () => {
  it("accepts exact backend exports and empty reports", () => {
    expect(parseValidation(fixture)).toBe(fixture);
    expect(parseValidation(empty).report).toBeNull();
  });
  it.each([{}, null, { ...fixture, extra: true }, { ...fixture, report: null },
    { ...fixture, status: { ...fixture.status, mode: "live" } },
    { ...fixture, report: { ...fixture.report, total_bars: -1 } },
    { ...fixture, report: { ...fixture.report, aggregate: { ...fixture.report.aggregate,
      metrics: { ...fixture.report.aggregate.metrics, mean_net_return: "NaN" } } } },
  ])("rejects incompatible or nonfinite evidence", value => {
    expect(() => parseValidation(value)).toThrow();
  });
  it("uses GET without credentials and propagates failed requests", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture)));
    vi.stubGlobal("fetch", fetch);
    await getValidation(new AbortController().signal);
    expect(fetch).toHaveBeenCalledWith("/api/validation/latest", expect.objectContaining({ method: "GET", credentials: "omit", cache: "no-store" }));
    fetch.mockResolvedValue(new Response("unavailable", { status: 503 }));
    await expect(getValidation(new AbortController().signal)).rejects.toThrow("unavailable");
  });
  it("times out and aborts unmounted readers", async () => {
    vi.useFakeTimers();
    const signals: AbortSignal[] = [];
    vi.stubGlobal("fetch", vi.fn((_url, options) => new Promise((_resolve, reject) => {
      signals.push(options.signal);
      options.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    })));
    const pending = getValidation(new AbortController().signal);
    const rejected = expect(pending).rejects.toThrow("aborted");
    await vi.advanceTimersByTimeAsync(5000);
    await rejected;
    const view = render(<Validation advanced={false} />);
    view.unmount();
    expect(signals.every(signal => signal.aborted)).toBe(true);
  });
  it.each([true, false])("bounds declared and streamed response bytes (header=%s)", async declared => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new Uint8Array(MAX_VALIDATION_BYTES + 1), {
      headers: declared ? { "Content-Length": String(MAX_VALIDATION_BYTES + 1) } : {},
    })));
    await expect(getValidation(new AbortController().signal)).rejects.toThrow("byte budget");
  });
  it("rejects inconsistent report identities", () => {
    expect(() => parseValidation({ ...fixture, status: { ...fixture.status, report_id: "validation_report_" + "0".repeat(64) } })).toThrow("identity");
  });
});

describe("explainable Validation panel", () => {
  it("opens the lazy-loaded panel from dashboard navigation", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture)));
    vi.stubGlobal("fetch", fetch);
    render(<Dashboard telemetry={{ connection: "unavailable" }} />);
    fireEvent.click(screen.getByRole("button", { name: /Backtest & Validation/ }));
    expect(await screen.findByRole("heading", { name: /Research Validation Lab/ })).toBeVisible();
    expect(await screen.findByText(/35 test decisions/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect(screen.getByText(fixture.report.report_id)).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("renders the medium multi-symbol release projection with explicit gaps", () => {
    render(<ValidationView advanced={false} telemetry={{ state: "connected", data: parseValidation(medium) }} />);
    expect(screen.getByText(/559 observed bars/)).toBeVisible();
    expect(screen.getByText(/1 missing bars/)).toBeVisible();
    expect(screen.getByText("symbol / ETHUSDT")).toBeVisible();
    expect(screen.getAllByText(/insufficient context/).length).toBeGreaterThan(0);
  });
  it.each(["loading", "unavailable"] as const)("shows %s honestly", state => {
    render(<ValidationView advanced={false} telemetry={{ state }} />);
    expect(screen.getByText(state === "loading" ? /Loading exported/ : /Validation backend unavailable/)).toBeVisible();
  });
  it("explains no report without inventing returns or run controls", () => {
    render(<ValidationView advanced={false} telemetry={{ state: "connected", data: parseValidation(empty) }} />);
    expect(screen.getByText(/No validated offline report/)).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run|optimize|buy|sell|deposit|withdraw/i })).not.toBeInTheDocument();
  });
  it("shows small samples, incomplete signals, counts, groups and fixed costs in Simple view", () => {
    render(<ValidationView advanced={false} telemetry={{ state: "connected", data: parseValidation(fixture) }} />);
    expect(screen.getByText(/Historical validation is not a prediction/)).toBeVisible();
    expect(screen.getByText(/^Fixed rules are replayed/)).toHaveTextContent("not a future probability");
    expect(screen.getByText(/35 test decisions/)).toBeVisible();
    expect(screen.getAllByText(/small sample/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: /Fixed cost sensitivity/ })).toBeVisible();
    expect(screen.getByText("trend / UNKNOWN")).toBeVisible();
    expect(screen.queryByText(fixture.report.report_id)).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
  it("Advanced adds exact provenance without requests or financial actions", () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    render(<ValidationView advanced telemetry={{ state: "connected", data: parseValidation(fixture) }} />);
    expect(screen.getByText(fixture.report.report_id)).toBeVisible();
    expect(screen.getByText(fixture.report.content_checksum)).toBeVisible();
    const summary = screen.getByText("Window 1 boundaries, warm-up and IDs");
    fireEvent.click(summary);
    expect(within(summary.parentElement!).getByText(/"context_start"/)).toBeVisible();
    expect(fetch).not.toHaveBeenCalled();
  });
  it("scope selection changes presentation only and retains window counts", () => {
    render(<ValidationView advanced={false} telemetry={{ state: "connected", data: parseValidation(fixture) }} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: fixture.report.windows[0].result_id } });
    expect(screen.getByText(/23 test decisions/)).toBeVisible();
  });
  it("overlap withholding and rejected windows never show fabricated aggregate", () => {
    const value = structuredClone(parseValidation(fixture));
    value.report!.aggregate = null;
    render(<ValidationView advanced={false} telemetry={{ state: "connected", data: value }} />);
    expect(screen.getByText(/No pooled evidence/)).toBeVisible();
    expect(screen.queryByRole("heading", { name: /Test sample and historical outcomes/ })).not.toBeInTheDocument();
  });
  it("loads the actual GET projection and clears it after a failed refresh", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(fixture))).mockRejectedValue(new Error("offline"));
    vi.stubGlobal("fetch", fetch);
    render(<Validation advanced={false} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(screen.getByText(/35 test decisions/)).toBeVisible();
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    expect(screen.getByText(/Validation backend unavailable/)).toBeVisible();
    expect(screen.queryByText(/35 test decisions/)).not.toBeInTheDocument();
  });
});
