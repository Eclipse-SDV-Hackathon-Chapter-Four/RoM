// Made with Claude (Claude Code, Anthropic)
import assert from "node:assert/strict";
import test from "node:test";
import { createCellSource } from "./cell-source.mjs";

/** Fake simulator + adapter; records every POST in order. */
function fake({ cells = [1, 2, 3, 4], enabled = false, adapter = true } = {}) {
  const state = { cells, enabled };
  const posts = [];
  const fetchFn = async (url, opts = {}) => {
    const body = opts.body ? JSON.parse(opts.body) : undefined;
    const ok = (b) => ({ ok: true, status: 200, json: async () => b });
    if (url.endsWith("/cells")) {
      if (body) (posts.push(["sim", body.cells]), (state.cells = body.cells));
      return ok({ cells: state.cells });
    }
    if (!adapter) throw new Error("connection refused");
    if (body) (posts.push(["adapter", body.enabled]), (state.enabled = body.enabled));
    return ok({ enabled: state.enabled });
  };
  return { source: createCellSource({ simUrl: "http://sim", adapterUrl: "http://adapter", fetchFn }), posts };
}

test("modes: sim, hw, both (two writers) and no adapter", async () => {
  assert.equal((await fake().source.get()).mode, "sim");
  assert.equal((await fake({ cells: [2, 3, 4], enabled: true }).source.get()).mode, "hw");
  assert.equal((await fake({ enabled: true }).source.get()).mode, "both");
  const none = await fake({ adapter: false }).source.get();
  assert.equal(none.mode, "sim");
  assert.equal(none.hwAvailable, false);
});

test("to hw: the simulator lets go of cell 1 before the adapter writes", async () => {
  const { source, posts } = fake();
  assert.equal((await source.set("hw")).mode, "hw");
  assert.deepEqual(posts, [["sim", [2, 3, 4]], ["adapter", true]]);
});

test("to sim: the adapter stops before the simulator takes cell 1; a 'both' state is repaired", async () => {
  const { source, posts } = fake({ enabled: true });
  assert.equal((await source.set("sim")).mode, "sim");
  assert.deepEqual(posts, [["adapter", false], ["sim", [1, 2, 3, 4]]]);
});

test("hw without an adapter is refused and changes nothing", async () => {
  const { source, posts } = fake({ adapter: false });
  await assert.rejects(source.set("hw"), (e) => e.code === 503);
  await assert.rejects(source.set("x"), (e) => e.code === 422);
  assert.deepEqual(posts, []);
});
