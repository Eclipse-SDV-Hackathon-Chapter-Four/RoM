// node --test vite/   Everything runs on temporary directories created and removed here, never on the repo's runs/.
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import zlib from "node:zlib";
import plugin, { ensureBundle, extractZip, isTimestampName, readZipEntries, resolveEvidence, selectRun, verifyManifest } from "./evidence-report.mjs";

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "rom-evidence-test-"));
const crc = (b) => zlib.crc32?.(b) ?? (() => { let c = 0xffffffff; for (const x of b) { c ^= x; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; } return (c ^ 0xffffffff) >>> 0; })();

/** Minimal zip writer (deflate or stored), the same layout Python's zipfile produces for bundle.py. */
function makeZip(files, { stored = false, badCrc = false } = {}) {
  const locals = [], central = [];
  let offset = 0;
  for (const [name, text] of Object.entries(files)) {
    const data = Buffer.from(text), nameB = Buffer.from(name), method = stored ? 0 : 8;
    const comp = stored ? data : zlib.deflateRawSync(data);
    const c = badCrc ? 1234 : crc(data);
    const lh = Buffer.alloc(30); lh.writeUInt32LE(0x04034b50, 0); lh.writeUInt16LE(20, 4); lh.writeUInt16LE(method, 8);
    lh.writeUInt32LE(c, 14); lh.writeUInt32LE(comp.length, 18); lh.writeUInt32LE(data.length, 22); lh.writeUInt16LE(nameB.length, 26);
    const ch = Buffer.alloc(46); ch.writeUInt32LE(0x02014b50, 0); ch.writeUInt16LE(20, 4); ch.writeUInt16LE(20, 6); ch.writeUInt16LE(method, 10);
    ch.writeUInt32LE(c, 16); ch.writeUInt32LE(comp.length, 20); ch.writeUInt32LE(data.length, 24); ch.writeUInt16LE(nameB.length, 28); ch.writeUInt32LE(offset, 42);
    locals.push(lh, nameB, comp); central.push(ch, nameB);
    offset += 30 + nameB.length + comp.length;
  }
  const cd = Buffer.concat(central);
  const eocd = Buffer.alloc(22); eocd.writeUInt32LE(0x06054b50, 0); eocd.writeUInt16LE(Object.keys(files).length, 8); eocd.writeUInt16LE(Object.keys(files).length, 10);
  eocd.writeUInt32LE(cd.length, 12); eocd.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, cd, eocd]);
}
const sha = (t) => crypto.createHash("sha256").update(t).digest("hex");
function bundleFiles(report = "<html>REPORT</html>", extra = {}) {
  const files = { "report.html": report, "evidence/a.json": "{}", "events.jsonl": "", "safety_case.yaml": "x: 1", ...extra };
  return { ...files, "manifest.json": JSON.stringify({ files: Object.fromEntries(Object.entries(files).map(([n, t]) => [n, sha(t)])) }) };
}
function makeRun(runs, id, { evidence = [{ verdict: "PASS" }], zipFiles = bundleFiles(), summary = null, skip = [] } = {}) {
  const dir = path.join(runs, id); fs.mkdirSync(dir, { recursive: true });
  const w = (n, c) => !skip.includes(n) && fs.writeFileSync(path.join(dir, n), c);
  w("evidence.json", typeof evidence === "string" ? evidence : JSON.stringify(evidence));
  w("summary.json", JSON.stringify(summary ?? { total: Array.isArray(evidence) ? evidence.length : 0 }));
  w("evidence-bundle.zip", Buffer.isBuffer(zipFiles) ? zipFiles : makeZip(zipFiles));
  return dir;
}

test("isTimestampName accepts real YYYYMMDD-HHMMSS only", () => {
  for (const ok of ["20261007-153632", "20260101-000000"]) assert.equal(isTimestampName(ok), true, ok);
  for (const bad of ["try2", "try3", "20261307-153632", "20261007-256000", "99999999-999999", "20261007-1536", "2026-10-07", "20260230-101010"]) assert.equal(isTimestampName(bad), false, bad);
});

test("selectRun: missing runs/ and empty runs/", () => {
  const root = tmp();
  assert.equal(selectRun(path.join(root, "runs")).status, "no_runs_dir");
  fs.mkdirSync(path.join(root, "runs"));
  assert.equal(selectRun(path.join(root, "runs")).status, "no_valid_run");
  fs.rmSync(root, { recursive: true });
});

test("selectRun: incomplete runs are never candidates, try2/try3 do not beat a timestamp run", () => {
  const runs = tmp();
  makeRun(runs, "20261007-100000");
  makeRun(runs, "20261007-153632");                       // newest complete timestamp run
  makeRun(runs, "20261008-090000", { skip: ["evidence-bundle.zip"] }); // newer but incomplete
  makeRun(runs, "20261009-090000", { skip: ["summary.json"] });
  makeRun(runs, "try2"); makeRun(runs, "try3");           // complete, but lexically last
  fs.mkdirSync(path.join(runs, "empty"));
  fs.writeFileSync(path.join(runs, "stray-file.txt"), "x");
  const sel = selectRun(runs);
  assert.equal(sel.run.id, "20261007-153632"); assert.equal(sel.run.kind, "timestamp");
  fs.rmSync(runs, { recursive: true });
});

test("selectRun: fallback only when no complete timestamp run, zero-byte artifact is not complete", () => {
  const runs = tmp();
  makeRun(runs, "20261007-120000", { skip: ["summary.json"] });
  const old = makeRun(runs, "try2"); const newer = makeRun(runs, "try3");
  fs.utimesSync(path.join(old, "evidence-bundle.zip"), new Date(2020, 0, 1), new Date(2020, 0, 1));
  fs.utimesSync(path.join(newer, "evidence-bundle.zip"), new Date(2021, 0, 1), new Date(2021, 0, 1));
  assert.deepEqual([selectRun(runs).run.id, selectRun(runs).run.kind], ["try3", "fallback"]);
  fs.writeFileSync(path.join(newer, "evidence.json"), ""); // empty file: try3 is no longer complete
  assert.equal(selectRun(runs).run.id, "try2");
  fs.rmSync(runs, { recursive: true });
});

test("zip: deflate and stored round trip, safe extraction", () => {
  for (const stored of [false, true]) {
    const root = tmp(); const zip = path.join(root, "b.zip"); fs.writeFileSync(zip, makeZip({ "report.html": "<p>hi</p>", "evidence/x.json": '{"a":1}' }, { stored }));
    extractZip(zip, path.join(root, "out"));
    assert.equal(fs.readFileSync(path.join(root, "out/report.html"), "utf8"), "<p>hi</p>");
    assert.equal(fs.readFileSync(path.join(root, "out/evidence/x.json"), "utf8"), '{"a":1}');
    fs.rmSync(root, { recursive: true });
  }
});

test("zip: path traversal, corrupt and non-zip input are rejected", () => {
  const root = tmp(); const out = path.join(root, "out");
  for (const name of ["../evil.txt", "/abs.txt", "a/../../evil.txt", "a\\b.txt"]) {
    fs.writeFileSync(path.join(root, "b.zip"), makeZip({ [name]: "x" }));
    assert.throws(() => extractZip(path.join(root, "b.zip"), out), /unsafe path/, name);
    assert.equal(fs.existsSync(path.join(root, "evil.txt")), false);
  }
  fs.writeFileSync(path.join(root, "bad.zip"), makeZip({ "report.html": "x" }, { badCrc: true }));
  assert.throws(() => extractZip(path.join(root, "bad.zip"), out), /checksum mismatch/);
  assert.throws(() => readZipEntries(Buffer.from("this is not a zip file at all, really")), /not a zip/);
  fs.rmSync(root, { recursive: true });
});

test("resolveEvidence: counts come from the real evidence.json", () => {
  const runs = tmp();
  makeRun(runs, "20261007-153632", { evidence: [{ verdict: "PASS" }, { verdict: "PASS" }, { verdict: "FAIL" }, { verdict: "INCONCLUSIVE" }, { verdict: "constructor" }], summary: { total: 5 } });
  const { meta, reportPath } = resolveEvidence(runs);
  assert.deepEqual({ ...meta }, { available: true, runId: "20261007-153632", campaigns: 5, pass: 2, fail: 1, inconclusive: 1, other: 1, summaryAgrees: true, manifest: "verified", reportUrl: "/evidence-report/report.html" });
  assert.equal(fs.readFileSync(reportPath, "utf8"), "<html>REPORT</html>");
  assert.ok(!JSON.stringify(meta).includes(runs), "meta must not leak filesystem paths");
  fs.rmSync(runs, { recursive: true });
});

test("resolveEvidence: each error state is reported separately, never as mock data", () => {
  const runs = tmp(); const status = () => resolveEvidence(runs).meta;
  assert.equal(resolveEvidence(path.join(runs, "nope")).meta.status, "no_runs_dir");
  assert.equal(status().status, "no_valid_run");
  const bad = makeRun(runs, "20261007-100000", { evidence: "{ not json" });
  assert.deepEqual([status().status, status().runId, /invalid JSON/.test(status().message)], ["invalid_evidence", "20261007-100000", true]);
  fs.writeFileSync(path.join(bad, "evidence.json"), "[]"); assert.equal(status().status, "invalid_evidence");
  fs.writeFileSync(path.join(bad, "evidence.json"), '[{"nothing":1}]'); assert.equal(status().status, "invalid_evidence");
  fs.writeFileSync(path.join(bad, "evidence.json"), '{"verdict":"PASS"}'); assert.equal(status().status, "invalid_evidence");
  fs.writeFileSync(path.join(bad, "evidence.json"), '[{"verdict":"PASS"}]'); fs.writeFileSync(path.join(bad, "evidence-bundle.zip"), "garbage, not a zip");
  assert.deepEqual([status().status, /could not be extracted/.test(status().message)], ["extract_failed", true]);
  fs.writeFileSync(path.join(bad, "evidence-bundle.zip"), makeZip({ "manifest.json": "{}" }));
  assert.equal(status().status, "report_missing");
  fs.writeFileSync(path.join(bad, "evidence-bundle.zip"), makeZip({ "report.html": "" }));
  assert.equal(status().status, "report_missing"); // empty report counts as missing
  fs.rmSync(runs, { recursive: true });
});

test("resolveEvidence: a newer run with bad evidence is an error, an older good run is not silently shown", () => {
  const runs = tmp();
  makeRun(runs, "20261007-100000"); makeRun(runs, "20261007-110000", { evidence: "garbage" });
  const m = resolveEvidence(runs).meta;
  assert.deepEqual([m.available, m.status, m.runId], [false, "invalid_evidence", "20261007-110000"]);
  fs.rmSync(runs, { recursive: true });
});

test("manifest verification and re-extraction when the zip is newer", () => {
  const runs = tmp(); const dir = makeRun(runs, "20261007-153632");
  const { bundle, report } = ensureBundle({ id: "x", dir });
  assert.equal(verifyManifest(bundle), "verified");
  fs.writeFileSync(report, "<html>TAMPERED</html>"); // newer than the zip: kept, but the manifest no longer matches
  assert.equal(ensureBundle({ id: "x", dir }).report, report);
  assert.equal(fs.readFileSync(report, "utf8"), "<html>TAMPERED</html>");
  assert.equal(verifyManifest(bundle), "mismatch");
  const future = new Date(Date.now() + 60_000); fs.utimesSync(path.join(dir, "evidence-bundle.zip"), future, future); // replaced bundle
  ensureBundle({ id: "x", dir });
  assert.equal(fs.readFileSync(report, "utf8"), "<html>REPORT</html>");
  assert.equal(verifyManifest(bundle), "verified");
  fs.rmSync(path.join(bundle, "manifest.json")); assert.equal(verifyManifest(bundle), "absent");
  fs.rmSync(runs, { recursive: true });
});

test("HTTP routes: meta.json, report.html with CSP, nothing else is served", async () => {
  const runs = tmp(); makeRun(runs, "20261007-153632", { evidence: [{ verdict: "PASS" }] });
  let handler; plugin({ runsDir: runs }).configureServer({ middlewares: { use: (_base, fn) => (handler = fn) } });
  const server = http.createServer((req, res) => handler(req, res, () => { res.statusCode = 418; res.end("next"); }));
  await new Promise((r) => server.listen(0, "127.0.0.1", r)); const port = server.address().port;
  const get = async (p, method = "GET") => { const r = await fetch(`http://127.0.0.1:${port}${p}`, { method }); return { status: r.status, headers: r.headers, text: await r.text() }; };
  const meta = await get("/meta.json"); assert.equal(meta.status, 200); assert.equal(JSON.parse(meta.text).campaigns, 1);
  assert.match(meta.headers.get("cache-control"), /no-store/);
  const rep = await get("/report.html"); assert.equal(rep.text, "<html>REPORT</html>");
  assert.match(rep.headers.get("content-type"), /text\/html/); assert.match(rep.headers.get("content-security-policy"), /default-src 'none'/);
  assert.equal((await get("/../../etc/passwd")).status, 418); assert.equal((await get("/evidence.json")).status, 418); assert.equal((await get("/bundle/manifest.json")).status, 418);
  assert.equal((await get("/meta.json", "POST")).status, 405);
  fs.rmSync(path.join(runs, "20261007-153632"), { recursive: true });
  const none = await get("/report.html"); assert.equal(none.status, 404); assert.equal(JSON.parse((await get("/meta.json")).text).available, false);
  server.close(); fs.rmSync(runs, { recursive: true });
});
