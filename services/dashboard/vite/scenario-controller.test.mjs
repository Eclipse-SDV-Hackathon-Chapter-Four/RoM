// node --test vite/   Browser-side state machine of the scenario control (src/data/scenarioApi.ts, run by Node's type stripping).
import assert from "node:assert/strict";
import test from "node:test";
import { ScenarioController } from "../src/data/scenarioApi.ts";

const LIST = [{ id: "thermal_runaway", label: "Thermal Runaway" }, { id: "transport_drop", label: "Transport Drop" }];
const reply = (status, body) => ({ ok: status < 400, status, json: async () => body });

/** A fake server: records calls, status is whatever the test sets. */
function fakeServer({ runReply = reply(202, {}), initial = { status: "idle" } } = {}) {
  const s = { calls: [], status: initial, runReply };
  s.fetch = async (url, init = {}) => {
    s.calls.push({ url, method: init.method || "GET", body: init.body });
    if (url.endsWith("/status")) return reply(200, s.status);
    if (url.endsWith("/run")) return s.runReply;
    return reply(200, { scenarios: LIST });
  };
  return s;
}
const tick = (ms = 15) => new Promise((r) => setTimeout(r, ms));
const ctl = (srv, finished) => new ScenarioController("/api/scenarios", srv.fetch, 5, finished);

test("the scenario list is loaded and the first demo scenario is preselected", async () => {
  const srv = fakeServer();
  const c = ctl(srv);
  await c.init();
  assert.deepEqual(c.getState().scenarios, LIST);
  assert.equal(c.getState().selected, "thermal_runaway");
  assert.equal(c.getState().busy, false);
  assert.ok(!srv.calls.some((x) => x.method === "POST"), "nothing is started on load");
  c.dispose();
});

test("Run sends the selected canonical id", async () => {
  const srv = fakeServer();
  const c = ctl(srv);
  await c.init();
  c.select("transport_drop");
  await c.run();
  const post = srv.calls.find((x) => x.method === "POST");
  assert.equal(post.url, "/api/scenarios/run");
  assert.deepEqual(JSON.parse(post.body), { scenario: "transport_drop" });
  c.dispose();
});

test("controls are disabled while running, a second run does nothing, polling ends on completion", async () => {
  const srv = fakeServer();
  let finished = null;
  const c = ctl(srv, (s) => (finished = s));
  await c.init();
  srv.status = { status: "running", scenario: "thermal_runaway" };
  const first = c.run();
  const second = c.run(); // same tick
  await Promise.all([first, second]);
  assert.equal(srv.calls.filter((x) => x.method === "POST").length, 1);
  assert.equal(c.getState().busy, true);
  c.select("transport_drop");
  assert.equal(c.getState().selected, "thermal_runaway", "selector locked while busy");
  await c.run();
  assert.equal(srv.calls.filter((x) => x.method === "POST").length, 1, "button locked while busy");
  await tick();
  assert.equal(c.getState().busy, true, "still running");
  srv.status = { status: "completed", scenario: "thermal_runaway", exitCode: 0 };
  await tick();
  assert.equal(c.getState().busy, false);
  assert.equal(c.getState().status.status, "completed");
  assert.equal(finished.exitCode, 0);
  const n = srv.calls.length;
  await tick(30);
  assert.equal(srv.calls.length, n, "no polling after completion");
  c.dispose();
});

test("a failed execution is shown with its exit code", async () => {
  const srv = fakeServer();
  const c = ctl(srv);
  await c.init();
  await c.run();
  srv.status = { status: "failed", scenario: "thermal_runaway", exitCode: 2, error: "simulator not reachable" };
  await tick();
  const st = c.getState().status;
  assert.equal(st.status, "failed");
  assert.equal(st.exitCode, 2);
  assert.equal(c.getState().busy, false);
  c.dispose();
});

test("a refusal (409 / 503) shows the server's message and unlocks the controls", async () => {
  const srv = fakeServer({ runReply: reply(503, { error: "Runtime stack is not healthy", detail: "Guardian is DEGRADED, not MONITORING" }) });
  const c = ctl(srv);
  await c.init();
  await c.run();
  assert.match(c.getState().error, /not healthy: Guardian is DEGRADED/);
  assert.equal(c.getState().busy, false);
  c.dispose();
});

test("a page opened during a run picks the run up and keeps polling", async () => {
  const srv = fakeServer({ initial: { status: "running", scenario: "transport_drop" } });
  const c = ctl(srv);
  await c.init();
  assert.equal(c.getState().busy, true);
  assert.equal(c.getState().selected, "transport_drop");
  c.dispose();
});

test("no scenario API (static build) is reported, not faked", async () => {
  const c = new ScenarioController("/api/scenarios", async () => reply(404, {}), 5);
  await c.init();
  assert.equal(c.getState().unavailable, true);
  assert.deepEqual(c.getState().scenarios, []);
  c.dispose();
});
