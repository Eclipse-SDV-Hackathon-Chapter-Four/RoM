<!-- Made with Claude (Claude Code, Anthropic) -->
# simulator — 4-cell battery temperature source with fault injection

Streams a sine-wave battery temperature into the KUKSA Databroker, one value per cell, and lets you break it
on purpose over HTTP.

| VSS path | Written by the simulator |
|---|---|
| `Vehicle.Powertrain.TractionBattery.Cells.Cell1..4.Temperature` | custom overlay [`infra/vss/rom_overlay.json`](../../infra/vss/rom_overlay.json), loaded by the databroker next to the standard VSS |
| `Vehicle.Powertrain.TractionBattery.Temperature.Max` | the hottest cell **that was written** (kept for monitors; the guardian reads the cells); only if the simulator owns all four cells |
| `Vehicle.RoM.Heartbeat.Simulator` / `.Chip` | liveness counters, every tick: the simulator process, and a simulated sensor chip (only if it owns cell 1) |

Cell 1 is the hottest (the others sit 1-1.5 °C below it, the seed shuffles the gaps), so without faults `Max` is
the plain wave. The guardian monitors every cell on its own, so a fault on any cell raises that cell's DFM code
(`battery_guardian.cell<N>.…`); only the thermal states follow the hottest **valid** cell.

**Hardware hybrid mode:** with the real board as cell 1 (written by the adapter) run `SIM_CELLS=2,3,4` (`make hw` does
this). The simulator then leaves cell 1, `Max` and the chip heartbeat to the adapter.

## Run

```bash
make guardian          # whole chain; the API is on http://127.0.0.1:8080
make sim               # simulator only, in the foreground
rom-simulator --hz 2 --period 120 --duration 0 --seed 0     # from the dev venv
```

| Env | Default | |
|---|---|---|
| `SIM_HZ`, `SIM_PERIOD_S`, `SIM_MIN_C`, `SIM_MAX_C`, `SIM_DURATION_S` | `2`, `120`, `30`, `69`, `0` | the wave (`0` = run forever) |
| `SIM_SEED` | `0` | cell offsets, replayable |
| `SIM_CELLS` | `1,2,3,4` | cells to simulate, e.g. `2,3,4` when a real board is cell 1 |
| `SIM_API_HOST` / `SIM_API_PORT` | `127.0.0.1` / `8080` | fault API; port `0` turns it off, a busy port only logs `api_unavailable` |

The default wave (30-69 °C) crosses the guardian thresholds (38 / 45 °C) by itself within 30 s. Campaigns therefore
set a calm `baseline` (for example 25-32 °C) so that only the injected fault moves the guardian.

## HTTP API

JSON in and out, **no authentication**: it binds to loopback by default, and compose publishes it on
`127.0.0.1` only. Do not expose it on a shared network.

| Request | |
|---|---|
| `POST /run` `{"run_id":"r1","seed":7,"min_c":25,"max_c":32,"period_s":120}` | new run: wave restarts at t=0, faults cleared, logs tagged with `run_id`. Wave settings optional (`min_c` and `max_c` go together) and stay for later runs |
| `POST /faults` `{"type":"drift","cell":1,"params":{"rate_c_per_s":2},"duration_s":30}` | inject; `cell` / `cells` omitted = all cells; `duration_s` omitted = until cleared. 201 + the fault with its `id`; 422 on a bad request |
| `GET /faults` | active faults |
| `DELETE /faults/{id}` / `DELETE /faults` | clear one / all |
| `GET /state` | run id, seed, source time, last cell values, `max_c`, stalled flag, active faults |
| `GET /health` | `{"status":"ok"}` |

```bash
curl -s -XPOST localhost:8080/faults -d '{"type":"drift","cell":1,"params":{"rate_c_per_s":2}}'
curl -s localhost:8080/state
curl -s -XDELETE localhost:8080/faults
```

## Fault types

| Type | Kind | Effect | `params` |
|---|---|---|---|
| `stuck` | signal | the cell keeps reporting the value it had at injection | `value` (optional: stick at this value) |
| `spike` | signal | adds `delta` for `samples` samples | `delta` (required), `samples` (default 1) |
| `drift` | signal | adds `rate_c_per_s` × seconds since injection | `rate_c_per_s` (required) |
| `out_of_range` | signal | reports a fixed value | `value` (default 200) |
| `dropout` | source | the cells are not written (all cells if none given); the wave keeps running | – |
| `replay_interruption` | source | the whole source goes silent (heartbeats keep going); the wave pauses and resumes where it stopped | – (no cells) |
| `heartbeat_loss` | source | one heartbeat stops while the data keeps flowing | `component`: `chip` or `simulator` (no cells) |

`dropout` wins over a signal fault on the same cell. `Max` is computed over the cells that are written; when none
is, only the heartbeats are written (the process is alive, the data is not). Ticks keep their schedule during faults.

## Log events

`campaign_start`, `sample` (`temp_c` = Max or null, `cells`, `stalled`, `heartbeats`), `run_started`, `fault_injected`,
`fault_cleared` (`reason`: `api` / `expired` / `new_run`), `campaign_end`, `api_started` / `api_unavailable`.

## Test

```bash
pytest services/simulator     # no databroker needed
```
