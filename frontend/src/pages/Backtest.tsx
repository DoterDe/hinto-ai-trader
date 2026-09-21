import { lazy, Suspense } from "react";
import { Card, Table } from "../components/Common";
import { Label } from "../help/Help";
const Validation = lazy(() => import("./Validation").then(module => ({ default: module.Validation })));

export function Backtest({ advanced = false }: { advanced?: boolean }) {
  return (
    <>
      <Suspense fallback={<p>Loading validation view…</p>}><Validation advanced={advanced} /></Suspense>
      <div className="intro-panel">
        <span className="eyebrow">VALIDATION, NOT OPTIMIZATION</span>
        <h2>Three views of the same evidence.</h2>
        <p>
          Historical simulation does not predict future performance. This
          educational view describes the existing offline validation contracts;
          it does not display an executed report.
        </p>
      </div>
      <div className="strategy-grid">
        <Card title="Phase 6 · Signal validation" help="backtest">
          <p>
            Evaluate each eligible decision independently. The next exact bar
            open is the entry; the configured complete holding horizon supplies
            the exit. No capital competition.
          </p>
        </Card>
        <Card title="Phase 7 · Portfolio simulation" help="paper_portfolio">
          <p>
            Signals compete for shared virtual capital. Reservations count
            toward limits before entry, and missing holding bars leave valuation
            unknown.
          </p>
        </Card>
        <Card title="Phase 8 · Live public-data paper" help="closed_view">
          <p>
            Process newly observed finalized public bars. The same analytical
            engines and portfolio math feed bounded live state. A restart begins
            a fresh virtual session.
          </p>
        </Card>
      </div>
      <Card title="What a validation report measures" help="backtest">
        <Table
          headers={[
            "Report family",
            "Available measurements",
            "Interpretation",
          ]}
        >
          <tr>
            <td>Analytical decisions</td>
            <td>ELIGIBLE / BLOCKED / NO_ACTION; LONG / SHORT</td>
            <td>
              <p>How fixed rules responded to historical evidence.</p>
            </td>
          </tr>
          <tr>
            <td>Signal outcomes</td>
            <td>Completed / incomplete; win / loss / flat; expectancy</td>
            <td>
              <p>Incomplete future data never becomes a fabricated outcome.</p>
            </td>
          </tr>
          <tr>
            <td>Return and costs</td>
            <td>Gross / cost / net return; profit factor; total costs</td>
            <td>
              <p>
                Configured fees and adverse slippage are explicit simulation
                assumptions.
              </p>
            </td>
          </tr>
          <tr>
            <td>
              <Label name="drawdown" text="Curve and drawdown" />
            </td>
            <td>Normalized cumulative returns; maximum drawdown</td>
            <td>
              <p>
                Historical path dependence, not a forecast or account balance.
              </p>
            </td>
          </tr>
          <tr>
            <td>Cohorts and chronology</td>
            <td>By symbol, direction and time segment; consecutive streaks</td>
            <td>
              <p>Different market periods can produce different behavior.</p>
            </td>
          </tr>
          <tr>
            <td>Shared virtual portfolio</td>
            <td>Exposure, reservations, occupancy, realized / marked equity</td>
            <td>
              <p>
                Capacity, timing and missing prices matter even for eligible
                signals.
              </p>
            </td>
          </tr>
        </Table>
      </Card>
      <Card title="How to use this evidence responsibly" help="backtest">
        <p>
          Use the existing backend historical replay interfaces with finalized
          local public bars. Repeated inputs and fixed settings produce
          identical reports and identities. There is no optimizer, browser
          upload, report-running control or invented performance series in this
          dashboard.
        </p>
        <p>
          Keep gross returns, costs and net returns separate. Compare
          chronological segments and inspect incomplete outcomes before
          interpreting aggregate metrics.
        </p>
      </Card>
    </>
  );
}
