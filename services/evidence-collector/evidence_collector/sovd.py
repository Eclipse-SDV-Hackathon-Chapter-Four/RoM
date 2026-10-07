# Made with Claude (Claude Code, Anthropic)
"""Diagnostic truth from Eclipse OpenSOVD (services/opensovd): is the expected DTC really there, for this run?

check(code) -> {"url", "visible", "confirmed", "run_id", "status", "error"}; never raises, an unreachable
OpenSOVD is a result (visible False + error) and becomes a FAIL in the verdict.

    GET <SOVD_URL>/v1/apps/<SOVD_APP>/faults/<code>  ->  {"item": Fault, "environment_data": {..., "run_id"}}

confirmed = the DTC status says the test failed since the last clear (confirmed_dtc or test_failed_since_last_clear);
run_id comes from the DFM record's environment data, which the guardian fills from the cell message behind the edge.
"""
import json
import urllib.error
import urllib.parse
import urllib.request


class SovdClient:
    def __init__(self, base_url: str, app: str, timeout_s: float = 2.0):
        self.base_url, self.app, self.timeout_s = base_url.rstrip("/"), app, timeout_s

    def url(self, code: str) -> str:
        return f"{self.base_url}/v1/apps/{self.app}/faults/{urllib.parse.quote(code, safe='')}"

    def check(self, code: str) -> dict:
        url = self.url(code)
        result = {"url": url, "visible": False, "confirmed": False, "run_id": None, "status": None, "error": None}
        try:
            with urllib.request.urlopen(url, timeout=self.timeout_s) as r:
                body = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            result["error"] = f"HTTP {e.code}" + (" (no record of this fault)" if e.code == 404 else "")
            return result
        except (urllib.error.URLError, OSError, ValueError) as e:
            result["error"] = f"OpenSOVD unreachable: {e}"
            return result
        return interpret(body, result)


def interpret(body, result: dict) -> dict:
    """Fill result from a GET .../faults/{code} answer."""
    if not isinstance(body, dict) or not isinstance(body.get("item"), dict):
        result["error"] = "answer without item"
        return result
    item = body["item"]
    status, env = item.get("status"), body.get("environment_data")
    status, env = (status if isinstance(status, dict) else {}), (env if isinstance(env, dict) else {})
    result.update(visible=True, status=status, run_id=env.get("run_id"),
                  confirmed=bool(status.get("confirmed_dtc") or status.get("test_failed_since_last_clear")))
    return result
