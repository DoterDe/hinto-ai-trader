import { Badge } from "./Common";
import { Label } from "../help/Help";
import { number, time, words } from "../utils/format";
import type { Analysis } from "../types";

const groups = [
  "trade",
  "returns",
  "trend",
  "momentum",
  "volatility",
  "volume",
  "microstructure",
  "mark_funding",
  "regime",
] as const;
const help: Record<(typeof groups)[number], string> = {
  trade: "market_data",
  returns: "roc",
  trend: "ema",
  momentum: "rsi",
  volatility: "volatility",
  volume: "vwap",
  microstructure: "spread",
  mark_funding: "funding",
  regime: "regime",
};

function valueText(value: unknown): string {
  if (Array.isArray(value))
    return value
      .map((v) => `${v.window} bars: ${number(v.value, 6)}`)
      .join(" · ");
  if (typeof value === "string" && value.includes("T")) return time(value);
  return number(value, 6);
}

export function FeatureDetails({ analysis }: { analysis: Analysis }) {
  const features = analysis.features;
  return (
    <details className="technical-details">
      <summary>All captured feature values and source evidence</summary>
      <p>
        Finalized candle: {time(features.closed_candle_time)} ·{" "}
        {features.closed_candles} consecutive candles ·{" "}
        {features.history_resets} continuity resets. These values describe this
        historical decision, not a newer live observation.
      </p>
      <div className="feature-groups">
        {groups.map((name) => {
          const group = features[name];
          return (
            <section key={name}>
              <h3>
                <Label name={help[name]} text={words(name)} />{" "}
                <Badge value={group.state} />
              </h3>
              <small>
                {group.available_samples} / {group.required_samples} required
                observations
              </small>
              {group.values ? (
                <dl className="rows">
                  {Object.entries(group.values).map(([key, value]) => (
                    <div key={key}>
                      <dt>{words(key)}</dt>
                      <dd title={JSON.stringify(value)}>{valueText(value)}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p>Unavailable: {group.reasons.map(words).join(", ")}.</p>
              )}
            </section>
          );
        })}
      </div>
      <h3>
        <Label name="connection_generation" text="Captured source provenance" />
      </h3>
      <dl className="rows">
        <div>
          <dt>Public source</dt>
          <dd>
            {analysis.connection_id} · generation{" "}
            {analysis.connection_generation}
          </dd>
        </div>
        <div>
          <dt>Actual publication</dt>
          <dd>{time(analysis.published_at)}</dd>
        </div>
        <div>
          <dt>Actual receipt</dt>
          <dd>{time(analysis.received_at)}</dd>
        </div>
      </dl>
      <p>
        Optional book, trade and funding context remains unavailable in the
        closed-bar analytical view. Raw depth deltas are not a reconstructed
        order book.
      </p>
    </details>
  );
}
