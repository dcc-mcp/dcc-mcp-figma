"""Pair one plugin/document using Core's reverse request-correlation seam."""

from __future__ import annotations

import hmac
import math
import re
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from copy import deepcopy
from uuid import uuid4

from dcc_mcp_core import BridgeTimeoutError, ReverseBridgeSession

_METHODS = {"document.read", "node.read", "frame.create", "frame.update", "node.export"}
_RESERVED = {"expected_plugin_instance", "page_id", "document_marker", "deadline_ms"}
_CODES = {
    "not_paired",
    "stale_connection",
    "already_paired",
    "invalid_binding",
    "invalid_arguments",
    "busy",
    "unavailable",
    "timeout",
    "invalid_response",
    "stale_response",
    "plugin_error",
    "scope_changed",
    "deadline_expired",
    "host_error",
    "unknown_method",
}


class BindingError(Exception):
    """Fixed adapter failure without upstream exceptions or pairing material."""

    def __init__(self, code, *, dispatched=False):
        self.code = code if isinstance(code, str) and code in _CODES else "plugin_error"
        self.dispatched = dispatched
        super().__init__(self.code)


def _document(value):
    if not isinstance(value, dict) or set(value) != {"name", "page_id", "page_name", "marker"}:
        raise BindingError("invalid_binding")
    if any(not isinstance(value[key], str) or len(value[key]) > 512 for key in ("name", "page_name")):
        raise BindingError("invalid_binding")
    if not isinstance(value["page_id"], str) or not re.fullmatch(r"[A-Za-z0-9:;_-]{1,128}", value["page_id"]):
        raise BindingError("invalid_binding")
    marker = value["marker"]
    if marker is not None and (
        not isinstance(marker, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", marker)
    ):
        raise BindingError("invalid_binding")
    return deepcopy(value)


class FigmaBinding:
    """Transport policy around one caller-approved, document-bound Core session.

    The operator supplies the pairing token. No credential, host, document or
    OAuth grant is created here. Connection IDs are correlation identifiers.
    """

    def __init__(self, token, *, timeout=30.0, clock=time.time, session_factory=ReverseBridgeSession):
        if not isinstance(token, str) or not 32 <= len(token) <= 256 or any(c.isspace() for c in token):
            raise ValueError(
                "An operator-provided pairing token of 32 to 256 non-space characters is required."
            )
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 120
        ):
            raise ValueError("timeout must be finite and between zero and 120 seconds.")
        self._token = token
        self._timeout = timeout
        self._clock = clock
        self._session_factory = session_factory
        self._lock = threading.RLock()
        self._call_lock = threading.Lock()
        self._record = None
        self._state = "disconnected"
        self._change_callback = None

    def authenticate(self, authorization):
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            return False
        return hmac.compare_digest(authorization[7:].encode("utf-8"), self._token.encode("utf-8"))

    def set_change_callback(self, callback):
        self._change_callback = callback
        self._notify()

    def _notify(self):
        if self._change_callback is not None:
            self._change_callback(self.status())

    def status(self):
        with self._lock:
            record = self._record
            return {
                "state": self._state,
                "connection_id": record["id"] if record else None,
                "document": deepcopy(record["document"]) if record else None,
                "native_acceptance": "unverified",
                "persistence": "unverified",
            }

    def connect(self, plugin_instance, document):
        if not isinstance(plugin_instance, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", plugin_instance):
            raise BindingError("invalid_binding")
        document = _document(document)
        with self._lock:
            if self._record is not None:
                raise BindingError("already_paired")
            self._record = {
                "id": uuid4().hex,
                "plugin_instance": plugin_instance,
                "document": document,
                "session": self._session_factory(timeout=self._timeout),
                "delivered": set(),
            }
            self._state = "paired"
        self._notify()
        return self.status()

    def _current(self, connection_id):
        record = self._record
        if record is None:
            raise BindingError("not_paired")
        if not isinstance(connection_id, str) or connection_id != record["id"]:
            raise BindingError("stale_connection")
        return record

    def _invalidate(self, record, state="unavailable"):
        with self._lock:
            if self._record is not record:
                return
            self._record = None
            self._state = state
            record["session"].close("Figma plugin connection ended.")
        self._notify()

    def disconnect(self, connection_id):
        with self._lock:
            record = self._current(connection_id)
        self._invalidate(record, "disconnected")
        return self.status()

    def close(self):
        with self._lock:
            record = self._record
        if record:
            self._invalidate(record, "disconnected")

    def call(self, connection_id, method, arguments):
        if method not in _METHODS or not isinstance(arguments, dict) or _RESERVED.intersection(arguments):
            raise BindingError("invalid_arguments")
        if not self._call_lock.acquire(blocking=False):
            raise BindingError("busy")
        try:
            with self._lock:
                record = self._current(connection_id)
                params = deepcopy(arguments)
                params.update(
                    expected_plugin_instance=record["plugin_instance"],
                    page_id=record["document"]["page_id"],
                    document_marker=record["document"]["marker"],
                    deadline_ms=int((self._clock() + self._timeout) * 1000),
                )
            try:
                result = record["session"].call(method, **params)
            except Exception as error:  # noqa: BLE001 - invalidate after any foreign transport failure.
                self._invalidate(record)
                # Future timeouts are distinct from builtin TimeoutError before Python 3.11.
                code = (
                    "timeout"
                    if isinstance(error, (BridgeTimeoutError, FutureTimeoutError, TimeoutError))
                    else "unavailable"
                )
                raise BindingError(code, dispatched=True) from None
            try:
                with self._lock:
                    self._current(connection_id)
                    if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                        raise BindingError("invalid_response")
                    if result["ok"] is not True:
                        raise BindingError(result.get("error", "plugin_error"))
                    document = _document(result.get("document"))
                    if document["page_id"] != record["document"]["page_id"] or "data" not in result:
                        raise BindingError("invalid_response")
                    previous = record["document"]["marker"]
                    if method in {"frame.create", "frame.update"}:
                        if (
                            document["marker"] is None
                            or previous is not None
                            and document["marker"] != previous
                        ):
                            raise BindingError("scope_changed")
                    elif document["marker"] != previous:
                        raise BindingError("scope_changed")
                    record["document"] = document
                    return deepcopy(result)
            except BindingError as error:
                self._invalidate(record)
                raise BindingError(error.code, dispatched=True) from None
        finally:
            self._call_lock.release()

    def poll(self, connection_id, *, timeout=0.5):
        with self._lock:
            record = self._current(connection_id)
        request = record["session"].next_request(timeout=min(max(timeout, 0), 1.0))
        with self._lock:
            if self._record is not record:
                raise BindingError("stale_connection")
            if request is None:
                return None
            if request.params.get("deadline_ms", 0) <= self._clock() * 1000:
                self._invalidate(record)
                raise BindingError("deadline_expired")
            record["delivered"].add(request.id)
            return {"connection_id": connection_id, "request": request.to_jsonrpc()}

    def respond(self, connection_id, request_id, result):
        with self._lock:
            record = self._current(connection_id)
            if type(request_id) is not int or request_id not in record["delivered"]:
                raise BindingError("stale_response")
            record["delivered"].remove(request_id)
            accepted = record["session"].submit_response(request_id, result=deepcopy(result))
            if not accepted:
                self._invalidate(record)
                raise BindingError("stale_response")
        return True
