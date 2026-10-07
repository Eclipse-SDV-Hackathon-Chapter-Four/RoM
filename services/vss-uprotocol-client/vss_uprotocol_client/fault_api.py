# Made with Claude (Claude Code, Anthropic)
"""Optional HTTP control API for transport faults (env FAULT_API_PORT; unset or 0 = off, no interceptor installed).

    POST   /run         {"run_id": "r1", "seed": 7}   new run: faults cleared, RNG reseeded, logs tagged
    POST   /faults      {"type": "delay", "params": {"ms": 1500}, "duration_s": 10}
    GET    /faults      active faults
    DELETE /faults/{id} clear one fault        DELETE /faults  clear all
    GET    /state       run id, active faults, counters (seen / dropped / reordered / duplicated / delayed)
    GET    /health

Fault types and what they do: rom_uprotocol.faults. Same request shape as the simulator API.
"""
from typing import Optional

from rom_common.control import ControlError, ControlServer
from rom_uprotocol.faults import FaultError, TransportFaults


def build_api(faults: TransportFaults, log, host: str, port: int) -> ControlServer:
    server = ControlServer(host, port)

    def body_object(body: Optional[dict]) -> dict:
        if not isinstance(body, dict):
            raise ControlError(400, "expected a JSON object body")
        return body

    def start_run(body, params):
        body = body_object(body) if body is not None else {}
        seed, run_id = body.get("seed", 0), body.get("run_id")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ControlError(422, "seed must be an integer")
        if run_id is not None and not isinstance(run_id, str):
            raise ControlError(422, "run_id must be a string")
        for f in faults.clear():
            log.log("fault_cleared", reason="new_run", **f.as_dict())
        if run_id is not None:
            log.run_id = run_id
        faults.reset(seed)
        log.log("run_started", seed=seed)
        return 200, {"run_id": log.run_id, "seed": seed}

    def inject(body, params):
        body = body_object(body)
        try:
            fault = faults.add(body.get("type"), body.get("params"), body.get("duration_s"))
        except FaultError as e:
            raise ControlError(422, str(e))
        log.log("fault_injected", **fault.as_dict())
        return 201, fault.as_dict()

    def clear_one(body, params):
        fault = faults.remove(int(params["id"])) if params["id"].isdigit() else None
        if fault is None:
            raise ControlError(404, "no such fault")
        log.log("fault_cleared", reason="api", **fault.as_dict())
        return {"cleared": fault.id}

    def clear_all(body, params):
        removed = faults.clear()
        for f in removed:
            log.log("fault_cleared", reason="api", **f.as_dict())
        return {"cleared": [f.id for f in removed]}

    server.route("POST", "/run", start_run)
    server.route("POST", "/faults", inject)
    server.route("GET", "/faults", lambda body, params: [f.as_dict() for f in faults.active()])
    server.route("DELETE", "/faults/{id}", clear_one)
    server.route("DELETE", "/faults", clear_all)
    server.route("GET", "/state", lambda body, params: {"run_id": log.run_id, "faults": [f.as_dict() for f in faults.active()],
                                                         "counts": dict(faults.counts)})
    return server
