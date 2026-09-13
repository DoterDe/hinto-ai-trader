import { useState } from "react";
import { Badge, Card, Empty, Metric, Table } from "../components/Common";
import { FeatureDetails } from "../components/FeatureDetails";
import { Label } from "../help/Help";
import { number, time, words } from "../utils/format";
import { latestPrice, publicContext } from "../utils/market";
import type { Snapshot } from "../types";

export function MarketPage({
  data,
  advanced,
}: {
  data: Snapshot;
  advanced: boolean;
}) {
  const [symbol, setSymbol] = useState(data.market[0]?.symbol);
  const selected =
    data.market.find((item) => item.symbol === symbol) ?? data.market[0];
  const features = selected?.captured_analysis?.features;
  if (!selected) return <Empty>No configured symbols.</Empty>;
  const context = publicContext(selected);
  return (
    <>
      <Card title="Public market observations" help="market_data">
        <Table
          headers={[
            "Symbol",
            "Observed price",
            <Label name="stale" text="Price freshness" />,
            <Label name="ema" text="Trend" />,
            <Label name="rsi" />,
            <Label name="atr" />,
            "Captured features",
          ]}
        >
          {data.market.map((item) => {
            const price = latestPrice(item),
              f = item.captured_analysis?.features;
            return (
              <tr key={item.symbol}>
                <td>
                  <button
                    className="text-button"
                    onClick={() => setSymbol(item.symbol)}
                    aria-pressed={item.symbol === selected.symbol}
                  >
                    {item.symbol}
                  </button>
                </td>
                <td>{number(price.value)}</td>
                <td>
                  <Badge
                    value={
                      price.stream?.stale === false
                        ? "FRESH"
                        : "STALE / MISSING"
                    }
                  />
                </td>
                <td>
                  {f?.trend.values
                    ? `EMA ${number(f.trend.values.ema_fast)}`
                    : "Unknown"}
                </td>
                <td>{number(f?.momentum.values?.rsi)}</td>
                <td>{number(f?.volatility.values?.atr)}</td>
                <td>
                  <Badge value={f?.state} />
                </td>
              </tr>
            );
          })}
        </Table>
        <p className="footnote">
          Prices are current public observations. Indicator columns are captured
          at each symbol’s last admitted closed bar. Their timestamps can
          differ.
        </p>
      </Card>
      <div className="section-heading">
        <h2>{selected.symbol} · market detail</h2>
        <span className="footnote">
          Current feed sample {time(selected.as_of)}
        </span>
      </div>
      <div className="metrics">
        <Metric
          name="spread"
          title="Public bid / ask"
          value={`${number(selected.book_ticker?.bid_price)} / ${number(selected.book_ticker?.ask_price)}`}
          note={
            <Badge
              value={
                selected.streams.book_ticker?.stale === false
                  ? "FRESH"
                  : "STALE / MISSING"
              }
            />
          }
        />
        <Metric
          name="spread"
          value={number(context.spread)}
          note="best-known ask minus bid"
        />
        <Metric
          name="basis"
          value={number(context.basis)}
          note={`Mark ${number(selected.mark_price?.mark_price)} / Index ${number(selected.mark_price?.index_price)}`}
        />
        <Metric
          name="funding"
          value={number(selected.mark_price?.funding_rate, 6)}
          note={
            <Badge
              value={
                selected.streams.mark_price?.stale === false
                  ? "FRESH"
                  : "STALE / MISSING"
              }
            />
          }
        />
      </div>
      <Card title="Captured closed-bar measurements" help="closed_view">
        <p>
          Observation: {time(selected.captured_analysis?.boundary)}. Indicators
          measure past behavior; an extreme reading does not guarantee a
          reversal or continuation.
        </p>
        <div className="metrics compact">
          <Metric
            name="ema"
            title="EMA fast / slow / long"
            value={`${number(features?.trend.values?.ema_fast)} / ${number(features?.trend.values?.ema_slow)} / ${number(features?.trend.values?.ema_long)}`}
          />
          <Metric name="rsi" value={number(features?.momentum.values?.rsi)} />
          <Metric
            name="vwap"
            value={number(features?.volume.values?.rolling_vwap)}
          />
          <Metric
            name="volatility"
            value={number(features?.volatility.values?.realized_volatility, 6)}
          />
        </div>
        <p>
          {features
            ? `${features.closed_candles} consecutive candles retained. Feature readiness: ${words(features.state)}.`
            : "No captured measurements yet. Warm-up starts with finalized public candles."}
        </p>
        {advanced && selected.captured_analysis && (
          <FeatureDetails analysis={selected.captured_analysis} />
        )}
      </Card>
      <Card title="Public stream freshness" help="stale">
        <Table
          headers={[
            "Stream",
            "Status",
            "Reason",
            "Source age (s)",
            "Receipt age (s)",
            ...(advanced ? [<Label name="connection_generation" />] : []),
          ]}
        >
          {Object.entries(selected.streams).map(([key, stream]) => (
            <tr key={key}>
              <td>{key}</td>
              <td>
                <Badge value={stream.stale ? "STALE / MISSING" : "FRESH"} />
              </td>
              <td>
                {stream.reason
                  ? words(stream.reason)
                  : "within freshness limit"}
              </td>
              <td>{number(stream.event_age_seconds, 1)}</td>
              <td>{number(stream.receive_age_seconds, 1)}</td>
              {advanced && (
                <td>
                  {stream.connection_id ?? "Unknown"} /{" "}
                  {stream.generation ?? "Unknown"}
                </td>
              )}
            </tr>
          ))}
        </Table>
      </Card>
    </>
  );
}
