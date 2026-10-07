import type { ReactNode } from "react";
import { AdapterIcon, BridgeIcon, BrokerIcon, DisplayIcon, FlowIcon, SensorIcon, ServerIcon, ShieldIcon } from "./icons";

interface NodeProps {
  icon: ReactNode;
  title: string;
  sub: string;
  tone: "sensor" | "broker" | "service" | "guardian" | "display";
}

const Node = ({ icon, title, sub, tone }: NodeProps) => (
  <div className={`flow-node tone-${tone}`}>
    <span className="flow-icon">{icon}</span>
    <div>
      <strong>{title}</strong>
      <span>{sub}</span>
    </div>
  </div>
);

const Arrow = ({ label }: { label?: string }) => (
  <div className="flow-arrow" aria-hidden="true">
    <span className="flow-label">{label ?? " "}</span>
    <span className="flow-line" />
  </div>
);

/**
 * Static picture of the CURRENT data path:
 *   AZ3166 -MQTT-> Mosquitto -> MQTT-KUKSA adapter -> KUKSA Databroker -> VSS uProtocol client
 *     -uProtocol/Zenoh-> Guardian,  and Guardian -MQTT rom/actuator/display/cmd-> AZ3166 OLED.
 * The Guardian never reads KUKSA, and the display command does not use uProtocol.
 */
export default function SystemFlow() {
  return (
    <section className="card flow-card" aria-label="System flow">
      <h2 className="card-title"><span className="icon icon-blue"><FlowIcon /></span>System Flow (Data Pipeline)</h2>

      <div className="flow-row">
        <Node tone="sensor" icon={<SensorIcon />} title="AZ3166" sub="Battery Sensor" />
        <Arrow label="MQTT" />
        <Node tone="broker" icon={<BrokerIcon />} title="Mosquitto" sub="MQTT Broker" />
        <Arrow />
        <Node tone="service" icon={<AdapterIcon />} title="MQTT → KUKSA" sub="Adapter" />
        <Arrow />
        <Node tone="service" icon={<ServerIcon />} title="KUKSA" sub="Databroker" />
        <Arrow />
        <Node tone="service" icon={<BridgeIcon />} title="VSS uProtocol" sub="Client" />
        <Arrow label="uProtocol / Zenoh" />
        <Node tone="guardian" icon={<ShieldIcon />} title="Battery Thermal Guardian" sub="Safety Logic" />
      </div>

      <div className="flow-feedback">
        <Node tone="display" icon={<DisplayIcon />} title="AZ3166 OLED" sub="Display (same board)" />
        <div className="flow-back" aria-hidden="true">
          <span className="flow-label">MQTT · <code>rom/actuator/display/cmd</code></span>
          <span className="flow-line flow-line-left" />
        </div>
        <div className="flow-node tone-guardian flow-chip">
          <span className="flow-icon"><ShieldIcon /></span>
          <div><strong>Battery Thermal Guardian</strong></div>
        </div>
      </div>
    </section>
  );
}
