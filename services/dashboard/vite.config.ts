import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import evidenceReport from "./vite/evidence-report.mjs";

// The Evidence Collector sends no CORS headers, so the browser talks to it through this same-origin proxy:
// /evidence-api/events -> $EVIDENCE_API_TARGET/events (default http://localhost:8082). Dev server and preview only.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const proxy = {
    "/evidence-api": {
      target: env.EVIDENCE_API_TARGET || "http://localhost:8082",
      changeOrigin: true,
      rewrite: (path: string) => path.replace(/^\/evidence-api/, ""),
    },
  };
  return {
    // /evidence-report/{meta.json,report.html}: the generated report of the newest completed final run (runs/<id>/)
    plugins: [react(), evidenceReport()],
    server: { host: true, port: 5173, proxy },
    preview: { proxy },
  };
});
