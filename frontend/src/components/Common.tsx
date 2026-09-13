import type { ReactNode } from "react";
import { Label } from "../help/Help";
import { time, words } from "../utils/format";
import type { Snapshot } from "../types";

export function Badge({ value }: { value?: string | null }) {
  const text = value ?? "UNKNOWN";
  const tone =
    /running|connected|ready|eligible|reserved|fresh/i.test(text) &&
    !/unavailable|disconnected|warming|stale/i.test(text)
      ? "good"
      : /degraded|stale|error|blocked|rejected|incomplete|unavailable/i.test(
            text,
          )
        ? "warn"
        : "neutral";
  return <span className={`badge ${tone}`}>{text.replaceAll("_", " ")}</span>;
}
export function Card({
  title,
  help,
  children,
  className = "",
}: {
  title: string;
  help: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      <h2>
        <Label name={help} text={title} />
      </h2>
      {children}
    </section>
  );
}
export function Metric({
  name,
  value,
  note,
  title,
}: {
  name: string;
  value: ReactNode;
  note?: ReactNode;
  title?: string;
}) {
  return (
    <section className="metric">
      <div className="metric-label">
        <Label name={name} text={title} />
      </div>
      <div className="metric-value">{value}</div>
      {note && <div className="metric-note">{note}</div>}
    </section>
  );
}
export function Empty({
  children = "No observations yet. Waiting for finalized public candles.",
}: {
  children?: ReactNode;
}) {
  return <p className="empty">{children}</p>;
}
export function EventList({ events }: { events: Snapshot["events"] }) {
  return events.length ? (
    <ul className="events">
      {events.slice(0, 8).map((item) => (
        <li key={item.event_id}>
          <div>
            <Badge value={item.severity} />
            <span>{item.symbol ?? "Runtime"}</span>
            <time>{time(item.timestamp)}</time>
          </div>
          <p>{item.explanation}</p>
          <small>{words(item.reason)}</small>
        </li>
      ))}
    </ul>
  ) : (
    <Empty>No runtime events recorded.</Empty>
  );
}
export function Table({
  headers,
  children,
  empty,
}: {
  headers: ReactNode[];
  children: ReactNode;
  empty?: boolean;
}) {
  return empty ? (
    <Empty>No records in the retained history.</Empty>
  ) : (
    <div
      className="table-scroll"
      tabIndex={0}
      role="region"
      aria-label="Scrollable data table"
    >
      <table>
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th key={i}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}
