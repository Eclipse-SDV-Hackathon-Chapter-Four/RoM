import { useCallback, useEffect, useState } from "react";
import { EVIDENCE_REPORT_BASE, fetchEvidenceMeta, type EvidenceMeta } from "../data/evidenceReport";

type State = { kind: "loading" } | { kind: "unreachable"; message: string } | { kind: "meta"; meta: EvidenceMeta };

/**
 * Safety Evidence: the Evidence Collector's own generated report.html of the newest completed final run, embedded as
 * is. This component adds only a strip of numbers read from evidence.json and a readable state for every way there can
 * be nothing to show. It never invents verdicts and never shows a stand-in report.
 */
export default function SafetyEvidence() {
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
    <main className="evidence-view" aria-label="Safety evidence">
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
    </main>
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
