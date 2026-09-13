import { useState } from "react";
import { Badge, Card, Empty, Metric, Table } from "../components/Common";
import { FeatureDetails } from "../components/FeatureDetails";
import { Label } from "../help/Help";
import { explainReason } from "../help/reasons";
import { number, time, words } from "../utils/format";
import type { Snapshot } from "../types";

export function Signals({
  data,
  advanced,
}: {
  data: Snapshot;
  advanced: boolean;
}) {
  const [selectedId, setSelectedId] = useState<string>();
  const selected =
    data.decisions.find(
      (item) => item.portfolio.upstream.decision_id === selectedId,
    ) ?? data.decisions[0];
  return (
    <>
      <Card title="Recent analytical decisions" help="decisions">
        <Table
          empty={!data.decisions.length}
          headers={[
            "Symbol / UTC",
            <Label name="decisions" text="Decision" />,
            <Label name="paper_portfolio" text="Portfolio action" />,
            "Why?",
          ]}
        >
          {data.decisions.map((item) => (
            <tr key={item.portfolio.portfolio_decision_id}>
              <td>
                <strong>{item.portfolio.upstream.symbol}</strong>
                <br />
                <small>{time(item.boundary)}</small>
              </td>
              <td>
                <Badge value={item.portfolio.upstream.outcome} />
              </td>
              <td>
                <Badge value={item.portfolio.action} />
              </td>
              <td>
                <button
                  className="text-button"
                  onClick={() =>
                    setSelectedId(item.portfolio.upstream.decision_id)
                  }
                  aria-pressed={selected === item}
                  aria-label={`Explain ${item.portfolio.upstream.symbol} at ${time(item.boundary)}`}
                >
                  Explain →
                </button>
              </td>
            </tr>
          ))}
        </Table>
      </Card>
      {selected ? (
        <>
          <div className="section-heading">
            <h2>{selected.portfolio.upstream.symbol} · explanation chain</h2>
            <small>{time(selected.boundary)}</small>
          </div>
          <div className="analysis-chain">
            <span>Closed observation</span>
            <span>Feature measurements</span>
            <span>Strategy evidence</span>
            <span>Decision</span>
            <span>Virtual policy</span>
          </div>
          <Card title="What happened, and why?" help="decisions">
            <div className="inline">
              <Badge value={selected.portfolio.upstream.outcome} />
              <span>→</span>
              <Badge value={selected.portfolio.action} />
            </div>
            <ul className="why-list">
              {selected.portfolio.upstream.reasons.map((r) => (
                <li key={r.code}>
                  {explainReason(r.code)}
                  {advanced && (
                    <small>
                      {" "}
                      {r.code} · observed {number(r.observed, 4)} / threshold{" "}
                      {number(r.threshold, 4)}
                    </small>
                  )}
                </li>
              ))}
            </ul>
            <p>
              <strong>Virtual portfolio gate:</strong>{" "}
              {explainReason(selected.portfolio.reason)}
            </p>
            <p>
              <strong>What it means:</strong>{" "}
              {selected.portfolio.action === "RESERVED"
                ? "Capacity is held for the next exact bar open. This is a virtual reservation, not an exchange order."
                : "No new virtual capacity was reserved by this observation."}
            </p>
            <p className="footnote">
              Historical decisions remain as captured even when the current feed
              later becomes stale.
            </p>
          </Card>
          <div className="metrics">
            <Metric
              name="score"
              value={number(selected.strategy.composite_score)}
              note="signed evidence, −100 to +100"
            />
            <Metric
              name="confidence"
              value={number(selected.strategy.confidence)}
              note="evidence quality, not probability of profit"
            />
            <Metric
              name="agreement"
              value={number(selected.strategy.agreement)}
              note="directional agreement, 0 to 1"
            />
            <Metric
              name="strategies"
              title="Candidate contributors"
              value={
                selected.strategy.candidate?.contributing_strategies.length ?? 0
              }
              note={
                selected.strategy.candidate?.contributing_strategies
                  .map(words)
                  .join(", ") || "No candidate"
              }
            />
          </div>
          <div className="strategy-grid">
            {selected.strategy.assessments.map((item) => (
              <Card
                key={item.strategy_id}
                title={words(item.strategy_id)}
                help={item.strategy_id}
              >
                <div className="inline">
                  <Badge value={item.readiness} />
                  <Badge value={item.direction} />
                </div>
                <p>
                  {item.reasons.map(words).join(" · ") ||
                    "No additional diagnostic reason."}
                </p>
                {advanced && (
                  <>
                    <p>
                      Score {number(item.score)} · Evidence confidence{" "}
                      {number(item.confidence)}
                    </p>
                    <details className="technical-details">
                      <summary>Weighted evidence contributions</summary>
                      <Table
                        headers={["Measurement", "Value", "Contribution"]}
                        empty={!item.evidence.length}
                      >
                        {item.evidence.map((e, i) => (
                          <tr key={`${e.name}-${i}`}>
                            <td>{words(e.name)}</td>
                            <td>{number(e.value, 5)}</td>
                            <td>{number(e.contribution, 5)}</td>
                          </tr>
                        ))}
                      </Table>
                    </details>
                  </>
                )}
              </Card>
            ))}
          </div>
          {advanced && (
            <Card title="Observation provenance" help="identity">
              <dl className="rows">
                {Object.entries({
                  decision: selected.portfolio.upstream.decision_id,
                  observation: selected.portfolio.upstream.observation_id,
                  strategy_snapshot: selected.strategy.snapshot_id,
                  decision_policy: selected.portfolio.upstream.policy_id,
                  portfolio_policy: selected.portfolio.policy_id,
                  portfolio_state: selected.portfolio.state_id,
                  reservation: selected.portfolio.reservation_id,
                }).map(([key, value]) => (
                  <div key={key}>
                    <dt>{words(key)}</dt>
                    <dd>
                      <code>{value ?? "None"}</code>
                    </dd>
                  </div>
                ))}
              </dl>
              <FeatureDetails analysis={selected} />
            </Card>
          )}
        </>
      ) : (
        <Empty>
          No captured decisions. The pipeline is waiting for finalized bars.
        </Empty>
      )}
    </>
  );
}
