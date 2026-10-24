"""Ephemeral loopback transport tests; all plugin/document data is synthetic."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from http.client import HTTPConnection
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from dcc_mcp_core import ReverseBridgeSession

from dcc_mcp_figma.binding import BindingError, FigmaBinding
from dcc_mcp_figma.http_bridge import PluginHttpBridge

TOKEN = "synthetic-pairing-token-contract-only-00000001"
PLUGIN = "synthetic_plugin_instance_0001"


def document(marker=None):
    return {"name": "Synthetic document", "page_id": "1:2", "page_name": "Synthetic page", "marker": marker}


class ObservedSession:
    def __init__(self, *, timeout):
        self.core = ReverseBridgeSession(timeout=timeout)
        self.started = threading.Event()
        self.calls = []

    def call(self, method, **params):
        self.calls.append((method, deepcopy(params)))
        self.started.set()
        return self.core.call(method, **params)

    def next_request(self, timeout=None):
        return self.core.next_request(timeout=timeout)

    def submit_response(self, request_id, *, result):
        return self.core.submit_response(request_id, result=result)

    def close(self, reason):
        self.core.close(reason)


@pytest.fixture
def transport(request):
    sessions = []

    def factory(*, timeout):
        session = ObservedSession(timeout=timeout)
        sessions.append(session)
        return session

    binding = FigmaBinding(TOKEN, timeout=getattr(request, "param", 1.0), session_factory=factory)
    bridge = PluginHttpBridge(binding, port=0).start()
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        yield SimpleNamespace(binding=binding, bridge=bridge, sessions=sessions, pool=pool)
    finally:
        bridge.close()
        pool.shutdown(wait=True)


def http(transport, path, payload=None, *, method="POST", headers=None, body=None):
    request_headers = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}
    request_headers.update(headers or {})
    if body is None and payload is not None:
        body = json.dumps(payload).encode("utf-8")
    connection = HTTPConnection("127.0.0.1", transport.bridge.port, timeout=3.0)
    try:
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        value = json.loads(raw.decode("utf-8")) if raw else None
        return response.status, value, dict(response.getheaders())
    finally:
        connection.close()


def connect(transport):
    status, value, _ = http(
        transport, "/connect", {"protocol": 1, "plugin_instance": PLUGIN, "document": document()}
    )
    assert status == 200
    return value["connection_id"]


def poll_path(connection):
    return "/request?" + urlencode({"connection_id": connection})


def test_connect_with_null_origin_is_read_only_and_does_not_replace_peer(transport):
    payload = {"protocol": 1, "plugin_instance": PLUGIN, "document": document()}
    status, value, headers = http(transport, "/connect", payload, headers={"Origin": "null"})
    assert status == 200
    assert headers["Access-Control-Allow-Origin"] == "null"
    assert headers["Cache-Control"] == "no-store"
    assert value["document"]["marker"] is None
    assert value["native_acceptance"] == value["persistence"] == "unverified"
    status, replacement, _ = http(transport, "/connect", payload)
    assert (status, replacement) == (409, {"error": "already_paired"})
    assert transport.sessions[0].calls == []
    assert len(transport.sessions) == 1


@pytest.mark.parametrize(
    ("headers", "status", "error"),
    [
        ({"Authorization": "Bearer wrong-token"}, 401, "pairing_required"),
        ({"Authorization": "Basic synthetic"}, 401, "pairing_required"),
        ({"Origin": "https://untrusted.invalid"}, 403, "origin_denied"),
        ({"Host": "untrusted.invalid"}, 403, "host_denied"),
    ],
)
def test_transport_boundary_rejects_wrong_token_origin_or_host(transport, headers, status, error):
    actual_status, value, _ = http(transport, "/connect", {}, headers=headers)
    assert (actual_status, value) == (status, {"error": error})
    assert transport.binding.status()["state"] == "disconnected"
    assert transport.sessions == []


@pytest.mark.parametrize(
    ("body", "headers", "status", "error"),
    [
        (b"{}", {"Content-Type": "text/plain"}, 415, "json_required"),
        (b"{}", {"Transfer-Encoding": "chunked"}, 400, "invalid_body"),
        (b"", {"Content-Length": "0"}, 400, "invalid_body"),
        (b"", {"Content-Length": "2097153"}, 400, "invalid_body"),
        (b"{", {}, 400, "invalid_body"),
        (b"[]", {}, 400, "invalid_body"),
        (b"\xff", {}, 400, "invalid_body"),
    ],
)
def test_invalid_http_bodies_are_bounded_and_rejected(transport, body, headers, status, error):
    actual_status, value, _ = http(transport, "/connect", body=body, headers=headers)
    assert (actual_status, value) == (status, {"error": error})
    assert transport.sessions == []


@pytest.mark.parametrize(
    ("payload", "status", "error"),
    [
        (
            {"protocol": 1, "plugin_instance": PLUGIN, "document": document(), "extra": True},
            400,
            "invalid_route_or_fields",
        ),
        ({"protocol": True, "plugin_instance": PLUGIN, "document": document()}, 409, "invalid_binding"),
        (
            {"protocol": 1, "plugin_instance": PLUGIN, "document": {**document(), "extra": True}},
            409,
            "invalid_binding",
        ),
    ],
)
def test_unknown_connection_fields_and_noninteger_protocol_are_rejected(transport, payload, status, error):
    actual_status, value, _ = http(transport, "/connect", payload)
    assert (actual_status, value) == (status, {"error": error})
    assert transport.sessions == []


def test_http_poll_and_response_use_real_core_ids_without_retry(transport):
    connection = connect(transport)
    future = transport.pool.submit(
        transport.binding.call, connection, "frame.create", {"name": "Synthetic frame"}
    )
    assert transport.sessions[0].started.wait(timeout=1.0)
    status, value, _ = http(transport, poll_path(connection), method="GET")
    assert status == 200
    assert value["connection_id"] == connection
    request = value["request"]
    assert request["method"] == "frame.create"
    assert type(request["id"]) is int
    assert request["params"]["expected_plugin_instance"] == PLUGIN
    assert request["params"]["page_id"] == "1:2"
    assert request["params"]["document_marker"] is None
    assert type(request["params"]["deadline_ms"]) is int
    result = {"ok": True, "document": document("synthetic_marker_001"), "data": {"node_id": "3:4"}}
    response = {"connection_id": connection, "id": request["id"], "result": result}
    status, value, _ = http(transport, "/response", {**response, "id": request["id"] + 100})
    assert (status, value) == (409, {"error": "stale_response"})
    status, value, _ = http(transport, "/response", {**response, "extra": True})
    assert (status, value) == (400, {"error": "invalid_route_or_fields"})
    status, value, _ = http(transport, "/response", response)
    assert (status, value) == (200, {"accepted": True})
    assert future.result(timeout=1.0) == result
    status, value, _ = http(transport, "/response", response)
    assert (status, value) == (409, {"error": "stale_response"})
    assert len(transport.sessions[0].calls) == 1
    assert transport.binding.status()["document"]["marker"] == "synthetic_marker_001"


def test_old_http_connection_cannot_poll_or_respond_after_repairing(transport):
    old = connect(transport)
    status, _, _ = http(transport, "/disconnect", {"connection_id": old})
    assert status == 200
    new = connect(transport)
    assert new != old
    status, value, _ = http(transport, poll_path(old), method="GET")
    assert (status, value) == (409, {"error": "stale_connection"})
    status, value, _ = http(transport, "/response", {"connection_id": old, "id": 1, "result": {}})
    assert (status, value) == (409, {"error": "stale_connection"})


@pytest.mark.parametrize("transport", [0.1], indirect=True)
def test_timed_out_mutation_cannot_later_be_delivered_by_http_poll(transport):
    old = connect(transport)
    future = transport.pool.submit(
        transport.binding.call, old, "frame.create", {"name": "Synthetic queued mutation"}
    )
    assert transport.sessions[0].started.wait(timeout=1.0)
    with pytest.raises(BindingError, match="^timeout$"):
        future.result(timeout=2.0)
    assert transport.binding.status()["state"] == "unavailable"
    status, value, _ = http(transport, poll_path(old), method="GET")
    assert (status, value) == (409, {"error": "not_paired"})
    new = connect(transport)
    status, value, _ = http(transport, poll_path(new), method="GET")
    assert (status, value) == (204, None)
    assert len(transport.sessions[0].calls) == 1
    assert transport.sessions[1].calls == []


def test_pairing_token_is_absent_from_status_errors_and_logs(transport, capsys, caplog):
    connection = connect(transport)
    status, value, _ = http(
        transport,
        poll_path(connection),
        method="GET",
        headers={"Authorization": "Bearer " + TOKEN + "-wrong"},
    )
    assert status == 401
    captured = capsys.readouterr()
    assert TOKEN not in json.dumps(value)
    assert TOKEN not in json.dumps(transport.binding.status())
    assert TOKEN not in captured.out + captured.err + caplog.text
