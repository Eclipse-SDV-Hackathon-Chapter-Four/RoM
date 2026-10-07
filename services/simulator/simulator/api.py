# Made with Claude (Claude Code, Anthropic)
"""HTTP control API of the simulator (JSON, see rom_common.control). Port: SIM_API_PORT (0 = off).

    POST   /run         {"run_id": "r1", "seed": 7}   start a new run: wave back to t=0, faults cleared, logs tagged
    POST   /faults      {"type": "drift", "cell": 1, "params": {"rate_c_per_s": 2}, "duration_s": 30}
    GET    /faults      active faults
    DELETE /faults/{id} clear one fault        DELETE /faults  clear all
    GET    /state       run id, seed, source time, last cell values, Max, active faults
    GET    /health

"cell": 3 or "cells": [1, 3]; neither means all cells. Fault types: see faults.py.
"""
from typing import Optional

from rom_common.control import ControlError, ControlServer

from .faults import FaultError, FaultState


def _need_body(body: Optional[dict]) -> dict:
    if not isinstance(body, dict):
        raise ControlError(400, "expected a JSON object body")
    return body


def build_api(session, faults: FaultState, log, host: str, port: int) -> ControlServer:
    server = ControlServer(host, port)

    def start_run(body, params):
        body = _need_body(body) if body is not None else {}
        seed, run_id = body.get("seed", session.seed), body.get("run_id")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ControlError(422, "seed must be an integer")
        if run_id is not None and not isinstance(run_id, str):
            raise ControlError(422, "run_id must be a string")
        for f in faults.clear():
            log.log("fault_cleared", reason="new_run", **f.as_dict())
        if run_id is not None:
            log.run_id = run_id
        session.restart(seed, log.run_id)
        log.log("run_started", seed=seed)
        return 200, {"run_id": log.run_id, "seed": seed}

    def inject(body, params):
        body = _need_body(body)
        cells = body.get("cells", [body["cell"]] if "cell" in body else None)
        try:
            fault = faults.add(body.get("type"), cells, body.get("params"), body.get("duration_s"))
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
    server.route("GET", "/state", lambda body, params: session.snapshot())
    return server
