// Development / hackathon integration: serves the Evidence Collector's generated report.html from a completed final run
// (runs/<id>/, written by scripts/final_run.sh) over HTTP, so the dashboard can embed it. Plain Node built-ins, no
// dependencies. The browser only ever sees two stable URLs; it never learns a filesystem path:
//
//   GET /evidence-report/meta.json     what is available (run id, campaign / PASS / FAIL / INCONCLUSIVE counts) or why not
//   GET /evidence-report/report.html   the generated report of the selected run (self-contained: inline CSS, no JS)
//
// A hosted deployment would replace this file with an artifact API that returns the same two documents.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";

/** A run is complete only with all three artifacts of scripts/final_run.sh. */
export const REQUIRED_FILES = ["evidence.json", "summary.json", "evidence-bundle.zip"];
const SAFE_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const TIMESTAMP = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/; // the default RUN_ID: date +%Y%m%d-%H%M%S
const MAX_ENTRIES = 5000;
const MAX_TOTAL_BYTES = 256 * 1024 * 1024;

/** True for a real YYYYMMDD-HHMMSS name (not just digits in that shape). */
export function isTimestampName(name) {
  const m = TIMESTAMP.exec(name);
  if (!m) return false;
  const [y, mo, d, h, mi, s] = m.slice(1).map(Number);
  const date = new Date(Date.UTC(y, mo - 1, d, h, mi, s));
  return y >= 2000 && date.getUTCFullYear() === y && date.getUTCMonth() === mo - 1 && date.getUTCDate() === d && h < 24 && mi < 60 && s < 60;
}

const isRegular = (p) => {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
};
/** A usable artifact: a regular file with content (an empty evidence.json / report.html proves nothing). */
const isFile = (p) => {
  try {
    const st = fs.statSync(p);
    return st.isFile() && st.size > 0;
  } catch {
    return false;
  }
};

/**
 * The run to show. Never "the last directory": try2 / try3 style folders must not win.
 *  1. child directories of runsDir that hold ALL required artifacts (incomplete runs are never candidates)
 *  2. timestamp-named ones first, newest first
 *  3. then any other complete directory, newest bundle first (fallback)
 * Returns {status: "no_runs_dir" | "no_valid_run" | "ok", run?: {id, dir, kind}}.
 */
export function selectRun(runsDir) {
  let entries;
  try {
    entries = fs.readdirSync(runsDir, { withFileTypes: true });
  } catch {
    return { status: "no_runs_dir" };
  }
  const complete = entries
    .filter((e) => e.isDirectory() && SAFE_NAME.test(e.name))
    .map((e) => ({ id: e.name, dir: path.join(runsDir, e.name) }))
    .filter((r) => REQUIRED_FILES.every((f) => isFile(path.join(r.dir, f))));
  const stamped = complete.filter((r) => isTimestampName(r.id)).sort((a, b) => (a.id < b.id ? 1 : -1));
  if (stamped.length) return { status: "ok", run: { ...stamped[0], kind: "timestamp" } };
  const others = complete
    .map((r) => ({ ...r, mtime: fs.statSync(path.join(r.dir, "evidence-bundle.zip")).mtimeMs }))
    .sort((a, b) => b.mtime - a.mtime);
  if (others.length) return { status: "ok", run: { id: others[0].id, dir: others[0].dir, kind: "fallback" } };
  return { status: "no_valid_run" };
}

// ---- zip (stored + deflate, no zip64, no encryption: what evidence_collector/bundle.py writes) ------------------------
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();
const crc32 = (buf) => {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
};

/** Lists the entries of a zip held in memory. Throws on anything it does not support. */
export function readZipEntries(buf) {
  let eocd = -1;
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 22 - 0xffff); i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error("not a zip file");
  const count = buf.readUInt16LE(eocd + 10);
  const cdOffset = buf.readUInt32LE(eocd + 16);
  if (count === 0xffff || cdOffset === 0xffffffff) throw new Error("zip64 is not supported");
  if (count > MAX_ENTRIES) throw new Error("too many entries in the zip");
  const entries = [];
  let p = cdOffset;
  for (let i = 0; i < count; i++) {
    if (buf.readUInt32LE(p) !== 0x02014b50) throw new Error("corrupt zip directory");
    const flags = buf.readUInt16LE(p + 8);
    if (flags & 1) throw new Error("encrypted zip entries are not supported");
    const nameLen = buf.readUInt16LE(p + 28);
    entries.push({
      name: buf.toString("utf8", p + 46, p + 46 + nameLen),
      method: buf.readUInt16LE(p + 10),
      crc: buf.readUInt32LE(p + 16),
      csize: buf.readUInt32LE(p + 20),
      usize: buf.readUInt32LE(p + 24),
      offset: buf.readUInt32LE(p + 42),
    });
    p += 46 + nameLen + buf.readUInt16LE(p + 30) + buf.readUInt16LE(p + 32);
  }
  return entries;
}

function entryData(buf, e) {
  if (buf.readUInt32LE(e.offset) !== 0x04034b50) throw new Error(`corrupt zip entry ${e.name}`);
  const start = e.offset + 30 + buf.readUInt16LE(e.offset + 26) + buf.readUInt16LE(e.offset + 28);
  const raw = buf.subarray(start, start + e.csize);
  let data;
  if (e.method === 0) data = Buffer.from(raw);
  else if (e.method === 8) data = zlib.inflateRawSync(raw, { maxOutputLength: e.usize + 1 });
  else throw new Error(`unsupported compression method ${e.method} for ${e.name}`);
  if (data.length !== e.usize || crc32(data) !== e.crc) throw new Error(`checksum mismatch for ${e.name}`);
  return data;
}

/** Entry name -> safe relative path, or null for names that could escape the target directory. */
function safeRelative(name) {
  if (!name || name.startsWith("/") || name.includes("\\") || name.includes(":") || name.includes("\0")) return null;
  const parts = name.split("/").filter((s) => s !== "" && s !== ".");
  return parts.length && !parts.includes("..") ? parts.join("/") : null;
}

/** Extracts zipPath into destDir (created fresh). Rejects path traversal, oversized and corrupt archives. */
export function extractZip(zipPath, destDir) {
  const buf = fs.readFileSync(zipPath);
  const entries = readZipEntries(buf);
  if (entries.reduce((n, e) => n + e.usize, 0) > MAX_TOTAL_BYTES) throw new Error("zip is too large");
  fs.rmSync(destDir, { recursive: true, force: true });
  fs.mkdirSync(destDir, { recursive: true });
  const root = path.resolve(destDir);
  for (const e of entries) {
    const rel = safeRelative(e.name);
    if (rel === null) throw new Error(`unsafe path in zip: ${e.name}`);
    const target = path.resolve(root, rel);
    if (!target.startsWith(root + path.sep)) throw new Error(`unsafe path in zip: ${e.name}`);
    if (e.name.endsWith("/")) {
      fs.mkdirSync(target, { recursive: true });
      continue;
    }
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, entryData(buf, e));
  }
}

/** Extracts runs/<id>/evidence-bundle.zip to runs/<id>/bundle/ unless that is already up to date. */
export function ensureBundle(run) {
  const zip = path.join(run.dir, "evidence-bundle.zip");
  const bundle = path.join(run.dir, "bundle");
  const report = path.join(bundle, "report.html");
  const upToDate = isFile(report) && fs.statSync(report).mtimeMs >= fs.statSync(zip).mtimeMs;
  if (!upToDate) {
    const tmp = path.join(run.dir, `bundle.tmp-${process.pid}`);
    try {
      extractZip(zip, tmp);
      fs.rmSync(bundle, { recursive: true, force: true });
      fs.renameSync(tmp, bundle);
    } catch (e) {
      fs.rmSync(tmp, { recursive: true, force: true });
      throw e;
    }
  }
  return { bundle, report };
}

/** Compares every file of the bundle with manifest.json (SHA-256). "absent" if there is no usable manifest. */
export function verifyManifest(bundleDir) {
  let manifest;
  try {
    manifest = JSON.parse(fs.readFileSync(path.join(bundleDir, "manifest.json"), "utf8"));
  } catch {
    return "absent";
  }
  const files = manifest && typeof manifest.files === "object" ? manifest.files : null;
  if (!files || !Object.keys(files).length) return "absent";
  for (const [name, sha] of Object.entries(files)) {
    const rel = safeRelative(name);
    if (rel === null) return "mismatch";
    const p = path.join(bundleDir, rel);
    if (!isRegular(p) || crypto.createHash("sha256").update(fs.readFileSync(p)).digest("hex") !== sha) return "mismatch";
  }
  return "verified";
}

/** Counts from the run's real evidence.json. Throws a readable Error if the file is not usable. */
export function summarizeEvidence(runDir) {
  let records;
  try {
    records = JSON.parse(fs.readFileSync(path.join(runDir, "evidence.json"), "utf8"));
  } catch (e) {
    throw new Error(`evidence.json cannot be read (${e instanceof SyntaxError ? "invalid JSON" : "unreadable"})`);
  }
  if (!Array.isArray(records)) throw new Error("evidence.json is not a list of evidence records");
  if (records.length === 0) throw new Error("evidence.json contains no evidence records");
  const counts = { PASS: 0, FAIL: 0, INCONCLUSIVE: 0, other: 0 };
  for (const r of records) {
    if (typeof r !== "object" || r === null || typeof r.verdict !== "string") throw new Error("evidence.json holds a record without a verdict");
    if (r.verdict !== "other" && Object.hasOwn(counts, r.verdict)) counts[r.verdict]++;
    else counts.other++;
  }
  let summaryAgrees = null; // summary.json is a second opinion, never the source of the counts
  try {
    const s = JSON.parse(fs.readFileSync(path.join(runDir, "summary.json"), "utf8"));
    summaryAgrees = typeof s.total === "number" ? s.total === records.length : null;
  } catch {
    summaryAgrees = null;
  }
  return { campaigns: records.length, pass: counts.PASS, fail: counts.FAIL, inconclusive: counts.INCONCLUSIVE, other: counts.other, summaryAgrees };
}

const MESSAGES = {
  no_runs_dir: "There is no runs/ directory.",
  no_valid_run: "runs/ holds no completed run (evidence.json, summary.json and evidence-bundle.zip are all required).",
};

/** Everything the UI needs, as plain data. Never contains a filesystem path. */
export function resolveEvidence(runsDir, base = "/evidence-report") {
  const sel = selectRun(runsDir);
  if (sel.status !== "ok") return { meta: { available: false, status: sel.status, message: MESSAGES[sel.status] } };
  const { run } = sel;
  const fail = (status, message) => ({ meta: { available: false, status, message, runId: run.id } });
  let counts;
  try {
    counts = summarizeEvidence(run.dir);
  } catch (e) {
    return fail("invalid_evidence", e.message);
  }
  let paths;
  try {
    paths = ensureBundle(run);
  } catch (e) {
    return fail("extract_failed", `evidence-bundle.zip could not be extracted: ${e.message}`);
  }
  if (!isFile(paths.report)) return fail("report_missing", "evidence-bundle.zip contains no report.html.");
  return {
    reportPath: paths.report,
    meta: { available: true, runId: run.id, ...counts, manifest: verifyManifest(paths.bundle), reportUrl: `${base}/report.html` },
  };
}

const defaultRunsDir = () => process.env.EVIDENCE_RUNS_DIR || fileURLToPath(new URL("../../../runs", import.meta.url));

function middleware(runsDir, base) {
  return (req, res, next) => {
    const url = (req.url || "/").split("?")[0];
    if (url !== "/meta.json" && url !== "/report.html") return next();
    if (req.method !== "GET" && req.method !== "HEAD") {
      res.statusCode = 405;
      return res.end();
    }
    const out = resolveEvidence(runsDir, base);
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Content-Type-Options", "nosniff");
    if (url === "/meta.json") {
      res.setHeader("Content-Type", "application/json; charset=utf-8");
      return res.end(req.method === "HEAD" ? undefined : JSON.stringify(out.meta));
    }
    if (!out.reportPath) {
      res.statusCode = 404;
      res.setHeader("Content-Type", "text/plain; charset=utf-8");
      return res.end(out.meta.message);
    }
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    // the report is static HTML with inline CSS: nothing else may load or run inside it
    res.setHeader("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'");
    return res.end(req.method === "HEAD" ? undefined : fs.readFileSync(out.reportPath));
  };
}

/** Vite plugin (dev server and `vite preview`). */
export default function evidenceReportPlugin({ runsDir = defaultRunsDir(), base = "/evidence-report" } = {}) {
  return {
    name: "rom-evidence-report",
    configureServer(server) {
      server.middlewares.use(base, middleware(runsDir, base));
    },
    configurePreviewServer(server) {
      server.middlewares.use(base, middleware(runsDir, base));
    },
  };
}
