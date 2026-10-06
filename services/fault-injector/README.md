<!-- Made with Claude (Claude Code, Anthropic) -->
# fault-injector — Fault Campaign Runner (TODO)

Placeholder: package, console script `rom-fault-injector` and image `localhost/rom/fault-injector:dev`
exist; the service only logs `not_implemented`.

TODO:
- [ ] Campaigns in YAML: `seed`, `run_id`, `hazard`, `safety_goal`, `fault`, `expected_state`, `max_detect_ms`
- [ ] Transport faults (delay, duplicate, drop, reorder) and signal faults (stuck, spike, drift, out-of-range)
      as `rom_uprotocol.publisher` interceptors — no change to the publisher needed
- [ ] Source faults (dropout, replay interruption)
- [ ] Log `campaign_start` / `fault_injected` / `campaign_end` with `run_id` for the evidence collector
