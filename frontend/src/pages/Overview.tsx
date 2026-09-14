import { useState } from "react";
import { Badge, Card, Empty, EventList, Metric } from "../components/Common";
import { Curve } from "../components/Curve";
import { number, percent, time, words } from "../utils/format";
import type { Snapshot } from "../types";
import { explainReason } from "../help/reasons";
import { latestPrice } from "../utils/market";
import { Persistence } from "../components/Persistence";

export function Overview({ data, advanced = false }: { data: Snapshot; advanced?: boolean }) {
  const [symbol, setSymbol] = useState(data.market[0]?.symbol ?? "");
  const selected =
    data.market.find((item) => item.symbol === symbol) ?? data.market[0];
  const state = data.portfolio.state;
  const latest = data.decisions[0];
  return (
    <>
      <Persistence state={data.status.persistence} advanced={advanced} />
      <div className="metrics">
        <Metric
          name="marked_equity"
          value={number(state.marked_equity)}
          note="virtual simulation units"
        />
        <Metric
          name="realized_equity"
          value={number(state.realized_equity)}
          note="completed positions only"
        />
        <Metric
          name="drawdown"
          value={percent(state.drawdown)}
          note={`Limit ${percent(data.status.configuration.portfolio.max_drawdown_fraction)}`}
        />
        <Metric
          name="gross_exposure"
          value={percent(state.gross_exposure_fraction)}
          note={`${number(state.gross_exposure)} open + reserved`}
        />
      </div>
      <div className="two-columns wide-left">
        <Card title="Virtual equity over time" help="marked_equity">
          <Curve
            label="Virtual equity"
            points={data.curve.map((p) => ({
              timestamp: p.state.timestamp,
              value: p.state.marked_equity,
            }))}
          />
          <p className="footnote">
            Retained history · finalized bars · valuation at{" "}
            {time(data.portfolio.valuation_as_of)}
          </p>
        </Card>
        <Card title="Public market pulse" help="market_data">
          <label className="select-label">
            Symbol
            <select
              value={selected?.symbol ?? ""}
              onChange={(e) => setSymbol(e.target.value)}
            >
              {data.market.map((m) => (
                <option key={m.symbol}>{m.symbol}</option>
              ))}
            </select>
          </label>
          <div className="hero-number">
            {number(latestPrice(selected).value)}
          </div>
          <p>
            Latest observed public price{" "}
            <Badge
              value={data.status.market.stale ? "STALE / PARTIAL" : "FRESH"}
            />
          </p>
          <dl className="rows">
            <div>
              <dt>Captured features</dt>
              <dd>
                <Badge value={selected?.captured_analysis?.features.state} />
              </dd>
            </div>
            <div>
              <dt>Captured strategies</dt>
              <dd>
                <Badge
                  value={selected?.captured_analysis?.strategy.readiness}
                />
              </dd>
            </div>
            <div>
              <dt>Last decision</dt>
              <dd>
                <Badge
                  value={
                    selected?.captured_analysis?.portfolio.upstream.outcome
                  }
                />
              </dd>
            </div>
          </dl>
        </Card>
      </div>
      <div className="metrics compact">
        <Metric
          name="virtual_position"
          title="Open virtual positions"
          value={state.open_count}
          note="includes incomplete exposure"
        />
        <Metric
          name="reservation"
          title="Active reservations"
          value={state.reservation_count}
          note="capacity already counted"
        />
        <Metric
          name="pnl"
          title="Completed net PnL"
          value={number(data.portfolio.closed_pnl.net_pnl)}
          note="after simulated fees and slippage"
        />
        <Metric
          name="warmup"
          title="Closed candles"
          value={selected?.captured_analysis?.features.closed_candles ?? 0}
          note="bounded consecutive history"
        />
      </div>
      <div className="two-columns">
        <Card title="Latest analytical decision" help="decisions">
          {latest ? (
            <>
              <div className="inline">
                <strong>{latest.portfolio.upstream.symbol}</strong>
                <Badge value={latest.portfolio.upstream.outcome} />
                <Badge value={latest.portfolio.action} />
              </div>
              <p>
                {latest.portfolio.upstream.reasons
                  .map((r) => explainReason(r.code))
                  .join(" ")}
              </p>
              <p>Virtual portfolio: {words(latest.portfolio.reason)}.</p>
              <small>{time(latest.boundary)}</small>
            </>
          ) : (
            <Empty />
          )}
        </Card>
        <Card title="Recent runtime events" help="stale">
          <EventList events={data.events} />
        </Card>
      </div>
    </>
  );
}
