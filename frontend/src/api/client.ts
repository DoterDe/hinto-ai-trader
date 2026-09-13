import Ajv from "ajv/dist/2020";
import addFormats from "ajv-formats";
import schema from "./dashboard.schema.json";
import type { Snapshot } from "../types";

const ajv = new Ajv({ strict: false, allErrors: false });
addFormats(ajv);
const validate = ajv.compile<Snapshot>(schema);

export function parseSnapshot(value: unknown): Snapshot {
  if (!validate(value))
    throw new Error(
      "Dashboard response does not match the supported contract.",
    );
  return value;
}

export const API_BASE = "/api";
export const REQUEST_TIMEOUT_MS = 5000;

export async function getSnapshot(signal: AbortSignal): Promise<Snapshot> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  const timer = setTimeout(abort, REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}/paper/snapshot?limit=100`, {
      method: "GET",
      credentials: "omit",
      cache: "no-store",
      signal: controller.signal,
      headers: { Accept: "application/json" },
    });
    if (!response.ok)
      throw new Error(
        "Backend unavailable. The dashboard will retry automatically.",
      );
    return parseSnapshot(await response.json());
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
}
