/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "mock" (default) = simulated telemetry, "live" = the running stack through the Evidence Collector. */
  readonly VITE_DASHBOARD_SOURCE?: string;
  /** Base URL of the Evidence Collector API as seen by the browser. Default "/evidence-api" (Vite dev proxy). */
  readonly VITE_EVIDENCE_API_BASE?: string;
  /** Where the generated evidence report is served (meta.json, report.html). Default "/evidence-report" (Vite dev server). */
  readonly VITE_EVIDENCE_REPORT_BASE?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
