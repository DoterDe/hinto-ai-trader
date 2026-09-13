export function numeric(value: unknown): number | null {
  if (
    (typeof value !== "string" && typeof value !== "number") ||
    (typeof value === "string" && !value.trim())
  )
    return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
export function number(value: unknown, digits = 2): string {
  const n = numeric(value);
  if (n === null) return "Unknown";
  if (Math.abs(n) >= 1e12 || (n !== 0 && Math.abs(n) < 10 ** -digits))
    return n.toExponential(3);
  return n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}
export function percent(value: unknown): string {
  const n = numeric(value);
  return n === null || !Number.isFinite(n * 100)
    ? "Unknown"
    : `${number(n * 100)}%`;
}
export function time(value?: string | null): string {
  if (!value || !Number.isFinite(Date.parse(value))) return "Unknown";
  return new Date(value)
    .toISOString()
    .replace("T", " ")
    .replace(".000Z", " UTC")
    .replace("Z", " UTC");
}
export function words(value?: string | null): string {
  return value ? value.replaceAll("_", " ").toLowerCase() : "Unknown";
}
