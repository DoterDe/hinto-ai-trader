import { useEffect, useState } from "react";
import { getSnapshot } from "../api/client";
import type { Snapshot } from "../types";

export type Telemetry = {
  data?: Snapshot;
  connection: "loading" | "connected" | "unavailable";
  receivedAt?: number;
};

export function useTelemetry(): Telemetry {
  const [state, setState] = useState<Telemetry>({ connection: "loading" });
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    let busy = false;
    const refresh = async () => {
      if (abort.signal.aborted || busy) return;
      clearTimeout(timer);
      busy = true;
      try {
        const data = await getSnapshot(abort.signal);
        failures = 0;
        if (!abort.signal.aborted)
          setState({ data, connection: "connected", receivedAt: Date.now() });
      } catch {
        failures++;
        // A failed refresh cannot leave old equity/health looking current.
        if (!abort.signal.aborted) setState({ connection: "unavailable" });
      } finally {
        busy = false;
        if (!abort.signal.aborted)
          timer = setTimeout(
            refresh,
            Math.min(15000, 2000 * 2 ** Math.min(failures, 3)),
          );
      }
    };
    const visible = () => {
      if (document.visibilityState === "visible") {
        setState({ connection: "loading" });
        void refresh();
      }
    };
    void refresh();
    document.addEventListener("visibilitychange", visible);
    return () => {
      abort.abort();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, []);
  return state;
}
