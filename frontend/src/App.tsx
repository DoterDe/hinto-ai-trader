import { Dashboard } from "./layouts/Dashboard";
import { useTelemetry } from "./hooks/useTelemetry";
export default function App() {
  return <Dashboard telemetry={useTelemetry()} />;
}
