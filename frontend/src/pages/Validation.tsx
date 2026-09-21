import { useState } from "react";
import { Card, Empty, Table } from "../components/Common";
import { Label } from "../help/Help";
import { useValidation, type ValidationTelemetry } from "../hooks/useValidation";
import { number, percent, time, words } from "../utils/format";

export function Validation({ advanced }: { advanced: boolean }) {
  return <ValidationView advanced={advanced} telemetry={useValidation()} />;
}

export function ValidationView({ advanced, telemetry }: { advanced: boolean; telemetry: ValidationTelemetry }) {
  const [scope, setScope] = useState("aggregate");
  const report = telemetry.data?.report;
  const selectedWindow = report?.windows.find(w => w.result_id === scope);
  const analysis = selectedWindow ? selectedWindow.analysis : report?.aggregate;
  return <>
    <Card title="Research Validation Lab" help="walk_forward">
      <p><strong>PAPER / VIRTUAL ONLY</strong> · Historical validation is not a prediction.</p>
      <p>Fixed rules are replayed through later test windows using only evidence available at each decision.
        Confidence describes evidence quality, not probability of profit. Historical hit rate is not a future probability.</p>
      {telemetry.state === "loading" && <Empty>Loading exported validation evidence…</Empty>}
      {telemetry.state === "unavailable" && <Empty>Validation backend unavailable. Retrying automatically; no previous report is shown as current.</Empty>}
      {telemetry.state === "connected" && !report && <Empty>
        {telemetry.data?.status.state === "INVALID" ? "The configured report could not be validated." : "No validated offline report is available."}
        {" "}Reports are prepared offline and loaded at backend startup. This page only reads evidence.
      </Empty>}
      {report && <>
        <p>{report.total_bars} observed bars · {report.windows.length} chronological windows · {report.protocol.mode.toLowerCase()} context.</p>
        <p>{report.missing_bar_count} missing bars · {report.duplicate_count} identical duplicates diagnosed.</p>
        <div><Label name="dataset_identity" /> <code>{report.dataset_id}</code></div>
        <p>Dataset period: {time(report.dataset_start)} through {time(report.dataset_end)}.</p>
        {!!report.warnings.length && <div className="notice" role="status">{report.warnings.map(words).join(" · ")}</div>}
        <label>Displayed evidence scope <select value={selectedWindow ? scope : "aggregate"} onChange={event => setScope(event.target.value)}>
          <option value="aggregate">Disjoint test aggregate{!report.aggregate ? " (withheld)" : ""}</option>
          {report.windows.map(w => <option key={w.result_id} value={w.result_id}>Window {w.ordinal + 1} · {words(w.status)}</option>)}
        </select></label>
        {!analysis && <Empty>No pooled evidence for this scope. Overlapping tests retain separate window results; rejected windows have no fabricated metrics.</Empty>}
      </>}
    </Card>
    {report && <Card title="Chronology and observed coverage" help="out_of_sample">
      <p>Context warms indicators and is excluded from test counts. Missing observations are never filled.</p>
      <Table headers={["Symbol", "Observed / expected bars", "Coverage", "Missing"]}>
        {report.coverage.map(c => <tr key={c.symbol}><td>{c.symbol}</td><td>{c.observed_bars} / {c.expected_bars}</td><td>{percent(c.coverage_fraction)}</td><td>{c.missing_bars}</td></tr>)}
      </Table>
      <Table headers={["Window", "Test period", "Decisions", "Completed / incomplete", "State"]}>
        {report.windows.map(w => <tr key={w.result_id}><td>{w.ordinal + 1}</td><td>{time(w.test_start)} → {time(w.test_end)}</td>
          <td>{w.analysis?.metrics.evaluated_decision_count ?? "Not evaluated"}</td>
          <td>{w.analysis ? `${w.analysis.metrics.completed_count} / ${w.analysis.metrics.incomplete_count}` : "Unknown"}</td>
          <td>{words(w.status)}{w.warnings.length ? ` · ${w.warnings.map(words).join(", ")}` : ""}</td></tr>)}
      </Table>
    </Card>}
    {analysis && <>
      <Card title="Test sample and historical outcomes" help="sample_size">
        <p>{analysis.metrics.evaluated_decision_count} test decisions: {analysis.metrics.eligible_count} eligible,
          {" "}{analysis.metrics.blocked_count} blocked, {analysis.metrics.no_action_count} no action.</p>
        <p>{analysis.metrics.completed_count} completed · {analysis.metrics.incomplete_count} incomplete · {analysis.metrics.boundary_censored_count} window-censored.</p>
        <div><Label name="historical_hit_rate" /> {percent(analysis.metrics.win_rate)} from {analysis.metrics.win_count} wins and {analysis.metrics.loss_count} losses;
          {" "}{analysis.metrics.flat_count} flats excluded.</div>
        <p>Mean net return: {percent(analysis.metrics.mean_net_return)}. Normalized signal drawdown: {percent(analysis.metrics.normalized_max_drawdown)}.</p>
        <p>These are independent signal returns and an additive normalized curve, not portfolio equity.</p>
      </Card>
      <Card title="Symbol and causal regime groups" help="causal_regime">
        <p>Labels use fixed EMA-separation/efficiency and trailing ATR/close thresholds. Groups with fewer than 30 completed outcomes are small samples, including empty groups.</p>
        <Table headers={["Partition / group", "Decisions / eligible", "Completed / incomplete", "Historical hit rate", "Mean net", "Evidence confidence", "Warnings"]}>
          {analysis.groups.map(g => <tr key={`${g.dimension}-${g.key}`}><td>{g.dimension} / {g.key}</td>
            <td>{g.metrics.evaluated_decision_count} / {g.metrics.eligible_count}</td><td>{g.metrics.completed_count} / {g.metrics.incomplete_count}</td>
            <td>{percent(g.metrics.win_rate)}</td><td>{percent(g.metrics.mean_net_return)}</td>
            <td>{number(g.confidence.mean)} (n={g.confidence.count})</td><td>{g.warnings.map(words).join(" · ") || "None"}</td></tr>)}
        </Table>
      </Card>
      <Card title="Fixed cost sensitivity" help="cost_sensitivity">
        <p>Identical decisions and raw entry/exit evidence. Only per-side fee and adverse slippage assumptions vary. Listed by assumptions; no best scenario is selected.</p>
        <Table headers={["Fee / slippage bps per side", "Completed / incomplete", "Sum gross", "Sum costs", "Sum net", "Sign changes vs baseline"]}>
          {analysis.costs.map(c => <tr key={c.scenario_id}><td>{number(c.assumptions.fee_bps_per_side)} / {number(c.assumptions.slippage_bps_per_side)}{c.is_baseline ? " · baseline" : ""}</td>
            <td>{c.metrics.completed_count} / {c.metrics.incomplete_count}</td><td>{percent(c.metrics.sum_gross_returns)}</td>
            <td>{percent(c.metrics.sum_simulated_costs)}</td><td>{percent(c.metrics.sum_net_returns)}</td><td>{c.sign_changed_count}</td></tr>)}
        </Table>
      </Card>
    </>}
    {report && advanced && <Card title="Validation provenance and fixed definitions" help="dataset_identity">
      <p>Report <code>{report.report_id}</code></p><p>Content checksum <code>{report.content_checksum}</code></p>
      <p>Protocol <code>{report.protocol_id}</code></p><p>Regime definition <code>{report.regime_definition_id}</code></p>
      <pre>{JSON.stringify({ protocol: report.protocol, engines: report.engines, regime: report.regime_definition }, null, 2)}</pre>
      {report.windows.map(w => <details key={w.result_id}><summary>Window {w.ordinal + 1} boundaries, warm-up and IDs</summary>
        <pre>{JSON.stringify({ split_id: w.split_id, result_id: w.result_id, context_start: w.context_start, context_end: w.context_end,
          test_start: w.test_start, test_end: w.test_end, required_warmup: w.required_warmup, context_boundaries: w.context_boundary_count,
          test_boundaries: w.test_boundary_count, observed_test_boundaries: w.observed_test_boundaries, coverage: w.test_coverage }, null, 2)}</pre></details>)}
      {analysis && <details><summary>Exact cost assumptions and score/confidence summaries</summary><pre>{JSON.stringify({ costs: analysis.costs, groups: analysis.groups }, null, 2)}</pre></details>}
      <ul>{report.limitations.map(item => <li key={item}>{item}</li>)}</ul>
    </Card>}
    <Card title="Reading validation evidence" help="walk_forward">
      <div><Label name="context_window" /> · <Label name="out_of_sample" /> · <Label name="data_leakage" /></div>
      <div><Label name="causal_regime" /> · <Label name="cost_sensitivity" /> · <Label name="sample_size" /></div>
      <div><Label name="incomplete_outcome" /> · <Label name="historical_hit_rate" /> · <Label name="dataset_identity" /></div>
    </Card>
  </>;
}
