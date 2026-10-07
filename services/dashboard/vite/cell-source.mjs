// Made with Claude (Claude Code, Anthropic)
// Cell 1 source switch: either the AZ3166 board (adapter) or the simulator writes cell 1, never both. Two writers on the
// same KUKSA path make the value jump between them on every tick, all the way through the guardian.
//
//   GET  /api/cell1-source            {mode: "hw" | "sim" | "both" | "none", hwAvailable, simulatorCells, adapterEnabled}
//   POST /api/cell1-source {mode}     switch; the old writer lets go before the new one takes over
//
// Talks to the simulator's POST /cells (SIMULATOR_URL, default http://localhost:8080) and the adapter's POST /source
// (ADAPTER_URL, default http://localhost:8084); both listen on 127.0.0.1 only. Local demo only, like scenarios.mjs.

const SIM_ALL = [1, 2, 3, 4];
const SIM_WITHOUT_1 = [2, 3, 4];
const TIMEOUT_MS = 2000;

export function createCellSource({
  simUrl = process.env.SIMULATOR_URL || "http://localhost:8080",
  adapterUrl = process.env.ADAPTER_URL || "http://localhost:8084",
  fetchFn = fetch,
} = {}) {
  const call = async (url, body) => {
    const res = await fetchFn(url, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
    return res.json();
  };
  const simCells = () => call(`${simUrl}/cells`).then((b) => b.cells);
  const adapterEnabled = () => call(`${adapterUrl}/source`).then((b) => b.enabled).catch(() => null); // null: no adapter

  async function get() {
    const [cells, enabled] = await Promise.all([simCells(), adapterEnabled()]);
    const sim = cells.includes(1);
    const hw = enabled === true;
    const mode = sim && hw ? "both" : hw ? "hw" : sim ? "sim" : "none";
    return { mode, hwAvailable: enabled !== null, simulatorCells: cells, adapterEnabled: enabled };
  }

  async function set(mode) {
    if (mode === "hw") {
      if ((await adapterEnabled()) === null) {
        const e = new Error("the adapter is not running (start the stack with make guardian or make hw)");
        e.code = 503;
        throw e;
      }
      await call(`${simUrl}/cells`, { cells: SIM_WITHOUT_1 }); // simulator lets go first
      await call(`${adapterUrl}/source`, { enabled: true });
    } else if (mode === "sim") {
      if ((await adapterEnabled()) !== null) await call(`${adapterUrl}/source`, { enabled: false }); // board lets go first
      await call(`${simUrl}/cells`, { cells: SIM_ALL });
    } else {
      const e = new Error('mode must be "hw" or "sim"');
      e.code = 422;
      throw e;
    }
    return get();
  }

  return { get, set };
}

const send = (res, code, body) => {
  res.statusCode = code;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(body));
};

const readJson = (req) =>
  new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (c) => {
      raw += c;
      if (raw.length > 1024) reject(new Error("body too large"));
    });
    req.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        reject(new Error("invalid JSON"));
      }
    });
  });

export function middleware(source) {
  return async (req, res, next) => {
    if ((req.url || "/").split("?")[0] !== "/") return next();
    try {
      if (req.method === "GET") return send(res, 200, await source.get());
      if (req.method !== "POST") return send(res, 405, { error: "Method not allowed" });
      const origin = req.headers.origin; // a page of another origin must not flip the source
      if (origin && new URL(origin).host !== req.headers.host) return send(res, 403, { error: "Cross-origin request refused" });
      const body = await readJson(req);
      return send(res, 200, await source.set(body?.mode));
    } catch (e) {
      return send(res, e.code || 502, { error: e.message });
    }
  };
}

/** Vite plugin (dev server and `vite preview`). */
export default function cellSourcePlugin(options = {}) {
  const source = createCellSource(options);
  const base = "/api/cell1-source";
  return {
    name: "rom-cell1-source",
    configureServer(server) {
      server.middlewares.use(base, middleware(source));
    },
    configurePreviewServer(server) {
      server.middlewares.use(base, middleware(source));
    },
  };
}
