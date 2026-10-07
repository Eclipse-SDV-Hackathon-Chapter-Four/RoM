/**
 * Pulsing indicator. Mock: "LIVE DEMO" with a simulated stream. Live: "LIVE DATA" from the running stack, and a red dot
 * when the data source cannot be reached (the last real data stays on screen, never simulated values).
 */
export default function LiveStatus({ live, label, connected = true }: { live: boolean; label: string; connected?: boolean }) {
  return (
    <div className={`live-status${connected ? "" : " live-lost"}`} role="status">
      <span className="live-dot" aria-hidden="true" />
      <strong>{live ? "LIVE DATA" : "LIVE DEMO"}</strong>
      <span className="live-sub">{connected ? label : "Evidence Collector unreachable"}</span>
    </div>
  );
}
