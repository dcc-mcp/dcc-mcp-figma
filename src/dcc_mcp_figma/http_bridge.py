"""Loopback-only authenticated plugin polling, without a second RPC queue."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .binding import BindingError

_MAX_BODY = 2 * 1024 * 1024


class PluginHttpBridge:
    """Expose only bounded plugin transport routes on IPv4 loopback."""

    def __init__(self, binding, *, port=0):
        self.binding = binding
        self._thread = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "DccMcpFigma/0.1"

            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def log_message(self, *_args):
                # Paths, authorization and document payloads are never logged.
                pass

            def _send(self, status, value=None):
                body = b"" if value is None else json.dumps(value).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                if self.headers.get("Origin") == "null":
                    self.send_header("Access-Control-Allow-Origin", "null")
                    self.send_header("Vary", "Origin")
                try:
                    self.end_headers()
                    if body:
                        self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    # A disconnected plugin must not cause a retry or raw log.
                    return

            def _boundary(self, *, authenticated=True):
                if self.headers.get("Host") != "127.0.0.1:" + str(owner.port):
                    self._send(403, {"error": "host_denied"})
                    return False
                if self.headers.get("Origin") not in (None, "null"):
                    self._send(403, {"error": "origin_denied"})
                    return False
                if authenticated and not owner.binding.authenticate(self.headers.get("Authorization")):
                    self._send(401, {"error": "pairing_required"})
                    return False
                return True

            def do_OPTIONS(self):
                if not self._boundary(authenticated=False):
                    return
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "null")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):
                if not self._boundary():
                    return
                route = urlsplit(self.path)
                query = parse_qs(route.query, keep_blank_values=True)
                if (
                    route.path != "/request"
                    or set(query) != {"connection_id"}
                    or len(query["connection_id"]) != 1
                ):
                    self._send(404, {"error": "route_not_found"})
                    return
                try:
                    result = owner.binding.poll(query["connection_id"][0])
                    self._send(204 if result is None else 200, result)
                except BindingError as error:
                    self._send(409, {"error": error.code})

            def do_POST(self):
                if not self._boundary():
                    return
                if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                    self._send(415, {"error": "json_required"})
                    return
                if self.headers.get("Transfer-Encoding"):
                    self._send(400, {"error": "invalid_body"})
                    return
                try:
                    size = int(self.headers.get("Content-Length", ""))
                    if not 0 < size <= _MAX_BODY:
                        raise ValueError
                    value = json.loads(self.rfile.read(size).decode("utf-8"))
                    if not isinstance(value, dict):
                        raise TypeError
                except (TypeError, ValueError, UnicodeError):
                    self._send(400, {"error": "invalid_body"})
                    return
                try:
                    if self.path == "/connect" and set(value) == {"protocol", "plugin_instance", "document"}:
                        if type(value["protocol"]) is not int or value["protocol"] != 1:
                            raise BindingError("invalid_binding")
                        result = owner.binding.connect(value["plugin_instance"], value["document"])
                    elif self.path == "/response" and set(value) == {"connection_id", "id", "result"}:
                        owner.binding.respond(value["connection_id"], value["id"], value["result"])
                        result = {"accepted": True}
                    elif self.path == "/disconnect" and set(value) == {"connection_id"}:
                        result = owner.binding.disconnect(value["connection_id"])
                    else:
                        self._send(400, {"error": "invalid_route_or_fields"})
                        return
                    self._send(200, result)
                except BindingError as error:
                    self._send(409, {"error": error.code})
                except Exception:  # noqa: BLE001 - never expose private callback or transport exceptions.
                    self._send(500, {"error": "bridge_unavailable"})

        class Server(ThreadingHTTPServer):
            def service_actions(self):
                # Reuse the listener loop; do not add a second watchdog/service.
                owner.binding.expire_idle()

        self._server = Server(("127.0.0.1", port), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]

    @property
    def url(self):
        return "http://127.0.0.1:" + str(self.port)

    def start(self):
        if self._thread is not None:
            raise RuntimeError("The plugin transport is already started.")
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self):
        self.binding.close()
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=2)
            self._thread = None
        self._server.server_close()
