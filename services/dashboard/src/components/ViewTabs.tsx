export type ViewId = "live" | "evidence";

const VIEWS: { id: ViewId; label: string; hash: string }[] = [
  { id: "live", label: "Live Monitoring", hash: "#/live" },
  { id: "evidence", label: "Safety Evidence", hash: "#/evidence" },
];

/** Top-level view switch. Plain links to a hash route, so a refresh or a shared URL stays on the same view. */
export default function ViewTabs({ view }: { view: ViewId }) {
  return (
    <nav className="view-tabs" aria-label="Views">
      {VIEWS.map((v) => (
        <a key={v.id} href={v.hash} className={`view-tab${view === v.id ? " active" : ""}`} aria-current={view === v.id ? "page" : undefined}>
          {v.label}
        </a>
      ))}
    </nav>
  );
}
