// Local hackathon demo control: runs ONE bundled fault-injection campaign of the running Docker Compose stack, on request
// of the dashboard. It is the same command `make campaign C=<id>` runs (see the Makefile of the runtime repo), nothing is
// simulated here. Plain Node built-ins; only for the Vite dev server / preview, a static build has no such API.
//
//   GET  /api/scenarios          {scenarios: [{id, label}]}
//   GET  /api/scenarios/status   {status: idle|running|completed|failed, scenario?, startedAt?, finishedAt?, exitCode?}
//   POST /api/scenarios/run      {"scenario": "<id>"}  ->  202 {status: "running", scenario}
//                                400 unknown id / bad body · 409 already running or stopping · 503 stack not healthy
//   POST /api/scenarios/stop     (no body)  ->  202 {status: "stopping", scenario} · 409 nothing running / already stopping
//
// status: idle | running | stopping | completed | failed | stopped. "stopped" is an orchestration status only (the stop
// was requested); the verdict of an interrupted campaign is whatever the Evidence Collector records, never invented here.
// Stop = SIGINT to the exact campaign container (the fault injector then clears its faults and logs campaign_end
// "interrupted"; SIGTERM would be ignored by a PID 1 without a handler and skip that cleanup), then, only after a grace
// period, SIGKILL of that same container. Containers are named rom-dashboard-campaign-<id>-<random> and labelled
// rom.dashboard.campaign=<id>; the API takes no container argument and every docker call is checked against that name.
//
// Security: the browser sends an id, never a command. The id must name a bundled campaign YAML that exists in the
// runtime repo (see listScenarios); the command and its arguments are fixed here and started with spawn() and an argument array, no shell.
import { execFile, spawn as nodeSpawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** Display labels of the known campaigns, by canonical name (= file name of services/fault-injector/fault_injector/campaigns/<id>.yaml). */
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
  transport_duplicate: "Transport Duplicate",
  transport_reorder: "Transport Reorder",
  sensor_spike_cell2: "Sensor Spike — Cell 2",
  reorder_during_runaway: "Reorder During Runaway",
  heartbeat_duplicate_reorder: "Heartbeat Duplicate / Reorder",
  dfm_write_delay: "DFM Write Delay",
  opensovd_partial_visibility: "OpenSOVD Partial Visibility",
});
const SAFE_ID = /^[a-z][a-z0-9_]{0,63}$/;
const humanize = (id) => id.split("_").map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");

const CAMPAIGN_DIR = ["services", "fault-injector", "fault_injector", "campaigns"];
const COMPOSE_FILE = path.join("infra", "docker-compose.yml");
const MAX_BODY = 1024;
const MAX_TAIL = 2000;

/** Containers started by the dashboard: this name pattern and label are the only thing stop ever touches. */
export const CONTAINER_PREFIX = "rom-dashboard-campaign-";
export const CAMPAIGN_LABEL = "rom.dashboard.campaign";
const CONTAINER_NAME = /^rom-dashboard-campaign-[a-z0-9_]+-[0-9a-f]{6}$/;
export const isCampaignContainer = (name) => typeof name === "string" && CONTAINER_NAME.test(name);

/** The argv of `make campaign C=<id>` (Makefile: $(DC) --profile tools run --rm -T fault-injector ...), plus a name and a label. */
export function campaignCommand(id, container) {
  return {
    command: "docker",
    args: ["compose", "-f", COMPOSE_FILE, "--profile", "tools", "run", "--rm", "-T", "--name", container, "--label", `${CAMPAIGN_LABEL}=${id}`,
      "fault-injector", "rom-fault-injector", "run", id],
  };
}

export const defaultRuntimeRepo = () => process.env.ROM_RUNTIME_REPO || fileURLToPath(new URL("../../..", import.meta.url));
const defaultHealthUrl = () => `${(process.env.EVIDENCE_API_TARGET || "http://localhost:8082").replace(/\/$/, "")}/health`;

/**
 * The scenarios on offer = the bundled campaign definitions that really exist in the runtime repo (<id>.yaml, a plain
 * [a-z0-9_] name, so nothing else can reach the command line). Known ones come first with their label, a campaign added
 * later appears with a label made from its name. If the folder cannot be read, only the known ones are offered.
 */
export function listScenarios(runtimeRepo) {
  let names = null;
  try {
    names = fs.readdirSync(path.join(runtimeRepo, ...CAMPAIGN_DIR)).filter((f) => f.endsWith(".yaml")).map((f) => f.slice(0, -5)).filter((id) => SAFE_ID.test(id));
  } catch {
    names = null;
  }
  if (!names) return Object.entries(SCENARIOS).map(([id, label]) => ({ id, label }));
  const have = new Set(names);
  const known = Object.keys(SCENARIOS).filter((id) => have.has(id));
  const extra = names.filter((id) => !Object.hasOwn(SCENARIOS, id)).sort();
  return [...known, ...extra].map((id) => ({ id, label: SCENARIOS[id] ?? humanize(id) }));
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

/** Plain `docker <args>` for the short stop / cleanup commands: resolves {code, stdout}, never rejects. */
function dockerExec(args, { timeoutMs = 15000 } = {}) {
  return new Promise((resolve) => {
    execFile("docker", args, { timeout: timeoutMs, shell: false }, (err, stdout) => {
      resolve({ code: err ? (typeof err.code === "number" ? err.code : 1) : 0, stdout: String(stdout || "") });
    });
  });
}

const sleepMs = (ms) => new Promise((r) => setTimeout(r, ms));

/** The controller behind the routes; options are injectable so tests never touch Docker. */
export function createScenarioRunner({
  runtimeRepo = defaultRuntimeRepo(),
  healthUrl = defaultHealthUrl(),
  spawn = nodeSpawn,
  docker = dockerExec,
  fetchFn = fetch,
  now = () => new Date().toISOString(),
  graceMs = 5000,
  newId = () => crypto.randomBytes(3).toString("hex"),
} = {}) {
  let state = { status: "idle" };
  // Not part of the public state: the process handle and what stop() waits for.
  let current = null; // {child, container, exited: Promise, markExited}

  const publicState = () => {
    const { container, ...rest } = state; // the container name stays server-side
    return rest;
  };

  /** Sets the terminal state once, from whichever of close / error / adoption sees the end first. */
  const finish = (exitCode, error) => {
    if (state.status !== "running" && state.status !== "stopping") return;
    const base = { scenario: state.scenario, startedAt: state.startedAt, finishedAt: now(), container: state.container };
    if (state.status === "stopping") {
      state = { status: "stopped", ...base, exitCode: null, ...(state.note ? { note: state.note } : {}) };
    } else {
      state = { status: exitCode === 0 ? "completed" : "failed", ...base, exitCode, ...(exitCode === 0 ? {} : { error: error || "" }) };
    }
    current?.markExited();
  };

  const run = async (id) => {
    if (typeof id !== "string" || !listScenarios(runtimeRepo).some((s) => s.id === id)) {
      return { code: 400, body: { error: "Unknown scenario" } };
    }
    if (state.status === "running" || state.status === "stopping") {
      return { code: 409, body: { error: `A scenario is already ${state.status}`, scenario: state.scenario } };
    }
    // Claim the slot before the first await: two requests in the same tick must not both pass.
    const container = `${CONTAINER_PREFIX}${id}-${newId()}`;
    state = { status: "running", scenario: id, startedAt: now(), container };
    const unhealthy = await checkHealth(healthUrl, fetchFn);
    if (unhealthy) {
      state = { status: "idle" };
      return { code: 503, body: { error: "Runtime stack is not healthy", detail: unhealthy } };
    }
    const { command, args } = campaignCommand(id, container);
    let tail = "";
    const keep = (chunk) => {
      tail = (tail + chunk.toString()).slice(-MAX_TAIL);
    };
    let markExited;
    const exited = new Promise((r) => (markExited = r));
    current = { child: null, container, exited, markExited };
    const end = (code, error) => finish(code, error || tail.trim().split("\n").slice(-3).join("\n"));
    try {
      const child = spawn(command, args, { cwd: runtimeRepo, stdio: ["ignore", "pipe", "pipe"], shell: false });
      current.child = child;
      child.stdout?.on("data", keep);
      child.stderr?.on("data", keep);
      let done = false;
      child.on("error", (e) => {
        if (!done) {
          done = true;
          end(-1, `could not start: ${e.message}`);
        }
      });
      child.on("close", (code, signal) => {
        if (!done) {
          done = true;
          end(code ?? -1, signal ? `terminated by ${signal}` : undefined);
        }
      });
    } catch (e) {
      end(-1, `could not start: ${e instanceof Error ? e.message : e}`);
    }
    return { code: 202, body: { status: "running", scenario: id } };
  };

  const waitExit = (ms) => Promise.race([current.exited.then(() => true), sleepMs(ms).then(() => false)]);

  /** Escalation, bounded: SIGINT to the campaign container -> (grace) -> SIGKILL of it -> rm -f -> last resort the CLI child. */
  const terminate = async (cur) => {
    const { container } = cur;
    if (!isCampaignContainer(container)) return; // never act on anything that is not ours
    const sig = await docker(["kill", "--signal=SIGINT", container]);
    if (sig.code !== 0) cur.child?.kill?.("SIGINT"); // no such container (yet): ask the compose CLI that started it
    if (await waitExit(graceMs)) return;
    state = { ...state, note: "did not stop on SIGINT within the grace period: killed; faults it injected are cleared by the next campaign start" };
    await docker(["kill", container]);
    cur.child?.kill?.("SIGKILL");
    if (!(await waitExit(3000))) {
      await docker(["rm", "-f", container]);
      finish(null); // the CLI never reported back: do not stay "stopping" forever
      return;
    }
    await docker(["rm", "-f", container]); // --rm normally did it already; no-op error if so
  };

  const stop = async () => {
    if (state.status === "stopping") return { code: 409, body: { error: "The scenario is already stopping", status: "stopping", scenario: state.scenario } };
    if (state.status !== "running" || !current) return { code: 409, body: { error: "No scenario is currently running" } };
    state = { ...state, status: "stopping" };
    const cur = current;
    void terminate(cur).catch(() => finish(null));
    return { code: 202, body: { status: "stopping", scenario: state.scenario } };
  };

  /** After a dev-server restart: pick up a campaign container this dashboard started earlier (label + name pattern only). */
  const adopt = async () => {
    if (state.status !== "idle") return;
    const out = await docker(["ps", "--filter", `label=${CAMPAIGN_LABEL}`, "--format", `{{.Names}} {{.Label "${CAMPAIGN_LABEL}"}}`]);
    if (out.code !== 0) return;
    const found = out.stdout.split("\n").map((l) => l.trim().split(" ")).find(([n, id]) => isCampaignContainer(n) && listScenarios(runtimeRepo).some((x) => x.id === id));
    if (!found || state.status !== "idle") return;
    const [container, id] = found;
    let markExited;
    current = { child: null, container, exited: new Promise((r) => (markExited = r)), markExited };
    state = { status: "running", scenario: id, startedAt: now(), container };
    void docker(["wait", container], { timeoutMs: 3600000 }).then((w) => finish(w.code === 0 ? Number.parseInt(w.stdout, 10) || 0 : -1, w.code === 0 ? "" : "lost track of the container"));
  };

  return { run, stop, adopt, status: publicState, list: () => listScenarios(runtimeRepo) };
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
    if (url !== "/run" && url !== "/stop") return next();
    if (method !== "POST") return send(res, 405, { error: "Method not allowed" });
    // A page of another origin must not be able to start campaigns: browsers always send Origin on a cross-origin POST.
    const origin = req.headers.origin;
    if (origin && new URL(origin).host !== req.headers.host) return send(res, 403, { error: "Cross-origin request refused" });
    if (url === "/stop") {
      const out = await runner.stop();
      return send(res, out.code, out.body);
    }
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
  if (!options.spawn) void runner.adopt().catch(() => {}); // a dev-server restart must not lose track of a running campaign
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
