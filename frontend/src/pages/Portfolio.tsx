import { Card, Metric, Table } from "../components/Common";
import { Curve } from "../components/Curve";
import { Capacity } from "../components/Capacity";
import { Badge } from "../components/Common";
import { Label } from "../help/Help";
import { number, numeric, percent, time, words } from "../utils/format";
import type { Snapshot } from "../types";

export function Portfolio({
  data,
  advanced,
}: {
  data: Snapshot;
  advanced: boolean;
}) {
  const p = data.portfolio,
    state = p.state,
    config = data.status.configuration,
    positions = data.positions;
  const equity = numeric(state.marked_equity);
  return (
    <>
      <p className="unit-note">
        All amounts are virtual simulation units. Valuation at{" "}
        {time(p.valuation_as_of)}. Retained closes:{" "}
        {positions.retained_closed_count} of {positions.completed_count}{" "}
        completed in this session.
      </p>
      <div className="metrics">
        <Metric
          name="paper_portfolio"
          title="Initial virtual equity"
          value={number(p.initial_virtual_equity)}
        />
        <Metric name="realized_equity" value={number(state.realized_equity)} />
        <Metric name="marked_equity" value={number(state.marked_equity)} />
        <Metric name="peak" value={number(state.peak_equity)} />
      </div>
      <div className="metrics">
        <Metric
          name="pnl"
          title="Realized net PnL"
          value={number(p.closed_pnl.net_pnl)}
        />
        <Metric
          name="unrealized_pnl"
          value={number(state.unrealized_net_pnl)}
        />
        <Metric
          name="fees"
          title="Completed fees"
          value={number(p.closed_pnl.fee_cost)}
          note={`Outstanding entry fees ${number(p.outstanding_entry_fee_cost)}`}
        />
        <Metric
          name="slippage"
          title="Completed slippage cost"
          value={number(p.closed_pnl.slippage_cost)}
          note={`Outstanding entry slippage ${number(p.outstanding_entry_slippage_cost)}`}
        />
      </div>
      <div className="two-columns">
        <Card title="Virtual capacity & limits" help="limits">
          <Capacity
            title="Gross exposure"
            value={state.gross_exposure_fraction}
            limit={config.portfolio.max_gross_exposure_fraction}
          />
          <Capacity
            title="Open + reserved positions"
            value={state.open_count + state.reservation_count}
            limit={config.portfolio.max_open_positions}
            ratio={false}
          />
          <Capacity
            title="Drawdown"
            value={state.drawdown}
            limit={config.portfolio.max_drawdown_fraction}
          />
          <p>
            Target allocation{" "}
            {percent(config.portfolio.target_position_fraction)}. Full
            allocation or rejection; confidence does not change size.
          </p>
        </Card>
        <Card title="Per-symbol exposure" help="exposure">
          {state.exposures.map((item) => {
            const open = numeric(item.open_notional),
              reserved = numeric(item.reserved_notional);
            const total =
              open !== null && reserved !== null ? open + reserved : null;
            return (
              <div key={item.symbol}>
                <Capacity
                  title={item.symbol}
                  value={
                    equity !== null && equity > 0 && total !== null
                      ? total / equity
                      : null
                  }
                  limit={config.portfolio.max_symbol_exposure_fraction}
                />
                <small>
                  {number(item.open_notional)} open +{" "}
                  {number(item.reserved_notional)} reserved virtual units
                </small>
              </div>
            );
          })}
          <p>
            Opposing directions add to gross exposure. They never cancel each
            other.
          </p>
        </Card>
      </div>
      <Card title="Virtual marked equity" help="marked_equity">
        <Curve
          label="Virtual marked equity"
          points={data.curve.map((p) => ({
            timestamp: p.state.timestamp,
            value: p.state.marked_equity,
          }))}
        />
      </Card>
      <div className="two-columns">
        <Card title="Drawdown history" help="drawdown">
          <Curve
            label="Drawdown"
            unit="fraction"
            points={data.curve.map((p) => ({
              timestamp: p.state.timestamp,
              value: p.state.drawdown,
            }))}
          />
        </Card>
        <Card title="Gross exposure history" help="gross_exposure">
          <Curve
            label="Gross exposure"
            unit="fraction"
            points={data.curve.map((p) => ({
              timestamp: p.state.timestamp,
              value: p.state.gross_exposure_fraction,
            }))}
          />
        </Card>
      </div>
      <Card title="Virtual reservations" help="reservation">
        <Table
          empty={!positions.reservations.length}
          headers={[
            "Symbol",
            "Direction",
            <Label name="exposure" text="Virtual notional" />,
            "Decision (UTC)",
            <Label name="horizon" text="Expected entry boundary" />,
          ]}
        >
          {positions.reservations.map((item) => (
            <tr key={item.reservation_id}>
              <td>
                {item.symbol}
                {advanced && (
                  <p>
                    <code>{item.reservation_id}</code>
                  </p>
                )}
              </td>
              <td>{item.direction}</td>
              <td>{number(item.virtual_notional)}</td>
              <td>{time(item.decision_time)}</td>
              <td>{time(item.expected_entry_time)}</td>
            </tr>
          ))}
        </Table>
        <p className="footnote">
          {p.expired_reservations} reservations expired in this session. Entry
          is observed only after the next exact candle finalizes.
        </p>
      </Card>
      <Card title="Open virtual positions" help="virtual_position">
        <Table
          empty={!positions.active.length}
          headers={[
            "Symbol / direction",
            "Virtual notional",
            "Entry time / raw price",
            "Last known mark",
            <Label name="horizon" text="Bars held" />,
            <Label name="unrealized_pnl" />,
            "Status / reason",
          ]}
        >
          {positions.active.map(({ position: item, unrealized_net_pnl }) => (
            <tr key={item.position_id}>
              <td>
                {item.reservation.symbol} · {item.reservation.direction}
                {advanced && (
                  <p>
                    <code>{item.position_id}</code>
                  </p>
                )}
              </td>
              <td>{number(item.reservation.virtual_notional)}</td>
              <td>
                {time(item.entry_time)}
                <br />
                {number(item.entry_price_raw)}
              </td>
              <td>
                {number(item.last_mark_price)}
                <br />
                <small>{time(item.last_mark_time)}</small>
              </td>
              <td>
                {item.bars_held} / {item.holding_period_bars}
              </td>
              <td>{number(unrealized_net_pnl)}</td>
              <td>
                <Badge value={item.status} />
                <br />
                <small>{words(item.reason)}</small>
              </td>
            </tr>
          ))}
        </Table>
      </Card>
      <Card title="Recently completed virtual positions" help="pnl">
        <Table
          empty={!positions.closed.length}
          headers={[
            "Symbol / direction",
            "Entry → exit (UTC)",
            "Raw entry → exit",
            "Gross PnL",
            <Label name="fees" />,
            <Label name="slippage" />,
            "Net PnL",
          ]}
        >
          {positions.closed.map(({ position: item, close }) => (
            <tr key={close.close_id}>
              <td>
                {item.reservation.symbol} · {item.reservation.direction}
                {advanced && (
                  <p>
                    <code>{close.close_id}</code>
                  </p>
                )}
              </td>
              <td>
                {time(item.entry_time)}
                <br />→ {time(close.exit_time)}
              </td>
              <td>
                {number(item.entry_price_raw)} → {number(close.exit_price_raw)}
              </td>
              <td>{number(close.pnl.gross_pnl)}</td>
              <td>{number(close.pnl.fee_cost)}</td>
              <td>{number(close.pnl.slippage_cost)}</td>
              <td>{number(close.pnl.net_pnl)}</td>
            </tr>
          ))}
        </Table>
        <p className="footnote">
          Assumptions: {number(config.costs.fee_bps_per_side)} bps fees and{" "}
          {number(config.costs.slippage_bps_per_side)} bps adverse slippage per
          side. Funding is not charged.
        </p>
      </Card>
    </>
  );
}
