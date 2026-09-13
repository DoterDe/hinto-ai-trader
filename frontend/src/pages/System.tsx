import { Card, Empty } from "../components/Common";
import { number, time, words } from "../utils/format";
import type { Snapshot } from "../types";

const groups = [
  ["features", "Feature windows", "features"],
  ["strategies", "Strategy rules", "strategies"],
  ["decisions", "Decision policy", "decisions"],
  ["portfolio", "Virtual portfolio limits", "limits"],
  ["costs", "Simulation assumptions", "fees"],
  ["runtime", "Runtime and retention", "closed_view"],
] as const;

function display(value: unknown): string {
  if (value === null) return "Unknown";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function FutureModules() {
  return (
    <div className="future-grid">
      {["Exchange Account Adapter", "Real Execution", "P2P Analytics"].map(
        (name) => (
          <section className="future" key={name} aria-disabled="true">
            <span className="eyebrow">FUTURE · NOT IMPLEMENTED</span>
            <h3>{name}</h3>
            <p>
              A separate, independently reviewed architectural boundary. No
              operational controls in Phase 8.
            </p>
          </section>
        ),
      )}
    </div>
  );
}

export function System({
  data,
  advanced,
}: {
  data?: Snapshot;
  advanced: boolean;
}) {
  return (
    <>
      <Card title="Software & public feed" help="market_data">
        <dl className="rows">
          <div>
            <dt>Dashboard</dt>
            <dd>0.8.0 · React / TypeScript</dd>
          </div>
          <div>
            <dt>Runtime version</dt>
            <dd>{data?.status.engine_version ?? "Unknown"}</dd>
          </div>
          <div>
            <dt>Mode</dt>
            <dd>PAPER / VIRTUAL ONLY</dd>
          </div>
          <div>
            <dt>Public symbols</dt>
            <dd>{data?.market.map((m) => m.symbol).join(", ") ?? "Unknown"}</dd>
          </div>
          <div>
            <dt>Candle interval</dt>
            <dd>{data?.status.interval ?? "Unknown"}</dd>
          </div>
          <div>
            <dt>Started at</dt>
            <dd>{time(data?.status.started_at)}</dd>
          </div>
          <div>
            <dt>Feed freshness limit</dt>
            <dd>
              {number(data?.status.market.stale_after_seconds, 0)} seconds
            </dd>
          </div>
        </dl>
      </Card>
      <div className="two-columns">
        {groups.map(([key, title, help]) => (
          <Card key={key} title={title} help={help}>
            {data ? (
              <dl className="rows">
                {Object.entries(data.status.configuration[key]).map(
                  ([name, value]) => (
                    <div key={name}>
                      <dt>{words(name)}</dt>
                      <dd>{display(value)}</dd>
                    </div>
                  ),
                )}
              </dl>
            ) : (
              <Empty>
                Backend unavailable. Configuration has not been loaded.
              </Empty>
            )}
          </Card>
        ))}
      </div>
      {advanced && data && (
        <Card title="Configuration identities" help="identity">
          <dl className="rows">
            {Object.entries(data.status.configuration.identities).map(
              ([name, value]) => (
                <div key={name}>
                  <dt>{name}</dt>
                  <dd>
                    <code>{value}</code>
                  </dd>
                </div>
              ),
            )}
          </dl>
          <p>
            Content identities describe fixed settings, not execution approvals.
          </p>
        </Card>
      )}
      <Card title="Limits of this simulation" help="paper_portfolio">
        <p>
          Memory only: a backend restart starts a new virtual session.
          Incomplete exposure cannot be repaired by a later price. No funding
          charges, exchange fills, leverage or liquidation model. Simple /
          Advanced changes only the local display.
        </p>
      </Card>
      <FutureModules />
    </>
  );
}
