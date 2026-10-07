# Made with Claude (Claude Code, Anthropic)
"""Runs one campaign: tags the run, injects every fault at its time, clears it again, and logs the trail.

Log events (JSON lines, all with the campaign's run_id, the raw material for the evidence collector):
    campaign_start   hazard, safety_goal, expected_state, max_detect_ms, seed, duration_s, baseline, faults
    fault_injected   the step plus the id the service gave the fault
    fault_cleared    reason: scheduled | campaign_end
    fault_failed     a service refused or was unreachable (the campaign is aborted)
    campaign_end     status: completed | aborted | interrupted (aborted also if a fault could not be cleared)
Faults are always cleared on the way out, also on Ctrl+C or an error.
"""
import json
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

from rom_common import clock

from .campaign import Campaign, FaultStep

Http = Callable[[str, str, Optional[dict]], Tuple[int, object]]


class RunnerError(RuntimeError):
    """A service could not be reached or refused a request."""


def http_json(method: str, url: str, body: Optional[dict] = None, timeout: float = 5.0) -> Tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {"error": e.reason}
    except (urllib.error.URLError, OSError) as e:
        raise RunnerError(f"{method} {url}: {e}") from e


def timeline(campaign: Campaign) -> List[Tuple[float, int, str, FaultStep]]:
    """(time, order, action, step) sorted by time; a clear sorts before an inject at the same instant."""
    events = []
    for step in campaign.faults:
        events.append((step.at_s, 1, "inject", step))
        if step.duration_s is not None:
            events.append((step.at_s + step.duration_s, 0, "clear", step))
    return sorted(events, key=lambda e: (e[0], e[1], e[3].index))


class Runner:
    def __init__(self, campaign: Campaign, urls: Dict[str, str], log, http: Http = http_json,
                 sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic):
        self.campaign, self.urls, self.log = campaign, urls, log
        self._http, self._sleep, self._monotonic = http, sleep, monotonic
        self._live: Dict[int, Tuple[FaultStep, int]] = {}  # step index -> (step, fault id at the service)

    def check_urls(self) -> None:
        missing = sorted(self.campaign.targets() - set(self.urls))
        if missing:
            raise RunnerError(f"campaign needs {', '.join(missing)} but no URL is set "
                              f"(--{missing[0]}-url or {missing[0].upper()}_URL)")

    def run(self) -> str:
        c = self.campaign
        self.check_urls()
        self.log.run_id = c.run_id
        status, error = "completed", None
        self.log.log("campaign_start", hazard=c.hazard, safety_goal=c.safety_goal, expected_state=c.expected_state,
                     max_detect_ms=c.max_detect_ms, seed=c.seed, duration_s=c.duration_s,
                     baseline=c.baseline, faults=[f.as_dict() for f in c.faults])
        try:
            for target, url in self.urls.items():   # new run: wave back to t=0, stale faults gone, logs tagged
                body = {"run_id": c.run_id, "seed": c.seed, **(c.baseline if target == "simulator" else {})}
                self._call("POST", f"{url}/run", body, target)
            start = self._monotonic()
            for at_s, _, action, step in timeline(c):
                self._sleep(max(0.0, start + at_s - self._monotonic()))
                (self._inject if action == "inject" else self._clear)(step)
            self._sleep(max(0.0, start + c.duration_s - self._monotonic()))
        except KeyboardInterrupt:
            status = "interrupted"
        except RunnerError as e:
            status, error = "aborted", str(e)
        finally:
            stuck = self._cleanup()
            if stuck and status == "completed":   # the run is not clean: a fault may still be active
                status, error = "aborted", f"could not clear {', '.join(stuck)}"
            self.log.log("campaign_end", status=status, **({"error": error} if error else {}))
        return status

    def _call(self, method: str, url: str, body: Optional[dict], target: str, step: Optional[FaultStep] = None):
        try:
            code, obj = self._http(method, url, body)
        except RunnerError as e:
            self.log.log("fault_failed", target=target, error=str(e), **({"index": step.index} if step else {}))
            raise
        if not 200 <= code < 300:
            message = f"{method} {url} -> {code}: {obj.get('error') if isinstance(obj, dict) else obj}"
            self.log.log("fault_failed", target=target, error=message, **({"index": step.index} if step else {}))
            raise RunnerError(message)
        return obj

    def _inject(self, step: FaultStep) -> None:
        obj = self._call("POST", f"{self.urls[step.target]}/faults", step.request(), step.target, step)
        self._live[step.index] = (step, obj["id"])
        self.log.log("fault_injected", fault_id=obj["id"], **step.as_dict())

    def _clear(self, step: FaultStep, reason: str = "scheduled") -> None:
        _, fault_id = self._live.pop(step.index)
        self._call("DELETE", f"{self.urls[step.target]}/faults/{fault_id}", None, step.target, step)
        self.log.log("fault_cleared", fault_id=fault_id, reason=reason, **step.as_dict())

    def _cleanup(self) -> List[str]:
        """Clear what is still active, best effort: one unreachable service must not leave the others faulted.
        Returns what could not be cleared, as 'target type'."""
        failed = []
        for step, _ in list(self._live.values()):
            try:
                self._clear(step, reason="campaign_end")
            except RunnerError:
                failed.append(f"{step.target} {step.type}")
        return failed
