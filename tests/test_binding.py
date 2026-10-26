"""Synthetic pairing contracts backed by the installed Core request queue."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from copy import deepcopy
from types import SimpleNamespace

import pytest
from dcc_mcp_core import BridgeTimeoutError, ReverseBridgeSession

from dcc_mcp_figma.binding import BindingError, FigmaBinding

TOKEN = "synthetic-pairing-token-contract-only-00000001"
PLUGIN = "synthetic_plugin_instance_0001"


def document(marker=None):
    return {"name": "Synthetic document", "page_id": "1:2", "page_name": "Synthetic page", "marker": marker}


class ObservedSession:
    """Delegate all correlation to Core while exposing deterministic test events."""

    def __init__(self, *, timeout):
        self.core = ReverseBridgeSession(timeout=timeout)
        self.started = threading.Event()
        self.calls = []
        self.closed = []

    def call(self, method, **params):
        self.calls.append((method, deepcopy(params)))
        self.started.set()
        return self.core.call(method, **params)

    def next_request(self, timeout=None):
        return self.core.next_request(timeout=timeout)

    def submit_response(self, request_id, *, result):
        return self.core.submit_response(request_id, result=result)

    def close(self, reason):
        self.closed.append(reason)
        self.core.close(reason)


@pytest.fixture
def harness():
    sessions = []

    def factory(*, timeout):
        session = ObservedSession(timeout=timeout)
        sessions.append(session)
        return session

    binding = FigmaBinding(TOKEN, timeout=1.0, session_factory=factory)
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        yield SimpleNamespace(binding=binding, sessions=sessions, pool=pool)
    finally:
        binding.close()
        pool.shutdown(wait=True)


def paired(harness, marker=None):
    return harness.binding.connect(PLUGIN, document(marker))["connection_id"]


def pending(harness, connection, method="document.read", arguments=None):
    future = harness.pool.submit(harness.binding.call, connection, method, arguments or {})
    assert harness.sessions[-1].started.wait(timeout=1.0)
    polled = harness.binding.poll(connection, timeout=1.0)
    assert polled is not None
    return future, polled["request"]


def reply(harness, connection, request, marker=None, data=None):
    result = {"ok": True, "document": document(marker), "data": {} if data is None else data}
    assert harness.binding.respond(connection, request["id"], result) is True
    return result


@pytest.mark.parametrize(
    "token", ["x" * 31, "x" * 257, "界" * 32, "x" * 31 + "\x00", "x" * 31 + "\x7f", "x" * 32 + "\n"]
)
def test_header_incompatible_tokens_are_rejected_without_creating_a_session(token):
    calls = []
    with pytest.raises(ValueError, match="printable ASCII"):
        FigmaBinding(token, session_factory=lambda **kwargs: calls.append(kwargs))
    assert calls == []


def test_printable_ascii_token_boundaries_are_supported():
    for token in ("!" * 32, "~" * 256):
        binding = FigmaBinding(token)
        assert binding.authenticate("Bearer " + token)


def test_cli_rejects_header_incompatible_token_before_creating_a_listener(monkeypatch, capsys):
    from dcc_mcp_figma import __main__, http_bridge

    def forbidden_listener(*_args, **_kwargs):
        pytest.fail("An invalid pairing token must not create a listener.")

    monkeypatch.setenv("SYNTHETIC_FIGMA_TOKEN", "界" * 32)
    monkeypatch.setattr("sys.argv", ["dcc-mcp-figma", "serve", "--token-env", "SYNTHETIC_FIGMA_TOKEN"])
    monkeypatch.setattr(http_bridge, "PluginHttpBridge", forbidden_listener)
    with pytest.raises(SystemExit) as caught:
        __main__.main()
    assert caught.value.code == 2
    error = capsys.readouterr().err
    assert "printable ASCII" in error
    assert "界" not in error


def test_idle_lease_expires_without_host_calls_and_polling_renews_it():
    now = [0.0]
    sessions = []

    def factory(**kwargs):
        session = ObservedSession(**kwargs)
        sessions.append(session)
        return session

    binding = FigmaBinding(TOKEN, lease_clock=lambda: now[0], session_factory=factory)
    try:
        connection = binding.connect(PLUGIN, document())["connection_id"]
        now[0] = 29
        assert binding.poll(connection, timeout=0) is None
        now[0] = 58
        assert binding.status()["state"] == "paired"
        now[0] = 59
        assert binding.expire_idle() is True
        assert binding.status()["state"] == "unavailable"
        assert sessions[0].calls == []
        assert len(sessions[0].closed) == 1
        assert binding.expire_idle() is False
        with pytest.raises(BindingError, match="not_paired"):
            binding.call(connection, "document.read", {})
    finally:
        binding.close()


@pytest.mark.parametrize("complete", [True, False])
def test_lease_preserves_a_legal_120_second_call_but_bounds_an_abandoned_call(complete):
    now = [0.0]
    sessions = []

    def factory(**kwargs):
        session = ObservedSession(**kwargs)
        sessions.append(session)
        return session

    binding = FigmaBinding(
        TOKEN, timeout=120, clock=lambda: 1000 + now[0], lease_clock=lambda: now[0], session_factory=factory
    )
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        connection = binding.connect(PLUGIN, document())["connection_id"]
        future = pool.submit(binding.call, connection, "document.read", {})
        assert sessions[0].started.wait(timeout=1)
        now[0] = 31
        assert binding.expire_idle() is False
        now[0] = 119
        assert binding.status()["state"] == "paired"
        if complete:
            request = binding.poll(connection, timeout=0)["request"]
            assert binding.respond(
                connection, request["id"], {"ok": True, "document": document(), "data": {}}
            )
            assert future.result(timeout=1)["ok"] is True
            now[0] = 148
            assert binding.status()["state"] == "paired"
            now[0] = 149
            assert binding.expire_idle() is True
        else:
            now[0] = 125
            assert binding.expire_idle() is True
            with pytest.raises(BindingError, match="unavailable"):
                future.result(timeout=1)
        assert len(sessions[0].calls) == 1
        assert len(sessions[0].closed) == 1
        assert binding.status()["state"] == "unavailable"
    finally:
        binding.close()
        pool.shutdown(wait=True)


def test_pairing_is_read_only_and_status_is_a_defensive_copy(harness):
    original = document()
    status = harness.binding.connect(PLUGIN, original)
    assert status["state"] == "paired"
    assert status["native_acceptance"] == status["persistence"] == "unverified"
    assert status["document"] == original
    assert status["document"]["marker"] is None
    status["document"]["page_id"] = "changed"
    original["name"] = "changed"
    assert harness.binding.status()["document"] == document()
    assert harness.sessions[0].calls == []
    assert harness.binding.poll(status["connection_id"], timeout=0) is None


def test_active_pair_cannot_be_replaced(harness):
    connection = paired(harness)
    with pytest.raises(BindingError, match="^already_paired$") as rejected:
        harness.binding.connect("synthetic_second_instance_0002", document())
    assert rejected.value.dispatched is False
    assert harness.binding.status()["connection_id"] == connection
    assert len(harness.sessions) == 1


@pytest.mark.parametrize(
    "invalid_document",
    [
        None,
        {},
        {**document(), "extra": True},
        {**document(), "page_id": "../foreign"},
        {**document(), "marker": "invalid marker"},
        {**document(), "name": 1},
    ],
)
def test_invalid_document_shape_is_rejected_before_pairing(harness, invalid_document):
    with pytest.raises(BindingError, match="^invalid_binding$"):
        harness.binding.connect(PLUGIN, invalid_document)
    assert harness.binding.status()["state"] == "disconnected"
    assert harness.sessions == []


@pytest.mark.parametrize(
    "header", [None, "", "Basic synthetic", "Bearer wrong-token", "Bearer " + TOKEN + "x"]
)
def test_pairing_token_authentication_does_not_echo_material(harness, header):
    assert harness.binding.authenticate(header) is False
    assert TOKEN not in json.dumps(harness.binding.status())
    assert harness.binding.authenticate("Bearer " + TOKEN) is True


@pytest.mark.parametrize("key", ["expected_plugin_instance", "page_id", "document_marker", "deadline_ms"])
def test_caller_cannot_override_document_or_deadline_scope(harness, key):
    connection = paired(harness)
    with pytest.raises(BindingError, match="^invalid_arguments$") as rejected:
        harness.binding.call(connection, "document.read", {key: "foreign"})
    assert rejected.value.dispatched is False
    assert harness.sessions[0].calls == []


def test_real_core_queue_correlates_one_call_and_rejects_bad_or_duplicate_responses(harness):
    connection = paired(harness)
    future, request = pending(harness, connection, "node.read", {"node_id": "3:4"})
    assert request["jsonrpc"] == "2.0"
    assert request["method"] == "node.read"
    assert type(request["id"]) is int
    assert request["params"]["node_id"] == "3:4"
    assert request["params"]["expected_plugin_instance"] == PLUGIN
    assert request["params"]["page_id"] == "1:2"
    assert request["params"]["document_marker"] is None
    assert type(request["params"]["deadline_ms"]) is int
    with pytest.raises(BindingError, match="^stale_response$"):
        harness.binding.respond(connection, request["id"] + 100, {})
    with pytest.raises(BindingError, match="^stale_response$"):
        harness.binding.respond(connection, True, {})
    assert future.done() is False
    result = reply(harness, connection, request, data={"node_id": "3:4"})
    assert future.result(timeout=1.0) == result
    with pytest.raises(BindingError, match="^stale_response$"):
        harness.binding.respond(connection, request["id"], result)
    assert len(harness.sessions[0].calls) == 1
    assert harness.binding.poll(connection, timeout=0) is None


def test_reconnected_peer_rejects_old_connection_and_response(harness):
    old = paired(harness)
    harness.binding.disconnect(old)
    new = paired(harness)
    assert old != new
    with pytest.raises(BindingError, match="^stale_connection$"):
        harness.binding.poll(old, timeout=0)
    with pytest.raises(BindingError, match="^stale_connection$"):
        harness.binding.respond(old, 1, {})
    assert harness.binding.poll(new, timeout=0) is None


def test_concurrent_call_is_rejected_without_queueing_or_retry(harness):
    connection = paired(harness)
    future, request = pending(harness, connection)
    with pytest.raises(BindingError, match="^busy$") as rejected:
        harness.binding.call(connection, "frame.create", {"name": "Synthetic"})
    assert rejected.value.dispatched is False
    result = reply(harness, connection, request)
    assert future.result(timeout=1.0) == result
    assert len(harness.sessions[0].calls) == 1


def test_first_write_marker_is_retained_in_every_followup(harness):
    connection = paired(harness)
    future, request = pending(harness, connection, "frame.create", {"name": "Synthetic frame"})
    assert request["params"]["document_marker"] is None
    result = reply(harness, connection, request, marker="synthetic_marker_001", data={"node_id": "3:4"})
    assert future.result(timeout=1.0) == result
    future, request = pending(harness, connection, "frame.update", {"node_id": "3:4"})
    assert request["params"]["document_marker"] == "synthetic_marker_001"
    result = reply(harness, connection, request, marker="synthetic_marker_001")
    assert future.result(timeout=1.0) == result
    assert harness.binding.status()["document"]["marker"] == "synthetic_marker_001"


@pytest.mark.parametrize("method", ["document.read", "node.read", "node.export", "frame.update"])
def test_marker_change_on_bound_document_fails_closed(harness, method):
    connection = paired(harness, marker="synthetic_marker_001")
    future, request = pending(harness, connection, method)
    reply(harness, connection, request, marker="synthetic_foreign_marker")
    with pytest.raises(BindingError, match="^scope_changed$") as rejected:
        future.result(timeout=1.0)
    assert rejected.value.dispatched is True
    assert harness.binding.status()["state"] == "unavailable"
    assert len(harness.sessions[0].closed) == 1
    assert len(harness.sessions[0].calls) == 1


def test_read_only_call_cannot_establish_a_document_marker(harness):
    connection = paired(harness)
    future, request = pending(harness, connection)
    reply(harness, connection, request, marker="synthetic_unexpected_marker")
    with pytest.raises(BindingError, match="^scope_changed$"):
        future.result(timeout=1.0)
    assert harness.binding.status()["state"] == "unavailable"
    assert len(harness.sessions[0].calls) == 1


@pytest.mark.parametrize("invalid_code", [[], {}])
def test_malformed_plugin_error_code_fails_closed(harness, invalid_code):
    connection = paired(harness)
    future, request = pending(harness, connection)
    assert harness.binding.respond(connection, request["id"], {"ok": False, "error": invalid_code}) is True
    with pytest.raises(BindingError, match="^plugin_error$") as rejected:
        future.result(timeout=1.0)
    assert rejected.value.dispatched is True
    assert harness.binding.status()["state"] == "unavailable"
    assert len(harness.sessions[0].calls) == len(harness.sessions[0].closed) == 1


def test_expired_deadline_is_rejected_before_a_queued_mutation_is_delivered():
    sessions = []
    clock = SimpleNamespace(now=1000.0)

    def factory(*, timeout):
        session = ObservedSession(timeout=timeout)
        sessions.append(session)
        return session

    binding = FigmaBinding(TOKEN, timeout=1.0, clock=lambda: clock.now, session_factory=factory)
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            connection = binding.connect(PLUGIN, document())["connection_id"]
            future = pool.submit(binding.call, connection, "frame.create", {"name": "Synthetic mutation"})
            assert sessions[0].started.wait(timeout=1.0)
            assert sessions[0].calls[0][1]["deadline_ms"] == 1001000
            clock.now = 1002.0
            with pytest.raises(BindingError, match="^deadline_expired$"):
                binding.poll(connection, timeout=1.0)
            with pytest.raises(BindingError, match="^unavailable$"):
                future.result(timeout=1.0)
            assert binding.status()["state"] == "unavailable"
            assert len(sessions[0].calls) == len(sessions[0].closed) == 1
        finally:
            binding.close()


def test_timeout_closes_whole_binding_before_queued_mutation_can_be_polled():
    sessions = []

    def factory(*, timeout):
        session = ObservedSession(timeout=timeout)
        sessions.append(session)
        return session

    binding = FigmaBinding(TOKEN, timeout=0.1, session_factory=factory)
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            connection = binding.connect(PLUGIN, document())["connection_id"]
            future = pool.submit(binding.call, connection, "frame.create", {"name": "Synthetic mutation"})
            assert sessions[0].started.wait(timeout=1.0)
            with pytest.raises(BindingError, match="^timeout$") as rejected:
                future.result(timeout=2.0)
            assert rejected.value.dispatched is True
            assert binding.status()["state"] == "unavailable"
            assert binding.status()["connection_id"] is None
            with pytest.raises(BindingError, match="^not_paired$"):
                binding.poll(connection, timeout=0)
            with pytest.raises(BindingError, match="^not_paired$"):
                binding.call(connection, "document.read", {})
            assert len(sessions[0].calls) == len(sessions[0].closed) == 1
            new_connection = binding.connect(PLUGIN, document())["connection_id"]
            assert binding.poll(new_connection, timeout=0) is None
        finally:
            binding.close()


@pytest.mark.parametrize("error_type", [FutureTimeoutError, BridgeTimeoutError])
def test_public_timeout_kinds_are_classified_and_closed_without_replay(error_type):
    class FailingSession:
        def __init__(self, *, timeout):
            self.calls = 0
            self.closed = False

        def call(self, method, **params):
            self.calls += 1
            raise error_type("synthetic-private-error-detail")

        def close(self, reason):
            self.closed = True

    session = FailingSession(timeout=1)
    binding = FigmaBinding(TOKEN, session_factory=lambda **_options: session)
    connection = binding.connect(PLUGIN, document())["connection_id"]
    with pytest.raises(BindingError, match="^timeout$") as caught:
        binding.call(connection, "frame.create", {})
    assert caught.value.dispatched is True
    assert session.closed is True
    assert session.calls == 1
    assert binding.status()["state"] == "unavailable"
    assert "private" not in str(caught.value)
