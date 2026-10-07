<!-- Made with Claude (Claude Code, Anthropic) -->
# opensovd — Eclipse OpenSOVD server with DFM faults

Serves the guardian's DFM fault records over the SOVD REST API (ISO 17978-3). This fills in section 4
("Let OpenSOVD read from the DFM and serve the faults interface") of the hackathon
[OpenSOVD Starter Template](https://github.com/Eclipse-SDV-Hackathon-Chapter-Four/OpenSOVD-Starter-Template).

```
guardian --uProtocol--> rom-dfm report --fault-lib Reporter--> dfm_bin --iceoryx2 dfm/query--> rom-opensovd --HTTP--> SOVD client
                   (services/dfm)                                                          (this service)
```

`rom-opensovd` is a small Rust binary on top of the upstream crates, not a fork:

| Upstream (pinned in `Cargo.toml`) | Used for |
|---|---|
| `eclipse-opensovd/opensovd-core` `opensovd-server` / `opensovd-core` / `opensovd-models` @ `601d680` | HTTP server, SOVD entity tree, `version-info`, auth layers, SOVD error model |
| `eclipse-opensovd/fault-lib` `dfm_lib` @ `12dac50` (same rev as `services/dfm`) | `DfmQueryApi` + `Iceoryx2DfmQuery`: reads fault records from the running DFM |

opensovd-core does not implement the SOVD `faults` resource yet (it is reserved in `EntityCapabilities`,
see [opensovd-core#156](https://github.com/eclipse-opensovd/opensovd-core/issues/156)), so
[`src/faults.rs`](src/faults.rs) adds it and mounts it with `ServerBuilder::service`.

## Run

```bash
make sovd            # dfm + opensovd in the background (needs the Rust DFM from services/dfm)
make sovd-faults     # GET /sovd/v1/apps/battery_guardian/faults, pretty-printed
```

Standalone image: `docker build -f services/opensovd/Dockerfile -t localhost/rom/opensovd:dev .`
(the build stage also runs `cargo test`).

## SOVD API

Base `http://localhost:7690/sovd`. Entities: component `rom-hpc` hosting app `battery_guardian`
(one app per DFM entity path, `SOVD_DFM_APPS`).

| Request | Answer |
|---|---|
| `GET /version-info` | SOVD 1.1.0, base URI |
| `GET /v1/apps`, `GET /v1/apps/battery_guardian` | app list / capabilities (`is-located-on` → `rom-hpc`) |
| `GET /v1/components/rom-hpc/hosts` | `battery_guardian` |
| `GET /v1/apps/battery_guardian/faults` | `{"items": [Fault]}`, sorted by `code` |
| `GET .../faults?status[testFailed]=1` | filter by DTC status bit (repeat = OR; camelCase or snake_case; `status[mask]=0x2F`), `?severity=N` |
| `GET .../faults/{code}` | `{"item": Fault, "environment_data": {cell, temp_c, cells, reason, seq, msg_id, ts_ms, run_id}}` |
| `DELETE .../faults`, `DELETE .../faults/{code}` | clear in the DFM → `204` |

Fault JSON (same shape as the OpenSOVD Classic Diagnostic Adapter), real output from `dfm_bin`:

```json
{
  "code": "battery_guardian.out_of_range",
  "display_code": "battery_guardian.out_of_range",
  "fault_name": "BatteryTempOutOfRange",
  "fault_translation_id": "fault.battery_guardian.out_of_range",
  "scope": "ecu",
  "severity": 4,
  "status": {
    "test_failed": true, "test_failed_this_operation_cycle": true, "pending_dtc": false,
    "confirmed_dtc": true, "test_not_completed_since_last_clear": false,
    "test_failed_since_last_clear": true, "test_not_completed_this_operation_cycle": false,
    "warning_indicator_requested": true, "mask": "0xAB"
  },
  "occurrence_counter": 10, "aging_counter": 0, "healing_counter": 0,
  "first_occurrence": "2026-10-07T09:16:15Z", "last_occurrence": "2026-10-07T09:16:18Z"
}
```

`severity` is the catalog `FaultSeverity` as a number (`Warn` = 3, `Error` = 4, `Fatal` = 5).
`environment_data` values that parse as numbers are sent as JSON numbers.

Errors use the SOVD `GenericError` body (`error_code: "vendor-specific"`):

| HTTP | `vendor_code` | When |
|---|---|---|
| 404 | `resource-not-found` | unknown fault code, or a fault the DFM has no record of yet (also on `DELETE`) |
| 400 | `invalid-query` / `bad-argument` | bad filter / rejected by the DFM |
| 503 | `dfm-unavailable` | DFM not running or no answer within `DFM_QUERY_TIMEOUT_MS` |

## Contract with `services/dfm`

- DFM entity path = catalog `id` = SOVD app id: `battery_guardian`. Fault codes = catalog `Text` ids
  ([`services/dfm/catalog/battery_guardian.json`](../dfm/catalog/battery_guardian.json)): 5 pack codes
  (`battery_guardian.over_temp_warning`, ...) and 3 per cell (`battery_guardian.cell2.signal_stuck`, ...).
  Environment keys `cell`, `temp_c`, `cells`, `reason`, `seq`, `msg_id`, `ts_ms`, `run_id` are passed through
  unchanged (numbers become JSON numbers; `cells` = `"31.2,30.1,,29.9"` stays a string).
- Same `fault-lib` rev on both sides (the iceoryx2 message layout must match).
- iceoryx2 needs the same `/dev/shm` **and** `/tmp/iceoryx2` in both containers, with the same lifetime,
  and both processes running as the same user. Compose mounts the tmpfs volumes `iceoryx2-shm` and
  `iceoryx2` into `dfm` and `opensovd` (`x-iceoryx2` anchor). Do not use `ipc: service:dfm` with a
  persistent `/tmp/iceoryx2` volume: after a DFM restart the service files outlive the shared memory and
  every query fails with `ServiceInCorruptedState`.
- The server can start before the DFM (503 until it is up). After a DFM restart or crash it removes the
  dead node's iceoryx2 resources and reconnects on the next request.

## Config (flags or env)

| Env | Default |
|---|---|
| `SOVD_URL` | `http://0.0.0.0:7690/sovd` |
| `SOVD_DFM_APPS` | `battery_guardian` (comma-separated DFM entity paths) |
| `SOVD_COMPONENT` | `rom-hpc` |
| `DFM_QUERY_TIMEOUT_MS` | `500` |
| `RUST_LOG` | `info` |

## Verified (2026-10-07)

With the upstream `dfm_bin` and the fault-lib `tst_app` reporter, using the `battery_guardian` catalog
from the DFM plan, in separate containers:

- entities, `version-info`, faults list / filter / detail / delete, 404 and 503 answers
- `docker compose restart dfm` and `kill dfm` + `start dfm`: next request is `200`, new reports show up
- `cargo test`: 5 tests on the faults resource against a stub `DfmQueryApi`

## Next

- [ ] Advertise `faults` in the app capabilities (needs opensovd-core#156 upstream; offer this module as the PR)
- [ ] `data/` on `battery_guardian`: live guardian state and temperature
- [ ] Evidence collector reads the faults for every faulted run (correlate `msg_id` with the guardian log)
