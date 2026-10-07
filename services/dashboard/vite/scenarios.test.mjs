// node --test vite/   Server side of the scenario control. Never starts Docker: spawn and the health check are fakes.
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import plugin, { SCENARIOS, campaignCommand, createScenarioRunner, isCampaignContainer, listScenarios } from "./scenarios.mjs";

const repo = () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rom-scn-"));
  const camp = path.join(dir, "services/fault-injector/fault_injector/campaigns");
  fs.mkdirSync(camp, { recursive: true });
  for (const id of Object.keys(SCENARIOS)) fs.writeFileSync(path.join(camp, `${id}.yaml`), "name: x\n");
  return dir;
};
const healthy = async () => ({ ok: true, json: async () => ({ ok: true, guardian_state: "MONITORING", open_run: null }) });
function fakeSpawn() {
  const calls = [];
  const spawn = (command, args, opts) => {
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.kill = () => true; // like ChildProcess.kill
    calls.push({ command, args, opts, child });
    return child;
  };
  return { spawn, calls };
}
/** Fake `docker <args>`: records every call; `onKill(args)` may end the fake campaign process (SIGINT -> the injector cleans up and exits). */
function fakeDocker(handler = () => ({ code: 0, stdout: "" })) {
  const calls = [];
  return { calls, docker: async (args) => { calls.push(args); return handler(args); } };
}
const mk = (over = {}) => {
  const f = fakeSpawn();
  const d = fakeDocker(over.dockerHandler);
  const runtimeRepo = repo();
  const { dockerHandler, ...rest } = over;
  return { ...f, dockerCalls: d.calls, runtimeRepo, runner: createScenarioRunner({ runtimeRepo, spawn: f.spawn, docker: d.docker, fetchFn: healthy, graceMs: 40, newId: () => "a1b2c3", ...rest }) };
};

test("the command is the Makefile's single-campaign command plus a name and a label, as an argument array", () => {
  assert.deepEqual(campaignCommand("thermal_runaway", "rom-dashboard-campaign-thermal_runaway-a1b2c3"), {
    command: "docker",
    args: ["compose", "-f", "infra/docker-compose.yml", "--profile", "tools", "run", "--rm", "-T", "--name", "rom-dashboard-campaign-thermal_runaway-a1b2c3",
      "--label", "rom.dashboard.campaign=thermal_runaway", "fault-injector", "rom-fault-injector", "run", "thermal_runaway"],
  });
});

test("lists the bundled campaigns present in the runtime repo, drops missing ones, adds new ones, ignores unsafe file names", () => {
  const dir = repo();
  const camp = path.join(dir, "services/fault-injector/fault_injector/campaigns");
  assert.equal(listScenarios(dir).length, Object.keys(SCENARIOS).length);
  fs.writeFileSync(path.join(camp, "brand_new_case.yaml"), "x: 1\n");
  for (const bad of ["Bad Name.yaml", "x;rm.yaml", "UPPER.yaml", "1abc.yaml", ".hidden.yaml"]) fs.writeFileSync(path.join(camp, bad), "x: 1\n");
  const l = listScenarios(dir);
  assert.deepEqual(l.at(-1), { id: "brand_new_case", label: "Brand New Case" });
  assert.equal(l.length, Object.keys(SCENARIOS).length + 1, "unsafe names are never offered");
  fs.rmSync(path.join(dir, "services/fault-injector/fault_injector/campaigns/transport_drop.yaml"));
  assert.ok(!listScenarios(dir).some((s) => s.id === "transport_drop"));
});

test("arbitrary or malicious scenario ids are rejected and nothing is spawned", async () => {
  const { runner, calls } = mk();
  for (const bad of ["../../etc/passwd", "thermal_runaway; rm -rf /", "$(id)", "", "THERMAL_RUNAWAY", "__proto__", "constructor", "toString", 42, null, undefined, { a: 1 }]) {
    const out = await runner.run(bad);
    assert.equal(out.code, 400, String(bad));
  }
  assert.equal(calls.length, 0);
  assert.deepEqual(runner.status(), { status: "idle" });
});

test("a valid run spawns the fixed command in the runtime repo, without a shell", async () => {
  const { runner, calls, runtimeRepo } = mk();
  const out = await runner.run("transport_drop");
  assert.equal(out.code, 202);
  assert.deepEqual(out.body, { status: "running", scenario: "transport_drop" });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].command, "docker");
  assert.equal(calls[0].args.at(-1), "transport_drop");
  assert.ok(calls[0].args.includes("rom-dashboard-campaign-transport_drop-a1b2c3"), "the campaign container has a unique name");
  assert.ok(!("container" in runner.status()), "the container name stays server-side");
  assert.equal(calls[0].opts.cwd, runtimeRepo);
  assert.equal(calls[0].opts.shell, false);
  assert.equal(runner.status().status, "running");
});

test("a second run while one is active gets 409 (also when both arrive in the same tick)", async () => {
  const { runner, calls } = mk();
  const [a, b] = await Promise.all([runner.run("thermal_runaway"), runner.run("transport_drop")]);
  assert.deepEqual([a.code, b.code].sort(), [202, 409]);
  assert.equal(calls.length, 1);
  assert.equal((await runner.run("sensor_stuck")).code, 409);
});

test("exit 0 -> completed with exitCode, then a new run is allowed", async () => {
  const { runner, calls } = mk();
  await runner.run("thermal_runaway");
  calls[0].child.emit("close", 0, null);
  assert.equal(runner.status().status, "completed");
  assert.equal(runner.status().exitCode, 0);
  assert.equal((await runner.run("transport_drop")).code, 202);
});

test("non-zero exit -> failed with the exit code and the tail of the output", async () => {
  const { runner, calls } = mk();
  await runner.run("thermal_runaway");
  calls[0].child.stderr.emit("data", Buffer.from("error: simulator not reachable\n"));
  calls[0].child.emit("close", 2, null);
  const s = runner.status();
  assert.equal(s.status, "failed");
  assert.equal(s.exitCode, 2);
  assert.match(s.error, /simulator not reachable/);
});

test("a command that cannot start is reported as failed", async () => {
  const { runner, calls } = mk();
  await runner.run("thermal_runaway");
  calls[0].child.emit("error", new Error("spawn docker ENOENT"));
  assert.equal(runner.status().status, "failed");
  assert.match(runner.status().error, /ENOENT/);
});

test("unhealthy stack -> 503, nothing spawned, state back to idle", async () => {
  for (const fetchFn of [
    async () => { throw new Error("ECONNREFUSED"); },
    async () => ({ ok: false, status: 500 }),
    async () => ({ ok: true, json: async () => ({ ok: true, guardian_state: "DEGRADED", open_run: null }) }),
    async () => ({ ok: true, json: async () => ({ ok: true, guardian_state: "MONITORING", open_run: "x-01" }) }),
  ]) {
    const { runner, calls } = mk({ fetchFn });
    const out = await runner.run("thermal_runaway");
    assert.equal(out.code, 503);
    assert.equal(out.body.error, "Runtime stack is not healthy");
    assert.equal(calls.length, 0);
    assert.deepEqual(runner.status(), { status: "idle" });
  }
});

test("HTTP routes: list, status, run (400 / 202 / 409), cross-origin refused, wrong method", async () => {
  const { spawn } = fakeSpawn();
  const p = plugin({ runtimeRepo: repo(), spawn, fetchFn: healthy });
  let mw;
  p.configureServer({ middlewares: { use: (_base, fn) => (mw = fn) } });
  const srv = http.createServer((req, res) => {
    req.url = req.url.replace(/^\/api\/scenarios/, "") || "/";
    mw(req, res, () => { res.statusCode = 404; res.end(); });
  });
  await new Promise((r) => srv.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${srv.address().port}/api/scenarios`;
  const post = (body, headers = {}) => fetch(`${base}/run`, { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body });
  try {
    assert.equal((await (await fetch(base)).json()).scenarios.length, Object.keys(SCENARIOS).length);
    assert.deepEqual(await (await fetch(`${base}/status`)).json(), { status: "idle" });
    assert.equal((await post("not json")).status, 400);
    assert.equal((await post(JSON.stringify({ scenario: "rm -rf /" }))).status, 400);
    assert.equal((await post(JSON.stringify({ scenario: "thermal_runaway" }), { Origin: "http://evil.example" })).status, 403);
    assert.equal((await fetch(`${base}/run`)).status, 405);
    const ok = await post(JSON.stringify({ scenario: "thermal_runaway" }));
    assert.equal(ok.status, 202);
    assert.equal((await post(JSON.stringify({ scenario: "transport_drop" }))).status, 409);
    assert.equal((await (await fetch(`${base}/status`)).json()).status, "running");
  } finally {
    srv.close();
  }
});

// ---- stop ------------------------------------------------------------------------------------------------------------
const tick = (ms = 20) => new Promise((r) => setTimeout(r, ms));
const NAME = "rom-dashboard-campaign-sensor_stuck_cell3-a1b2c3";

test("stop with nothing running -> 409, no docker call", async () => {
  const { runner, dockerCalls } = mk();
  const out = await runner.stop();
  assert.equal(out.code, 409);
  assert.equal(out.body.error, "No scenario is currently running");
  assert.equal(dockerCalls.length, 0);
});

test("stop interrupts the exact campaign container with SIGINT, ends as 'stopped' (not completed / failed), exitCode null", async () => {
  let cur;
  const { runner, calls, dockerCalls } = mk({
    dockerHandler: (args) => {
      if (args[0] === "kill") setTimeout(() => cur.child.emit("close", 130, null), 5); // the injector clears its faults and exits
      return { code: 0, stdout: "" };
    },
  });
  await runner.run("sensor_stuck_cell3");
  cur = calls[0];
  const out = await runner.stop();
  assert.equal(out.code, 202);
  assert.deepEqual(out.body, { status: "stopping", scenario: "sensor_stuck_cell3" });
  assert.equal(runner.status().status, "stopping");
  await tick();
  assert.deepEqual(dockerCalls[0], ["kill", "--signal=SIGINT", NAME]);
  assert.ok(dockerCalls.every((c) => c.includes(NAME) || c[0] === "rm"), "nothing but the campaign container is addressed");
  const s = runner.status();
  assert.equal(s.status, "stopped");
  assert.equal(s.exitCode, null);
  assert.equal(s.scenario, "sensor_stuck_cell3");
  assert.ok(s.finishedAt);
  assert.ok(!dockerCalls.some((c) => c[0] === "kill" && c.length === 2), "no force kill when SIGINT was enough");
});

test("a second stop and a run while stopping are rejected with 409", async () => {
  const { runner, calls } = mk();
  await runner.run("sensor_stuck_cell3");
  assert.equal((await runner.stop()).code, 202);
  const again = await runner.stop();
  assert.equal(again.code, 409);
  assert.equal(again.body.status, "stopping");
  assert.equal((await runner.run("transport_drop")).code, 409);
  assert.equal(calls.length, 1);
});

test("if SIGINT is not enough, only that container is force-killed and removed afterwards", async () => {
  const { runner, calls, dockerCalls } = mk({
    dockerHandler: (args) => {
      if (args[0] === "kill" && args.length === 2) setTimeout(() => calls[0].child.emit("close", 137, null), 5); // SIGKILL ends it
      return { code: 0, stdout: "" };
    },
  });
  await runner.run("sensor_stuck_cell3");
  await runner.stop();
  await tick(120);
  assert.deepEqual(dockerCalls.slice(0, 2), [["kill", "--signal=SIGINT", NAME], ["kill", NAME]]);
  assert.deepEqual(dockerCalls.at(-1), ["rm", "-f", NAME]);
  assert.equal(runner.status().status, "stopped");
  assert.match(runner.status().note, /killed/);
});

test("when the container cannot be found the compose CLI process is signalled instead", async () => {
  const { runner, calls } = mk({ dockerHandler: (args) => (args[0] === "kill" ? { code: 1, stdout: "" } : { code: 0, stdout: "" }) });
  await runner.run("sensor_stuck_cell3");
  let signals = [];
  calls[0].child.kill = (sig) => { signals.push(sig); if (sig === "SIGINT") setTimeout(() => calls[0].child.emit("close", 130, null), 5); };
  await runner.stop();
  await tick();
  assert.equal(signals[0], "SIGINT");
  assert.equal(runner.status().status, "stopped");
});

test("stop racing a natural completion is deterministic and does not crash", async () => {
  const { runner, calls } = mk();
  await runner.run("sensor_stuck_cell3");
  calls[0].child.emit("close", 0, null); // finished first
  assert.equal((await runner.stop()).code, 409);
  assert.equal(runner.status().status, "completed");
  // stop accepted, then the process ends by itself with 0 before the signal lands: still reported as stopped, once
  await runner.run("transport_drop");
  await runner.stop();
  calls[1].child.emit("close", 0, null);
  calls[1].child.emit("close", 0, null);
  assert.equal(runner.status().status, "stopped");
});

test("a process that dies by itself is 'failed', not 'stopped'", async () => {
  const { runner, calls } = mk();
  await runner.run("sensor_stuck_cell3");
  calls[0].child.emit("close", 137, "SIGKILL");
  assert.equal(runner.status().status, "failed");
});

test("only containers named by this dashboard can be addressed; the API has no container argument", async () => {
  for (const bad of ["rom-fault-injector", "infra-guardian-1", "rom-dashboard-campaign-", "rom-dashboard-campaign-x; rm -rf /-a1b2c3", "../rom-dashboard-campaign-thermal_runaway-a1b2c3", "rom-dashboard-campaign-thermal_runaway-XYZ123", null, undefined, 7]) {
    assert.equal(isCampaignContainer(bad), false, String(bad));
  }
  assert.equal(isCampaignContainer(NAME), true);
  // stop() never takes input: whatever is in the request body cannot reach docker
  const { runner, dockerCalls } = mk();
  await runner.run("sensor_stuck_cell3");
  await runner.stop.call(null, { container: "infra-guardian-1" });
  await tick();
  assert.ok(dockerCalls.length > 0 && dockerCalls.every((c) => !c.includes("infra-guardian-1")));
  assert.ok(dockerCalls.every((c) => c.includes(NAME)));
});

test("a campaign container left by an earlier dev-server run is adopted (label + name only), others are ignored", async () => {
  const { runner, dockerCalls } = mk({
    dockerHandler: (args) => (args[0] === "ps"
      ? { code: 0, stdout: `infra-guardian-1 \nsomebody-elses-injector thermal_runaway\n${NAME} sensor_stuck_cell3\n` }
      : new Promise((r) => setTimeout(() => r({ code: 0, stdout: "0\n" }), 40))), // `docker wait` returns when the container ends
  });
  await runner.adopt();
  assert.equal(runner.status().status, "running");
  assert.equal(runner.status().scenario, "sensor_stuck_cell3");
  assert.equal((await runner.run("transport_drop")).code, 409);
  await tick(100);
  assert.deepEqual(dockerCalls.at(-1), ["wait", NAME]);
  assert.equal(runner.status().status, "completed");
});

test("HTTP: POST /stop with nothing running is 409, and ?container= is ignored", async () => {
  const f = fakeSpawn();
  const d = fakeDocker();
  const p = plugin({ runtimeRepo: repo(), spawn: f.spawn, docker: d.docker, fetchFn: healthy });
  let mw;
  p.configureServer({ middlewares: { use: (_b, fn) => (mw = fn) } });
  const srv = http.createServer((req, res) => { req.url = req.url.replace(/^\/api\/scenarios/, "") || "/"; mw(req, res, () => { res.statusCode = 404; res.end(); }); });
  await new Promise((r) => srv.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${srv.address().port}/api/scenarios`;
  try {
    const r = await fetch(`${base}/stop?container=infra-guardian-1`, { method: "POST" });
    assert.equal(r.status, 409);
    assert.equal((await r.json()).error, "No scenario is currently running");
    assert.equal((await fetch(`${base}/stop`)).status, 405);
    assert.equal(d.calls.length, 0);
  } finally { srv.close(); }
});
