# Made with Claude (Claude Code, Anthropic)
import json
import urllib.error
import urllib.request

import pytest

from rom_common.control import ControlError, ControlServer


def call(server, method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}", data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def server():
    s = ControlServer("127.0.0.1", 0)

    def boom(body, params):
        raise ControlError(422, "nope")

    s.route("POST", "/items", lambda body, params: (201, {"got": body}))
    s.route("DELETE", "/items/{id}", lambda body, params: {"deleted": params["id"]})
    s.route("GET", "/boom", boom)
    s.start()
    yield s
    s.close()


def test_health(server):
    assert call(server, "GET", "/health") == (200, {"status": "ok"})


def test_post_returns_handler_status_and_body(server):
    assert call(server, "POST", "/items", {"a": 1}) == (201, {"got": {"a": 1}})


def test_path_parameters_and_default_200(server):
    assert call(server, "DELETE", "/items/7") == (200, {"deleted": "7"})


def test_empty_body_is_none(server):
    assert call(server, "POST", "/items") == (201, {"got": None})


def test_invalid_json_is_400(server):
    assert call(server, "POST", "/items", raw=b"{nope") == (400, {"error": "invalid_json"})


def test_control_error_sets_status(server):
    assert call(server, "GET", "/boom") == (422, {"error": "nope"})


def test_unknown_path_404_and_wrong_method_405(server):
    assert call(server, "GET", "/missing")[0] == 404
    assert call(server, "GET", "/items")[0] == 405


def test_query_string_is_ignored(server):
    assert call(server, "GET", "/health?x=1")[0] == 200
