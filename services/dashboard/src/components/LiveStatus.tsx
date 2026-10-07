/** Pulsing indicator: the dashboard is receiving a stream (here simulated), not showing a static snapshot. */
export default function LiveStatus({ label }: { label: string }) {
  return (
    <div className="live-status" role="status">
      <span className="live-dot" aria-hidden="true" />
      <strong>LIVE DEMO</strong>
      <span className="live-sub">{label}</span>
    </div>
  );
}
