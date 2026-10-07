// Local hackathon demo control: runs ONE bundled fault-injection campaign of the running Docker Compose stack, on request
// of the dashboard. It is the same command `make campaign C=<id>` runs (see the Makefile of the runtime repo), nothing is
// simulated here. Plain Node built-ins; only for the Vite dev server / preview, a static build has no such API.
//
//   GET  /api/scenarios          {scenarios: [{id, label}]}
//   GET  /api/scenarios/status   {status: idle|running|completed|failed, scenario?, startedAt?, finishedAt?, exitCode?}
//   POST /api/scenarios/run      {"scenario": "<id>"}  ->  202 {status: "running", scenario}
//                                400 unknown id / bad body · 409 already running · 503 stack not healthy
//
// Security: the browser sends an id, never a command. The id must be a key of SCENARIOS (and its YAML must exist in the
// runtime repo); the command and its arguments are fixed here and started with spawn() and an argument array, no shell.
import { spawn as nodeSpawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** Canonical campaign name (= file name of services/fault-injector/fault_injector/campaigns/<id>.yaml) -> display label. */
export const SCENARIOS = Object.freeze({
  thermal_runaway: "Thermal Runaway",
  transport_drop: "Transport Drop",
  transport_delay: "Transport Delay",
  sensor_stuck: "Sensor Stuck",
  sensor_stuck_cell3: "Sensor Stuck — Cell 3",
  out_of_range: "Out of Range",
  source_dropout: "Source Dropout",
  cell_dropout_cell2: "Cell Dropout — Cell 2",
  cell_faulty_while_other_hot: "Faulty Cell While Another Cell Is Hot",
  combined_runaway_lossy_link: "Combined Runaway + Lossy Link",
  databroker_down: "Databroker Down",
  chip_heartbeat_loss: "Chip Heartbeat Loss",
  producer_heartbeat_loss: "Producer Heartbeat Loss",
  uprotocol_heartbeat_loss: "uProtocol Heartbeat Loss",
  replay_interruption: "Replay Interruption",
});

const CAMPAIGN_DIR = ["services", "fault-injector", "fault_injector", "campaigns"];
const COMPOSE_FILE = path.join("infra", "docker-compose.yml");
const MAX_BODY = 1024;
const MAX_TAIL = 2000;

/** The exact argv of `make campaign C=<id>` (Makefile: $(DC) --profile tools run --rm -T fault-injector ...). */
export function campaignCommand(id) {
  return { command: "docker", args: ["compose", "-f", COMPOSE_FILE, "--profile", "tools", "run", "--rm", "-T", "fault-injector", "rom-fault-injector", "run", id] };
}

// ROM_RUNTIME_REPO: the checkout whose infra/docker-compose.yml runs the stack. Default: the repository this file is in.
export const defaultRuntimeRepo = () => process.env.ROM_RUNTIME_REPO || fileURLToPath(new URL("../../..", import.meta.url));
const defaultHealthUrl = () => `${(process.env.EVIDENCE_API_TARGET || "http://localhost:8082").replace(/\/$/, "")}/health`;

/** Allowlisted scenarios whose campaign definition really exists in the runtime repo (or all, if it cannot be read). */
export function listScenarios(runtimeRepo) {
  let present = null;
  try {
    present = new Set(fs.readdirSync(path.join(runtimeRepo, ...CAMPAIGN_DIR)).filter((f) => f.endsWith(".yaml")).map((f) => f.slice(0, -5)));
  } catch {
    present = null;
  }
  return Object.entries(SCENARIOS)
    .filter(([id]) => !present || present.has(id))
    .map(([id, label]) => ({ id, label }));
}

/** Healthy = the collector answers ok and the guardian is back in MONITORING (a campaign during another state is judged INCONCLUSIVE). */
async function checkHealth(healthUrl, fetchFn) {
  try {
    const res = await fetchFn(healthUrl, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) return `Evidence Collector answered HTTP ${res.status}`;
    const h = await res.json();
    if (h.ok !== true) return "Evidence Collector reports not ok";
    if (h.guardian_state !== "MONITORING") return `Guardian is ${h.guardian_state ?? "in an unknown state"}, not MONITORING`;
    if (h.open_run) return `Campaign ${h.open_run} is still open in the Evidence Collector`;
    return null;
  } catch (e) {
    return `Evidence Collector is not reachable (${e instanceof Error ? e.message : e})`;
  }
}

/** The controller behind the routes; options are injectable so tests never touch Docker. */
export function createScenarioRunner({
  runtimeRepo = defaultRuntimeRepo(),
  healthUrl = defaultHealthUrl(),
  spawn = nodeSpawn,
  fetchFn = fetch,
  now = () => new Date().toISOString(),
} = {}) {
  let state = { status: "idle" };

  const run = async (id) => {
    if (typeof id !== "string" || !Object.hasOwn(SCENARIOS, id) || !listScenarios(runtimeRepo).some((s) => s.id === id)) {
      return { code: 400, body: { error: "Unknown scenario" } };
    }
    if (state.status === "running") return { code: 409, body: { error: "A scenario is already running", scenario: state.scenario } };
    // Claim the slot before the first await: two requests in the same tick must not both pass.
    state = { status: "running", scenario: id, startedAt: now() };
    const unhealthy = await checkHealth(healthUrl, fetchFn);
    if (unhealthy) {
      state = { status: "idle" };
      return { code: 503, body: { error: "Runtime stack is not healthy", detail: unhealthy } };
    }
    const { command, args } = campaignCommand(id);
    let tail = "";
    const keep = (chunk) => {
      tail = (tail + chunk.toString()).slice(-MAX_TAIL);
    };
    const finish = (exitCode, error) => {
      state = {
        status: exitCode === 0 ? "completed" : "failed",
        scenario: id,
        startedAt: state.startedAt,
        finishedAt: now(),
        exitCode,
        ...(exitCode === 0 ? {} : { error: error || tail.trim().split("\n").slice(-3).join("\n") }),
      };
    };
    try {
      const child = spawn(command, args, { cwd: runtimeRepo, stdio: ["ignore", "pipe", "pipe"], shell: false });
      child.stdout?.on("data", keep);
      child.stderr?.on("data", keep);
      let done = false;
      child.on("error", (e) => {
        if (!done) {
          done = true;
          finish(-1, `could not start: ${e.message}`);
        }
      });
      child.on("close", (code, signal) => {
        if (!done) {
          done = true;
          finish(code ?? -1, signal ? `terminated by ${signal}` : undefined);
        }
      });
    } catch (e) {
      finish(-1, `could not start: ${e instanceof Error ? e.message : e}`);
    }
    return { code: 202, body: { status: "running", scenario: id } };
  };

  return { run, status: () => ({ ...state }), list: () => listScenarios(runtimeRepo) };
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (c) => {
      size += c.length;
      if (size > MAX_BODY) {
        reject(new Error("body too large"));
        req.destroy();
      } else chunks.push(c);
    });
    req.on("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch {
        reject(new Error("body is not JSON"));
      }
    });
    req.on("error", reject);
  });
}

function middleware(runner) {
  const send = (res, code, body) => {
    res.statusCode = code;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.end(JSON.stringify(body));
  };
  return async (req, res, next) => {
    const url = (req.url || "/").split("?")[0].replace(/\/$/, "") || "/";
    const method = req.method || "GET";
    if (url === "/") return method === "GET" ? send(res, 200, { scenarios: runner.list() }) : send(res, 405, { error: "Method not allowed" });
    if (url === "/status") return method === "GET" ? send(res, 200, runner.status()) : send(res, 405, { error: "Method not allowed" });
    if (url !== "/run") return next();
    if (method !== "POST") return send(res, 405, { error: "Method not allowed" });
    // A page of another origin must not be able to start campaigns: browsers always send Origin on a cross-origin POST.
    const origin = req.headers.origin;
    if (origin && new URL(origin).host !== req.headers.host) return send(res, 403, { error: "Cross-origin request refused" });
    let body;
    try {
      body = await readJson(req);
    } catch (e) {
      return send(res, 400, { error: e.message });
    }
    const out = await runner.run(body && typeof body === "object" ? body.scenario : undefined);
    return send(res, out.code, out.body);
  };
}

/** Vite plugin (dev server and `vite preview`). */
export default function scenariosPlugin(options = {}) {
  const runner = createScenarioRunner(options);
  const base = "/api/scenarios";
  return {
    name: "rom-scenarios",
    configureServer(server) {
      server.middlewares.use(base, middleware(runner));
    },
    configurePreviewServer(server) {
      server.middlewares.use(base, middleware(runner));
    },
  };
}
