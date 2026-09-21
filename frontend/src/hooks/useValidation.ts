import { useEffect, useState } from "react";
import { getValidation } from "../api/validation";
import type { ValidationSnapshot } from "../types/validation.generated";

export type ValidationTelemetry = { state: "loading" | "connected" | "unavailable"; data?: ValidationSnapshot };

export function useValidation(): ValidationTelemetry {
  const [state, setState] = useState<ValidationTelemetry>({ state: "loading" });
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    async function refresh() {
      try {
        const data = await getValidation(abort.signal);
        failures = 0;
        if (!abort.signal.aborted) setState({ state: "connected", data });
      } catch {
        failures++;
        if (!abort.signal.aborted) setState({ state: "unavailable" });
      } finally {
        if (!abort.signal.aborted)
          timer = setTimeout(refresh, Math.min(60000, 15000 * 2 ** Math.min(failures, 2)));
      }
    }
    void refresh();
    return () => { abort.abort(); clearTimeout(timer); };
  }, []);
  return state;
}
