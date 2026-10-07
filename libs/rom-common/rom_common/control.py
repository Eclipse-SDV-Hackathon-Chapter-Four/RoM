# Made with Claude (Claude Code, Anthropic) — shared RoM "rom_common" library, used by all components.
"""Tiny JSON-over-HTTP control server (stdlib only), used to steer a running component:

    server = ControlServer("127.0.0.1", 8080)
    server.route("POST", "/faults", lambda body, params: (201, {"id": 1}))
    server.route("DELETE", "/faults/{id}", lambda body, params: {"cleared": params["id"]})
    server.start()                    # background thread; server.port is the bound port

A handler is called as handler(body, params) and returns either a JSON-able object (200) or
(status, object). Raise ControlError(status, message) for a client error. No authentication:
bind to 127.0.0.1 or keep the port on a private network (see README).
"""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, List, Optional, Tuple

MAX_BODY_BYTES = 64 * 1024


class ControlError(Exception):
    """Handler-level error that becomes {"error": message} with the given HTTP status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


Handler = Callable[[Optional[dict], dict], object]


def _compile(pattern: str) -> "re.Pattern":
    return re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")


class ControlServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self._routes: List[Tuple[str, "re.Pattern", Handler]] = []
        self._httpd = ThreadingHTTPServer((host, port), self._make_handler())
        self._thread: Optional[threading.Thread] = None
        self.route("GET", "/health", lambda body, params: {"status": "ok"})

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    def route(self, method: str, pattern: str, handler: Handler) -> None:
        self._routes.append((method.upper(), _compile(pattern), handler))

    def start(self) -> "ControlServer":
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def dispatch(self, method: str, path: str, raw_body: bytes) -> Tuple[int, object]:
        path_matched = False
        for m, rx, handler in self._routes:
            match = rx.match(path)
            if not match:
                continue
            path_matched = True
            if m != method:
                continue
            try:
                body = json.loads(raw_body) if raw_body.strip() else None
            except ValueError:
                return 400, {"error": "invalid_json"}
            try:
                result = handler(body, match.groupdict())
            except ControlError as e:
                return e.status, {"error": e.message}
            if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], int):
                return result
            return 200, result
        return (405, {"error": "method_not_allowed"}) if path_matched else (404, {"error": "not_found"})

    def _make_handler(self):
        server = self

        class _Handler(BaseHTTPRequestHandler):
            def _serve(self):
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY_BYTES:
                    status, obj = 413, {"error": "body_too_large"}
                else:
                    status, obj = server.dispatch(self.command, self.path.split("?")[0], self.rfile.read(length))
                data = json.dumps(obj, separators=(",", ":")).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_DELETE = _serve

            def log_message(self, *args):  # components log JSON events themselves
                pass

        return _Handler
