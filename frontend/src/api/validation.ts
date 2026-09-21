import Ajv from "ajv/dist/2020";
import addFormats from "ajv-formats";
import schema from "./validation.schema.json";
import type { ValidationSnapshot } from "../types/validation.generated";
import { API_BASE, REQUEST_TIMEOUT_MS } from "./client";

const ajv = new Ajv({ strict: false, allErrors: false });
addFormats(ajv);
const validate = ajv.compile<ValidationSnapshot>(schema);
export const MAX_VALIDATION_BYTES = 8 * 1024 * 1024;

export function parseValidation(value: unknown): ValidationSnapshot {
  if (!validate(value)) throw new Error("Validation response does not match the supported contract.");
  if ((value.status.state === "READY") !== (value.report !== null))
    throw new Error("Validation response has inconsistent availability.");
  if (value.report && (value.report.report_id !== value.status.report_id || value.report.dataset_id !== value.status.dataset_id))
    throw new Error("Validation response has inconsistent identity.");
  return value;
}

export async function getValidation(signal: AbortSignal): Promise<ValidationSnapshot> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  const timer = setTimeout(abort, REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}/validation/latest`, {
      method: "GET", credentials: "omit", cache: "no-store", signal: controller.signal,
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error("Validation telemetry unavailable.");
    if (Number(response.headers.get("Content-Length")) > MAX_VALIDATION_BYTES || !response.body)
      throw new Error("Validation response exceeds its byte budget or has no body.");
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let length = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        length += value.byteLength;
        if (length > MAX_VALIDATION_BYTES) {
          await reader.cancel();
          throw new Error("Validation response exceeds its byte budget.");
        }
        chunks.push(value);
      }
    } finally { reader.releaseLock(); }
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return parseValidation(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)));
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
}
