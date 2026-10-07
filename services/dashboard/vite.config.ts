import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import evidenceReport from "./vite/evidence-report.mjs";
import scenarios from "./vite/scenarios.mjs";
import cellSource from "./vite/cell-source.mjs";

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
    // VITE_CACHE_DIR: scripts/dashboard-dev.sh keeps Vite's optimizer cache inside the container, so another process (or a
    // container running as root) that shares the checkout cannot leave files in node_modules/.vite that this one cannot replace
    cacheDir: env.VITE_CACHE_DIR || undefined,
    // /evidence-report/{meta.json,report.html}: the generated report of the newest completed final run (runs/<id>/)
    // /api/scenarios/{,status,run}: starts ONE bundled fault campaign of the running stack (ROM_RUNTIME_REPO), local demo only
    // /api/cell1-source: cell 1 from the AZ3166 board or the simulator, never both (local demo only)
    plugins: [react(), evidenceReport(), scenarios(), cellSource()],
    server: { host: true, port: 5173, proxy },
    preview: { proxy },
  };
});
