/**
 * The generated Evidence Collector report of a completed final run (runs/<id>/), as the browser sees it. Two stable
 * HTTP documents, nothing about where they come from: today the Vite dev server (vite/evidence-report.mjs), later a
 * hosted artifact API could return the same shapes.
 *   <base>/meta.json    {available, ...}
 *   <base>/report.html  the self-contained generated report
 */
export interface EvidenceAvailable {
  available: true;
  runId: string;
  /** Counts derived from the run's evidence.json. */
  campaigns: number;
  pass: number;
  fail: number;
  inconclusive: number;
  /** Records whose verdict is none of the three. */
  other: number;
  /** summary.json agrees with evidence.json on the number of records; null when summary.json cannot say. */
  summaryAgrees: boolean | null;
  /** SHA-256 check of the bundle files against its manifest.json. */
  manifest: "verified" | "mismatch" | "absent";
  reportUrl: string;
}

export type EvidenceUnavailableStatus = "no_runs_dir" | "no_valid_run" | "invalid_evidence" | "extract_failed" | "report_missing";

export interface EvidenceUnavailable {
  available: false;
  status: EvidenceUnavailableStatus;
  message: string;
  /** The run that was selected but could not be shown. */
  runId?: string;
}

export type EvidenceMeta = EvidenceAvailable | EvidenceUnavailable;

export const EVIDENCE_REPORT_BASE = import.meta.env.VITE_EVIDENCE_REPORT_BASE || "/evidence-report";

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** Throws with a readable message when the service is missing or answers something unexpected. */
export async function fetchEvidenceMeta(base = EVIDENCE_REPORT_BASE, signal?: AbortSignal): Promise<EvidenceMeta> {
  const res = await fetch(`${base}/meta.json`, { cache: "no-store", signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    throw new Error("the answer is not JSON (is the evidence route served?)");
  }
  if (!isObj(body) || typeof body.available !== "boolean") throw new Error("unexpected answer");
  if (body.available === false) {
    return {
      available: false,
      status: (body.status as EvidenceUnavailableStatus) ?? "no_valid_run",
      message: typeof body.message === "string" ? body.message : "",
      runId: typeof body.runId === "string" ? body.runId : undefined,
    };
  }
  const n = (k: string) => (typeof body[k] === "number" ? (body[k] as number) : NaN);
  if (typeof body.runId !== "string" || typeof body.reportUrl !== "string" || [n("campaigns"), n("pass"), n("fail"), n("inconclusive")].some(Number.isNaN)) {
    throw new Error("unexpected answer");
  }
  return {
    available: true,
    runId: body.runId,
    campaigns: n("campaigns"),
    pass: n("pass"),
    fail: n("fail"),
    inconclusive: n("inconclusive"),
    other: Number.isNaN(n("other")) ? 0 : n("other"),
    summaryAgrees: typeof body.summaryAgrees === "boolean" ? body.summaryAgrees : null,
    manifest: body.manifest === "verified" || body.manifest === "mismatch" ? body.manifest : "absent",
    reportUrl: body.reportUrl,
  };
}
