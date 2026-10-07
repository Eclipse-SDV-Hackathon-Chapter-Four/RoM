// node --test vite/   Server side of the scenario control. Never starts Docker: spawn and the health check are fakes.
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import plugin, { SCENARIOS, campaignCommand, createScenarioRunner, listScenarios } from "./scenarios.mjs";

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
    calls.push({ command, args, opts, child });
    return child;
  };
  return { spawn, calls };
}
const mk = (over = {}) => {
  const f = fakeSpawn();
  const runtimeRepo = repo();
  return { ...f, runtimeRepo, runner: createScenarioRunner({ runtimeRepo, spawn: f.spawn, fetchFn: healthy, ...over }) };
};

test("the command is exactly the Makefile's single-campaign command, as an argument array", () => {
  assert.deepEqual(campaignCommand("thermal_runaway"), {
    command: "docker",
    args: ["compose", "-f", "infra/docker-compose.yml", "--profile", "tools", "run", "--rm", "-T", "fault-injector", "rom-fault-injector", "run", "thermal_runaway"],
  });
});

test("lists the 15 bundled campaigns, and drops ones whose YAML is missing in the runtime repo", () => {
  const dir = repo();
  assert.equal(listScenarios(dir).length, 15);
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
    assert.equal((await (await fetch(base)).json()).scenarios.length, 15);
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
