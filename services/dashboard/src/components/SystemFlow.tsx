import type { CSSProperties, ReactNode } from "react";
import { AdapterIcon, BridgeIcon, BrokerIcon, DisplayIcon, FlowIcon, SensorIcon, ServerIcon, ShieldIcon, SignalIcon } from "./icons";

interface NodeProps {
  icon: ReactNode;
  title: string;
  sub: string;
  tone: "sensor" | "broker" | "service" | "guardian" | "display" | "sim";
  at: [col: number, row: number];
  className?: string;
  children?: ReactNode;
}

const place = ([col, row]: [number, number]): CSSProperties => ({ gridColumn: col, gridRow: row });

const Node = ({ icon, title, sub, tone, at, className = "", children }: NodeProps) => (
  <div className={`flow-node tone-${tone} ${className}`} style={place(at)}>
    <span className="flow-icon">{icon}</span>
    <div>
      <strong>{title}</strong>
      <span>{sub}</span>
    </div>
    {children}
  </div>
);

const Arrow = ({ col, label }: { col: number; label?: string }) => (
  <div className="flow-arrow" style={place([col, 1])} aria-hidden="true">
    <span className="flow-label">{label ?? " "}</span>
    <span className="flow-line" />
  </div>
);

/**
 * Static picture of the CURRENT data path with four cells:
 *   AZ3166 (cell 1) -MQTT-> Mosquitto -> MQTT-KUKSA adapter -> KUKSA Databroker
 *   Simulator (cells 2-4) ----------------------------------> KUKSA Databroker (writes directly)
 *   KUKSA -> VSS uProtocol client -uProtocol/Zenoh-> Battery Thermal Guardian,
 *   and Guardian -MQTT rom/actuator/display/cmd-> AZ3166 OLED.
 * The Guardian never reads KUKSA, and the display command does not use uProtocol. There is exactly one Guardian node.
 */
export default function SystemFlow() {
  return (
    <section className="card flow-card" aria-label="System flow">
      <h2 className="card-title"><span className="icon icon-blue"><FlowIcon /></span>System Flow (Data Pipeline)</h2>

      <div className="flow-grid">
        <Node at={[1, 1]} tone="sensor" icon={<SensorIcon />} title="AZ3166" sub="Cell 1 · physical board" />
        <Arrow col={2} label="MQTT" />
        <Node at={[3, 1]} tone="broker" icon={<BrokerIcon />} title="Mosquitto" sub="MQTT Broker" />
        <Arrow col={4} />
        <Node at={[5, 1]} tone="service" icon={<AdapterIcon />} title="MQTT → KUKSA" sub="Adapter" />
        <Arrow col={6} />
        <Node at={[7, 1]} tone="service" icon={<ServerIcon />} title="KUKSA" sub="Databroker" />
        <Arrow col={8} />
        <Node at={[9, 1]} tone="service" icon={<BridgeIcon />} title="VSS uProtocol" sub="Client" />
        <Arrow col={10} label="uProtocol / Zenoh" />
        <Node at={[11, 1]} tone="guardian" icon={<ShieldIcon />} title="Battery Thermal Guardian" sub="Safety Logic" />

        <Node at={[1, 2]} tone="sim" className="flow-sim" icon={<SignalIcon />} title="Simulator" sub="Cells 2–4 → KUKSA" />
        <div className="flow-wire" style={{ gridColumn: "2 / 7", gridRow: 2 }} aria-hidden="true">
          <span className="flow-label">writes straight to KUKSA</span>
          <span className="flow-line flow-line-plain" />
        </div>
        <div className="flow-join" style={place([7, 2])} aria-hidden="true"><span className="flow-join-head" /></div>

        <Node at={[11, 2]} tone="display" className="flow-oled" icon={<DisplayIcon />} title="AZ3166 OLED" sub="Display (same board)">
          <span className="flow-stub" aria-hidden="true" />
          <span className="flow-stub-label" aria-hidden="true">MQTT · <code>rom/actuator/display/cmd</code></span>
        </Node>
      </div>
    </section>
  );
}
