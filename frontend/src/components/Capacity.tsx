import { Label } from "../help/Help";
import { numeric, number, percent } from "../utils/format";

export function Capacity({
  title,
  value,
  limit,
  ratio = true,
}: {
  title: string;
  value: unknown;
  limit: unknown;
  ratio?: boolean;
}) {
  const n = numeric(value),
    max = numeric(limit);
  const known = n !== null && max !== null && max > 0;
  const format = ratio ? percent : (value: unknown) => number(value, 0);
  return (
    <div className="capacity">
      <div>
        <Label name="limits" text={title} />
        <span>
          {format(value)} / {format(limit)}
        </span>
      </div>
      {known ? (
        <progress
          max={1}
          value={Math.max(0, Math.min(1, n / max))}
          aria-label={title}
          aria-valuetext={`${format(value)} of ${format(limit)} limit`}
        />
      ) : (
        <p>Unknown — capacity ratio cannot be valued.</p>
      )}
      {known && n >= max && (
        <small className="caution">
          At or above the configured threshold. New reservations may be blocked.
        </small>
      )}
    </div>
  );
}
