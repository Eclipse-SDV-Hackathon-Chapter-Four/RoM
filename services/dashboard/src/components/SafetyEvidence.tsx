import { useCallback, useEffect, useState } from "react";
import { EVIDENCE_REPORT_BASE, fetchEvidenceMeta, type EvidenceMeta } from "../data/evidenceReport";

type State = { kind: "loading" } | { kind: "unreachable"; message: string } | { kind: "meta"; meta: EvidenceMeta };
type Mode = "live" | "saved";

const LIVE_BASE = "/evidence-api"; // vite.config.ts proxies this to the Evidence Collector
const LIVE_POLL_MS = 2000;

/**
 * Safety Evidence. Live: the running Evidence Collector's report, reloaded whenever a new verdict arrives (a scenario
 * started from the dropdown shows up here once the collector has judged it). Saved run: the generated report.html of the
 * newest completed run in runs/ (make evidence-snapshot / make final-run), embedded as is. This component adds only a strip of numbers read from evidence.json and a readable state for every way there can
 * be nothing to show. It never invents verdicts and never shows a stand-in report.
 */
export default function SafetyEvidence() {
  const [mode, setMode] = useState<Mode>("live");
  return (
    <main className="evidence-view" aria-label="Safety evidence">
      <div className="view-tabs evidence-mode" role="tablist">
        {(["live", "saved"] as const).map((m) => (
          <button key={m} type="button" role="tab" aria-selected={mode === m} className={`view-tab${mode === m ? " active" : ""}`} onClick={() => setMode(m)}>
            {m === "live" ? "Live" : "Saved run"}
          </button>
        ))}
      </div>
      {mode === "live" ? <LiveEvidence /> : <SavedEvidence />}
    </main>
  );
}

type Summary = { total: number; verdicts: Record<string, number> };
type Health = { open_run?: string | null };

function LiveEvidence() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [openRun, setOpenRun] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stop = false;
    const poll = async () => {
      try {
        const [s, h] = await Promise.all([
          fetch(`${LIVE_BASE}/evidence/summary`, { cache: "no-store" }).then((r) => (r.ok ? (r.json() as Promise<Summary>) : Promise.reject(new Error(`HTTP ${r.status}`)))),
          fetch(`${LIVE_BASE}/health`, { cache: "no-store" }).then((r) => r.json() as Promise<Health>).catch(() => ({}) as Health),
        ]);
        if (stop) return;
        setSummary(s);
        setOpenRun(h.open_run ?? null);
        setError(null);
      } catch (e) {
        if (!stop) setError(e instanceof Error ? e.message : String(e));
      }
    };
    poll();
    const id = setInterval(poll, LIVE_POLL_MS);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, []);

  if (error && !summary) {
    return (
      <section className="evidence-notice error" role="alert">
        <h2>The Evidence Collector is not reachable.</h2>
        <p>{error}. Start the stack with <code>make guardian</code>; this view retries every {LIVE_POLL_MS / 1000} s.</p>
      </section>
    );
  }
  if (!summary) return <p className="loading">Connecting to the Evidence Collector…</p>;
  const v = summary.verdicts ?? {};
  // the report reloads only when the number of verdicts changes, not on every poll
  const src = `${LIVE_BASE}/ui/?n=${summary.total}`;
  return (
    <>
      <div className="evidence-strip">
        <span className="evidence-title">Live evidence</span>
        <span>Runs judged <strong>{summary.total}</strong></span>
        <span className="ev-pass">PASS <strong>{v.PASS ?? 0}</strong></span>
        <span className="ev-fail">FAIL <strong>{v.FAIL ?? 0}</strong></span>
        <span className="ev-inc">INCONCLUSIVE <strong>{v.INCONCLUSIVE ?? 0}</strong></span>
        {openRun ? <span className="ev-chip">judging <strong className="mono">{openRun}</strong>…</span> : <span className="ev-chip ok">idle</span>}
        {error && <span className="ev-chip bad" title={error}>connection lost, retrying</span>}
        <span className="evidence-actions">
          <a className="scenario-btn" href={src} target="_blank" rel="noopener noreferrer">Open report in new tab</a>
        </span>
      </div>
      {summary.total === 0 ? (
        <section className="evidence-notice empty" role="status">
          <h2>No verdicts yet.</h2>
          <p>Run a scenario from the dropdown in Live Monitoring; its verdict appears here as soon as the collector has judged it.</p>
        </section>
      ) : (
        <iframe className="evidence-frame" title="Live evidence report" src={src} sandbox="" referrerPolicy="no-referrer" />
      )}
    </>
  );
}

function SavedEvidence() {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [nonce, setNonce] = useState(0); // new value = rescan runs/ and reload the report

  const load = useCallback((signal?: AbortSignal) => {
    setState({ kind: "loading" });
    fetchEvidenceMeta(EVIDENCE_REPORT_BASE, signal)
      .then((meta) => setState({ kind: "meta", meta }))
      .catch((e) => {
        if (signal?.aborted) return;
        setState({ kind: "unreachable", message: e instanceof Error ? e.message : String(e) });
      });
  }, []);

  useEffect(() => {
    const ctl = new AbortController();
    load(ctl.signal);
    return () => ctl.abort();
  }, [load, nonce]);

  return (
    <>
      {state.kind === "loading" && <p className="loading">Looking for a completed evidence run…</p>}

      {state.kind === "unreachable" && (
        <Notice tone="error" title="The evidence service is not reachable." onRescan={() => setNonce(nonce + 1)}>
          {state.message}. The report is served by the Vite dev server from the repository's <code>runs/</code> folder; a static build
          does not include it.
        </Notice>
      )}

      {state.kind === "meta" && !state.meta.available && (
        <Unavailable meta={state.meta} onRescan={() => setNonce(nonce + 1)} />
      )}

      {state.kind === "meta" && state.meta.available && (
        <Report meta={state.meta} nonce={nonce} onRescan={() => setNonce(nonce + 1)} />
      )}
    </>
  );
}

function Notice({ tone, title, children, onRescan }: { tone: "empty" | "error"; title: string; children: React.ReactNode; onRescan: () => void }) {
  return (
    <section className={`evidence-notice ${tone}`} role={tone === "error" ? "alert" : "status"}>
      <h2>{title}</h2>
      <p>{children}</p>
      <button type="button" className="scenario-btn" onClick={onRescan}>Rescan</button>
    </section>
  );
}

function Unavailable({ meta, onRescan }: { meta: Extract<EvidenceMeta, { available: false }>; onRescan: () => void }) {
  if (meta.status === "no_runs_dir" || meta.status === "no_valid_run") {
    return (
      <Notice tone="empty" title="No completed evidence run available." onRescan={onRescan}>
        Run the final evidence pipeline (<code>make final-run</code>) or add a completed <code>runs/&lt;id&gt;/</code> folder containing{" "}
        <code>evidence.json</code>, <code>summary.json</code> and <code>evidence-bundle.zip</code>, then rescan. {meta.message}
      </Notice>
    );
  }
  const titles = {
    invalid_evidence: "The evidence of this run cannot be read.",
    extract_failed: "The evidence bundle could not be opened.",
    report_missing: "The evidence bundle has no report.",
  } as const;
  return (
    <Notice tone="error" title={`${titles[meta.status]}${meta.runId ? ` (run ${meta.runId})` : ""}`} onRescan={onRescan}>
      {meta.message}
    </Notice>
  );
}

function Report({ meta, nonce, onRescan }: { meta: Extract<EvidenceMeta, { available: true }>; nonce: number; onRescan: () => void }) {
  const src = `${meta.reportUrl}?run=${encodeURIComponent(meta.runId)}&r=${nonce}`;
  return (
    <>
      <div className="evidence-strip">
        <span className="evidence-title">Safety Evidence</span>
        <span>Run <strong className="mono">{meta.runId}</strong></span>
        <span>Campaigns <strong>{meta.campaigns}</strong></span>
        <span className="ev-pass">PASS <strong>{meta.pass}</strong></span>
        <span className="ev-fail">FAIL <strong>{meta.fail}</strong></span>
        <span className="ev-inc">INCONCLUSIVE <strong>{meta.inconclusive}</strong></span>
        {meta.other > 0 && <span className="ev-warn">OTHER <strong>{meta.other}</strong></span>}
        {meta.manifest === "verified" && <span className="ev-chip ok" title="Every file of the bundle matches the SHA-256 in manifest.json">checksums verified</span>}
        {meta.manifest === "mismatch" && <span className="ev-chip bad" title="A file of the bundle differs from manifest.json">CHECKSUM MISMATCH</span>}
        {meta.manifest === "absent" && <span className="ev-chip" title="The bundle has no usable manifest.json">no manifest</span>}
        {meta.summaryAgrees === false && <span className="ev-chip bad" title="summary.json and evidence.json disagree on the number of records">summary.json disagrees</span>}
        <span className="evidence-actions">
          <a className="scenario-btn" href={src} target="_blank" rel="noopener noreferrer">Open report in new tab</a>
          <button type="button" className="scenario-btn" onClick={onRescan}>Rescan</button>
        </span>
      </div>
      <iframe className="evidence-frame" title={`Generated evidence report, run ${meta.runId}`} src={src} sandbox="" referrerPolicy="no-referrer" />
    </>
  );
}
