<!-- Made with Claude (Claude Code, Anthropic) -->
# fault-injector — Fault Campaign Runner

Runs **campaigns**: YAML files that tie a hazard and a safety goal to the faults that provoke it and to the state
the guardian must reach. The runner injects each fault at its time, clears it again, and logs the whole trail with
the campaign's `run_id`, which is also stamped on the simulator's and the publisher's logs. That makes
**hazard → safety goal → injected fault → detection** traceable for the evidence collector.

```
fault-injector --HTTP--> simulator             signal + source faults (stuck, spike, drift, out_of_range, dropout, replay_interruption, heartbeat_loss)
               --HTTP--> vss-uprotocol-client  transport faults (drop, reorder, duplicate, delay; topic: all|signal|heartbeat) + databroker_down
```

## Run

```bash
make guardian                       # the stack must be up
make campaigns                      # list the bundled campaigns
make campaign C=thermal_runaway     # run one, watch the guardian logs in the other terminal

rom-fault-injector run my.yaml --dry-run          # validate and print the timeline only
rom-fault-injector run thermal_runaway --simulator-url http://127.0.0.1:8080 --publisher-url http://127.0.0.1:8081
```

Exit code: `0` completed, `1` aborted or interrupted (a fault was refused, a service is down, Ctrl+C, or a fault
could not be cleared), `2` invalid campaign or missing URL. Faults are cleared on every way out.

| Env | Default | |
|---|---|---|
| `SIMULATOR_URL` | `http://127.0.0.1:8080` | simulator API ([simulator README](../simulator/README.md)) |
| `PUBLISHER_URL` | – | vss-uprotocol-client fault API, needed by campaigns with `target: publisher` |
| `UP_CAMPAIGN_EVENTS` | – | `1` (or `--uprotocol`): every log event below also goes out on `up://<UP_AUTHORITY>/1003/1/8005` for the [evidence collector](../evidence-collector/README.md); needs `pip install './services/fault-injector[uprotocol]'`, set in compose. Waits `ZENOH_SETTLE_MS` (1000) for Zenoh to connect first |

## Campaign file

```yaml
run_id: thermal-runaway-01          # correlation id on every log line
seed: 7                             # replayable runs (cell offsets, drop probability)
hazard: "H1: thermal runaway of a single traction battery cell"
safety_goal: "SG1: warn at 38 °C and request cooling at 45 °C pack maximum"
expected_state: CRITICAL            # CLEAR | MONITORING | WARNING | CRITICAL | SENSOR_FAULT | MITIGATING
expected_faults: [battery_guardian.over_temp_critical]   # DFM codes OpenSOVD must show (rom_common.contracts.FAULT_CODES)
max_detect_ms: 35000                # ... reached within this long after the first fault
duration_s: 70                      # optional; default = last fault end + settle_s (default 10)
baseline: {min_c: 25, max_c: 32}    # optional calm wave, so only the fault moves the guardian
faults:
  - {at_s: 10, duration_s: 50, target: simulator, type: drift, cell: 1, params: {rate_c_per_s: 0.7}}
```

`cell: 2` / `cells: [1, 3]` / neither (all cells); transport faults take no cell. A fault without `duration_s` lasts
until the campaign ends. Fault parameters are checked by the services at injection time, not at load time, so a bad
`params` shows up as `fault_failed` and aborts the run.

Bundled campaigns (`fault_injector/campaigns/`), or pass a path to your own:

| Campaign | Fault | Expected state | Expected DFM faults (`battery_guardian.…`) |
|---|---|---|---|
| `thermal_runaway` | drift on cell 1 | `CRITICAL` | `over_temp_warning`, `over_temp_critical`, `cell_imbalance` |
| `sensor_stuck` | all four cells stuck | `SENSOR_FAULT` (10 s) | `cell1..4.signal_stuck` |
| `sensor_stuck_cell3` | cell 3 stuck | `MONITORING` | `cell3.signal_stuck` |
| `out_of_range` | 200 °C on cell 1 | `MONITORING` (cell 1 left out) | `cell1.out_of_range` |
| `cell_dropout_cell2` | cell 2 dropped | `MONITORING` | `cell2.signal_stale` |
| `source_dropout` | all cells dropped | `SENSOR_FAULT` (stale) | `signal_stale` |
| `replay_interruption` | source stalls and resumes | `SENSOR_FAULT` (stale) | `signal_stale` |
| `transport_drop` | every message dropped | `SENSOR_FAULT` (stale) | `signal_stale` |
| `transport_delay` | messages 2.5 s late | `SENSOR_FAULT` (stale), recovers after about 1 s once the late messages keep arriving | `signal_stale` |
| `combined_runaway_lossy_link` | drift + duplicate + 600 ms delay | `CRITICAL` | as `thermal_runaway` |
| `cell_faulty_while_other_hot` | cell 3 stuck + cell 1 drifts up | `CRITICAL` (the stuck cell is left out, the warning still fires) | `cell3.signal_stuck`, `over_temp_warning`, `over_temp_critical`, `cell_imbalance` |
| `chip_heartbeat_loss` | the chip stops beating, data flows | `SENSOR_FAULT` "chip silent" | `chip_silent` |
| `producer_heartbeat_loss` | the simulator stops beating | `SENSOR_FAULT` "sim down" | `simulator_down` |
| `uprotocol_heartbeat_loss` | only the heartbeats dropped, cells flow | `SENSOR_FAULT` "uP link lost" | `uprotocol_lost` |
| `databroker_down` | the client reports KUKSA down (simulated) | `SENSOR_FAULT` "KUKSA down" | `databroker_down` |

Transport faults hit the cell topic (`…/1001/1/8002`) and the heartbeat topic (`…/8004`). `params.topic` picks one:
`signal` (cells only), `heartbeat`, or `all` (default). `transport_drop`, `transport_delay` and the combined campaign use
`topic: signal` so the heartbeats keep flowing and the guardian sees a stale data stream (`signal_stale`) rather than a
dead link. With `topic: all` the guardian blames the link (`uprotocol_lost`).

The heartbeat campaigns need the heartbeats to have been seen first (the guardian learns `chip` and `simulator` from
their first beat), so run them against a stack that has been up for a few seconds. With the real board,
`chip_heartbeat_loss` is simply: unplug it. `databroker_down` is simulated; for a real outage run
`docker compose -f infra/docker-compose.yml stop databroker`.

`reorder` and `duplicate` are available but have no campaign of their own: the guardian does not detect them yet
(roadmap, Guardian section), so there is no state to expect.

## Log events

`campaign_start` (hazard, safety_goal, expected_state, expected_faults, max_detect_ms, seed, baseline, faults), `fault_injected`,
`fault_cleared` (`scheduled` / `campaign_end`), `fault_failed`, `campaign_end` (`completed` / `aborted` /
`interrupted`). The runner does not judge the run: comparing the guardian's state (`…/1002/1/8006`) with
`expected_state` and `max_detect_ms`, and checking `expected_faults` in OpenSOVD, is the
[evidence collector](../evidence-collector/README.md)'s job.

## Test

```bash
pytest services/fault-injector     # fake services and a fake clock, no stack and no sleeping
```
