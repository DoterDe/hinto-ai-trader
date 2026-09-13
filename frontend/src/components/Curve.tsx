import { useId } from "react";
import { numeric, number, time } from "../utils/format";
import { Empty } from "./Common";

type Point = { timestamp: string; value: unknown };
export function Curve({
  points,
  label,
  unit = "virtual units",
}: {
  points: Point[];
  label: string;
  unit?: string;
}) {
  const id = useId();
  const values = points.map((p) => numeric(p.value));
  const known = values.filter((v): v is number => v !== null);
  if (!known.length)
    return <Empty>No known {label.toLowerCase()} values to chart.</Empty>;
  // Scale in normalized coordinates first to avoid overflow for large finite values.
  const scale = Math.max(...known.map((v) => Math.abs(v)), 1);
  const normalized = known.map((v) => v / scale);
  const min = Math.min(...normalized),
    max = Math.max(...normalized);
  const span = max - min || 1 / Math.max(scale, 1);
  const xs = points.map((p) => Date.parse(p.timestamp));
  const xmin = Math.min(...xs),
    xrange = Math.max(...xs) - xmin || 1;
  const segments: string[] = [];
  let current = "";
  values.forEach((value, i) => {
    if (value === null) {
      if (current) segments.push(current);
      current = "";
      return;
    }
    const x = 12 + (616 * (xs[i] - xmin)) / xrange;
    const y = max === min ? 88 : 158 - 140 * ((value / scale - min) / span);
    current += `${current ? " L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`;
  });
  if (current) segments.push(current);
  return (
    <figure className="curve">
      <div className="chart-range">
        <span>
          {number(Math.max(...known))} {unit}
        </span>
        <span>{number(Math.min(...known))} low</span>
      </div>
      <svg viewBox="0 0 640 180" role="img" aria-labelledby={id}>
        <title id={id}>{label}. Missing valuations break the line.</title>
        {[30, 90, 150].map((y) => (
          <line key={y} x1="12" y1={y} x2="628" y2={y} className="grid-line" />
        ))}
        {segments.map((d, i) => (
          <path key={i} d={d} className="curve-line" />
        ))}
        {known.length === 1 && (
          <circle cx="12" cy="88" r="3" className="curve-dot" />
        )}
      </svg>
      <figcaption>
        <span>{time(points[0].timestamp)}</span>
        <span>{time(points.at(-1)?.timestamp)}</span>
      </figcaption>
      {values.some((v) => v === null) && (
        <p className="caution">Unknown valuations are gaps, not zero.</p>
      )}
    </figure>
  );
}
