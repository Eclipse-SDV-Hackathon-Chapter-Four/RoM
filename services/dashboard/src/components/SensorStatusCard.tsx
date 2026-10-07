import type { SensorInfo } from "../types/dashboard";
import { SignalIcon } from "./icons";

export default function SensorStatusCard({ sensor }: { sensor: SensorInfo }) {
  const online = sensor.status === "ONLINE";
  return (
    <section className="card compact" aria-label="Sensor status">
      <h2 className="card-title small"><span className="icon icon-blue"><SignalIcon /></span>Sensor Status</h2>
      <div className="sensor-status">
        <span className={`dot ${online ? "dot-on" : "dot-off"}`} />
        <span>{sensor.status}</span>
      </div>
    </section>
  );
}
