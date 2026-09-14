import { Badge, Card } from "./Common";
import { Label } from "../help/Help";
import type { Snapshot } from "../types";
import { time } from "../utils/format";

type State = Snapshot["status"]["persistence"];
const messages: Record<State["status"], string> = {
  DISABLED: "Persistence disabled. Virtual state stays in memory for this run.",
  NEW_SESSION: "New virtual session. Waiting for the first durable checkpoint.",
  RECOVERING: "Validating saved virtual state before the public feed starts.",
  RECOVERED: "Recovered virtual session. Waiting for new admissible public candles.",
  DURABLE: "Current virtual state is durable.",
  DEGRADED: "Persistence degraded. Further paper transitions are stopped; newer state may be unsaved.",
  INCOMPATIBLE: "Recovery incompatible. The saved session requires different settings. Paper processing is stopped.",
  CORRUPT: "Saved virtual state cannot be trusted or recovered. Paper processing is stopped.",
  ERROR: "Local persistence is unavailable. Paper processing is stopped.",
};

export function Persistence({ state, advanced = false }: { state: State; advanced?: boolean }) {
  return (
    <Card title="Virtual session & recovery" help="persistence">
      <Badge value={state.status} />
      <p>{state.status === "DURABLE" && state.has_uncommitted_changes
        ? "Saving new virtual state. The previous checkpoint remains authoritative."
        : messages[state.status]}</p>
      {state.recovered && <p>Recovered virtual session: its identity and committed accounting were preserved.</p>}
      <dl className="rows">
        <div><dt><Label name="checkpoint" text="Last durable checkpoint" /></dt><dd>{time(state.checkpoint_at)}</dd></div>
        <div><dt><Label name="durable_boundary" /></dt><dd>{time(state.durable_boundary)}</dd></div>
        <div><dt>Newer unsaved state</dt><dd>{state.has_uncommitted_changes ? "Yes" : "No"}</dd></div>
      </dl>
      <p className="footnote">All capital remains virtual. Missing candles during downtime can leave reservations expired or positions incomplete; a recent price cannot repair them.</p>
      {advanced && <dl className="rows">
        <div><dt><Label name="session_id" /></dt><dd><code>{state.session_id ?? "Unknown"}</code></dd></div>
        <div><dt>Session created</dt><dd>{time(state.session_created_at)}</dd></div>
        <div><dt>Checkpoint ID</dt><dd><code>{state.checkpoint_id ?? "Unknown"}</code></dd></div>
        <div><dt>Checksum</dt><dd><code>{state.checksum ?? "Unknown"}</code></dd></div>
        <div><dt>Schema version</dt><dd>{state.schema_version}</dd></div>
        <div><dt>Current memory boundary</dt><dd>{time(state.in_memory_boundary)}</dd></div>
        <div><dt>Retained checkpoints / audit events</dt><dd>{state.retained_checkpoints} / {state.retained_audit_events}</dd></div>
        <div><dt><Label name="configuration_compatibility" /></dt><dd>{state.configuration_compatible === null ? "Unknown" : state.configuration_compatible ? "Compatible" : "Incompatible"}</dd></div>
        <div><dt>Database healthy</dt><dd>{state.database_healthy ? "Yes" : "No"}</dd></div>
        <div><dt>Persistence reason</dt><dd>{state.reason ?? "None"}</dd></div>
      </dl>}
    </Card>
  );
}
