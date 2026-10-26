"""Synthetic binding contracts and real Core HTTP; no Figma host is exercised."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import struct
import urllib.error
import urllib.request
import zlib
from copy import deepcopy

import pytest

from dcc_mcp_figma.binding import BindingError
from dcc_mcp_figma.server import FigmaMcpServer
from dcc_mcp_figma.tools import MAX_EXPORT_BYTES, TOOL_DEFINITIONS, FigmaTools

CONNECTION = "synthetic_connection"
DOCUMENT = {"name": "Synthetic document", "page_id": "1:0", "page_name": "Fixture", "marker": None}


def _png_chunk(kind, body):
    return (
        struct.pack("!I", len(body))
        + kind
        + body
        + struct.pack("!I", binascii.crc32(kind + body) & 0xFFFFFFFF)
    )


PNG = (
    b"\x89PNG\r\n\x1a\n"
    + _png_chunk(b"IHDR", struct.pack("!IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    + _png_chunk(b"IDAT", zlib.compress(b"\x00\x33\x66\xff\xff"))
    + _png_chunk(b"IEND", b"")
)
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'


def export_data(format="PNG", body=None):
    body = (PNG if format == "PNG" else SVG) if body is None else body
    return {
        "node_id": "1:2",
        "format": format,
        "mime_type": "image/png" if format == "PNG" else "image/svg+xml",
        "data_base64": base64.b64encode(body).decode("ascii"),
        "byte_length": len(body),
    }


class SyntheticBinding:
    """In-memory fixture, with no transport, credentials, plugin or native document."""

    def __init__(self, paired=True):
        self.paired = paired
        self.calls = []
        self.callback = None
        self.error = None
        self.result = None

    def status(self):
        return {
            "state": "paired" if self.paired else "disconnected",
            "connection_id": CONNECTION if self.paired else None,
            "document": deepcopy(DOCUMENT) if self.paired else None,
            "native_acceptance": "unverified",
            "persistence": "unverified",
        }

    def set_change_callback(self, callback):
        self.callback = callback
        if callback is not None:
            callback(self.status())

    def set_paired(self, paired):
        self.paired = paired
        if self.callback is not None:
            self.callback(self.status())

    def call(self, connection_id, method, arguments):
        self.calls.append((connection_id, method, deepcopy(arguments)))
        if self.error is not None:
            raise self.error
        if not self.paired:
            raise BindingError("not_paired")
        if connection_id != CONNECTION:
            raise BindingError("stale_connection")
        if self.result is not None:
            return deepcopy(self.result)
        if method == "node.export":
            data = export_data(arguments["format"])
        elif method == "document.read":
            data = {"nodes": [], "limit": arguments["limit"], "synthetic": True}
        else:
            data = {"node_id": "1:2", "synthetic": True}
        return {"ok": True, "document": deepcopy(DOCUMENT), "data": data}


@pytest.fixture
def binding():
    return SyntheticBinding()


@pytest.mark.parametrize(
    "tool,parameters,method,expected",
    [
        ("figma_document__read", {}, "document.read", {"limit": 100}),
        ("figma_nodes__read", {"node_id": "I14:1;11:1"}, "node.read", {"node_id": "I14:1;11:1"}),
        (
            "figma_nodes__create_frame",
            {"name": "Fixture frame", "width": 100, "height": 50},
            "frame.create",
            {"name": "Fixture frame", "width": 100, "height": 50, "x": 0, "y": 0, "fill": "#3366FF"},
        ),
        (
            "figma_nodes__update_frame",
            {"node_id": "1:2", "x": -0.5, "fill": "#12aBcD"},
            "frame.update",
            {"node_id": "1:2", "x": -0.5, "fill": "#12aBcD"},
        ),
    ],
)
def test_typed_tools_invoke_binding_once_and_keep_unverified_result(
    binding, tool, parameters, method, expected
):
    result = FigmaTools(binding).invoke(tool, {"connection_id": CONNECTION, **parameters})
    assert result["success"] is True
    assert result["context"]["document"] == DOCUMENT
    assert result["context"]["data"]["synthetic"] is True
    assert result["context"]["persistence"] == "unverified"
    assert result["context"]["native_acceptance"] == "unverified"
    assert result["postcondition"]["verified"] is False
    assert binding.calls == [(CONNECTION, method, expected)]


def test_status_does_not_invoke_the_host(binding):
    binding.set_paired(False)
    result = FigmaTools(binding).invoke("figma_session__status", {})
    assert result["success"] is True
    assert result["context"]["state"] == "disconnected"
    assert result["context"]["native_acceptance"] == "unverified"
    assert binding.calls == []


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("figma_session__status", {"token": "synthetic-secret"}),
        ("figma_document__read", {}),
        ("figma_document__read", {"connection_id": True}),
        ("figma_document__read", {"connection_id": " "}),
        ("figma_document__read", {"connection_id": "a" * 129}),
        ("figma_document__read", {"connection_id": CONNECTION, "limit": True}),
        ("figma_document__read", {"connection_id": CONNECTION, "limit": 1.5}),
        ("figma_document__read", {"connection_id": CONNECTION, "limit": 0}),
        ("figma_document__read", {"connection_id": CONNECTION, "limit": 201}),
        ("figma_document__read", {"connection_id": CONNECTION, "_meta": {"dcc": {"jobId": "synthetic"}}}),
        (
            "figma_document__read",
            {"connection_id": CONNECTION, "expected_plugin_instance": "synthetic-secret"},
        ),
        ("figma_nodes__read", {"connection_id": CONNECTION, "node_id": ""}),
        ("figma_nodes__read", {"connection_id": CONNECTION, "node_id": "1:2/../synthetic-secret"}),
        ("figma_nodes__read", {"connection_id": CONNECTION, "node_id": "1" * 129}),
        ("figma_nodes__update_frame", {"connection_id": CONNECTION, "node_id": "1:2"}),
        ("figma_nodes__update_frame", {"connection_id": CONNECTION, "node_id": "1:2", "x": True}),
        ("figma_nodes__update_frame", {"connection_id": CONNECTION, "node_id": "1:2", "x": float("nan")}),
        ("figma_nodes__update_frame", {"connection_id": CONNECTION, "node_id": "1:2", "x": float("inf")}),
        ("figma_nodes__update_frame", {"connection_id": CONNECTION, "node_id": "1:2", "x": 1000001}),
        ("figma_nodes__update_frame", {"connection_id": CONNECTION, "node_id": "1:2", "height": False}),
        ("figma_nodes__update_frame", {"connection_id": CONNECTION, "node_id": "1:2", "height": 0.5}),
        ("figma_nodes__update_frame", {"connection_id": CONNECTION, "node_id": "1:2", "width": 8193}),
        ("figma_nodes__update_frame", {"connection_id": CONNECTION, "node_id": "1:2", "name": " "}),
        ("figma_nodes__update_frame", {"connection_id": CONNECTION, "node_id": "1:2", "name": "n" * 121}),
        ("figma_nodes__update_frame", {"connection_id": CONNECTION, "node_id": "1:2", "fill": "#123"}),
        ("figma_nodes__update_frame", {"connection_id": CONNECTION, "node_id": "1:2", "fill": "#GGHHII"}),
        ("figma_nodes__export", {"connection_id": CONNECTION, "node_id": "1:2", "format": "PDF"}),
        (
            "figma_nodes__export",
            {"connection_id": CONNECTION, "node_id": "1:2", "format": "PNG", "path": "synthetic-secret"},
        ),
    ],
)
def test_invalid_input_is_rejected_before_binding_without_echo(binding, tool, arguments):
    result = FigmaTools(binding).invoke(tool, arguments)
    assert result["success"] is False
    assert result["error"] == "invalid_arguments"
    assert result["context"]["dispatched"] is False
    assert result["context"]["outcome"] == "not_dispatched"
    assert binding.calls == []
    assert "synthetic-secret" not in json.dumps(result)


@pytest.mark.parametrize("value", [None, [], "synthetic-secret", True])
def test_non_object_parameters_are_rejected(binding, value):
    assert FigmaTools(binding).invoke("figma_session__status", value)["error"] == "invalid_arguments"
    assert binding.calls == []


@pytest.mark.parametrize("dispatched", [False, True])
def test_binding_failure_retains_fixed_code_and_indeterminate_dispatch(binding, dispatched):
    binding.error = BindingError("timeout", dispatched=dispatched)
    result = FigmaTools(binding).invoke("figma_document__read", {"connection_id": CONNECTION})
    assert result["error"] == "timeout"
    assert result["context"]["dispatched"] is dispatched
    assert result["context"]["outcome"] == ("indeterminate" if dispatched else "not_dispatched")
    assert len(binding.calls) == 1


def test_unknown_binding_exception_is_not_echoed_or_retried(binding):
    binding.error = RuntimeError("synthetic-secret")
    result = FigmaTools(binding).invoke("figma_document__read", {"connection_id": CONNECTION})
    assert result["error"] == "internal_error"
    assert result["context"]["outcome"] == "indeterminate"
    assert "synthetic-secret" not in json.dumps(result)
    assert len(binding.calls) == 1


@pytest.mark.parametrize("format,body", [("PNG", PNG), ("SVG", SVG)])
def test_export_validates_bytes_and_returns_hash_without_writing(binding, tmp_path, format, body):
    binding.result = {"ok": True, "document": DOCUMENT, "data": export_data(format, body)}
    result = FigmaTools(binding).invoke(
        "figma_nodes__export", {"connection_id": CONNECTION, "node_id": "1:2", "format": format}
    )
    assert result["success"] is True
    data = result["context"]["data"]
    assert data["sha256"] == hashlib.sha256(body).hexdigest()
    assert base64.b64decode(data["data_base64"], validate=True) == body
    assert data["byte_length"] == len(body)
    assert list(tmp_path.iterdir()) == []
    assert len(binding.calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"node_id": "9:9"},
        {"format": "SVG"},
        {"mime_type": "image/svg+xml"},
        {"data_base64": "not!base64"},
        {"data_base64": "\u2603"},
        {"data_base64": ""},
        {"byte_length": True},
        {"byte_length": len(PNG) - 1},
        {"byte_length": MAX_EXPORT_BYTES + 1},
        {"data_base64": base64.b64encode(b"not a PNG").decode("ascii"), "byte_length": 9},
        {"path": "synthetic-secret"},
    ],
)
def test_invalid_export_payloads_fail_without_echo_or_retry(binding, changes):
    data = export_data()
    data.update(changes)
    binding.result = {"ok": True, "document": DOCUMENT, "data": data}
    result = FigmaTools(binding).invoke(
        "figma_nodes__export", {"connection_id": CONNECTION, "node_id": "1:2", "format": "PNG"}
    )
    assert result["error"] == "invalid_response"
    assert result["context"]["outcome"] == "indeterminate"
    assert "synthetic-secret" not in json.dumps(result)
    assert len(binding.calls) == 1


@pytest.mark.parametrize("body", [b"<html/>", b"<svg", b'<!DOCTYPE svg [<!ENTITY x "x">]><svg>&x;</svg>'])
def test_svg_export_rejects_invalid_xml_or_declarations(binding, body):
    binding.result = {"ok": True, "document": DOCUMENT, "data": export_data("SVG", body)}
    result = FigmaTools(binding).invoke(
        "figma_nodes__export", {"connection_id": CONNECTION, "node_id": "1:2", "format": "SVG"}
    )
    assert result["error"] == "invalid_response"


@pytest.mark.parametrize("result", [None, [], {"ok": False}, {"ok": 1, "document": DOCUMENT, "data": {}}])
def test_malformed_host_results_are_indeterminate(binding, result):
    if result is None:
        binding.result = {"ok": True, "document": DOCUMENT, "data": {"invalid": float("nan")}}
    else:
        binding.result = result
    response = FigmaTools(binding).invoke("figma_document__read", {"connection_id": CONNECTION})
    assert response["error"] == "invalid_response"
    assert response["context"]["outcome"] == "indeterminate"


def _readyz(url):
    try:
        response = urllib.request.urlopen(url, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read())


def test_real_core_http_discovers_typed_tools_and_tracks_pairing_gate(tmp_path):
    """Use real Core and the official MCP SDK with an explicitly synthetic binding."""
    pytest.importorskip("mcp", reason="The official SDK is test-only and is never installed here.")
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared.exceptions import McpError

    async def exercise():
        binding = SyntheticBinding(paired=False)
        server = FigmaMcpServer(binding, registry_dir=tmp_path)
        assert server.config.host == "127.0.0.1"
        assert server.config.gateway_port == 0
        assert server.config.enable_cors is False
        assert server.readiness.is_ready() is False
        handle = server.start()
        endpoint = handle.mcp_url()
        readyz = endpoint.rsplit("/mcp", 1)[0] + "/v1/readyz"
        try:
            async with streamable_http_client(endpoint) as (read, write, _):  # noqa: SIM117
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    catalogue = await session.list_tools()
                    assert {tool.name for tool in catalogue.tools if tool.name.startswith("figma_")} == {
                        definition["name"] for definition in TOOL_DEFINITIONS
                    }
                    assert "jobs_get_status" in {tool.name for tool in catalogue.tools}
                    for tool in catalogue.tools:
                        if tool.name.startswith("figma_"):
                            assert tool.inputSchema["type"] == "object"
                            assert tool.inputSchema["additionalProperties"] is False
                    with pytest.raises(McpError) as unavailable:
                        await session.call_tool("figma_session__status", {})
                    assert unavailable.value.error.code == -32002
                    status_code, initial = _readyz(readyz)
                    assert status_code == 503
                    assert initial["dcc"] is False
                    assert binding.calls == []

                    binding.set_paired(True)
                    assert server.readiness.is_ready() is True
                    status_code, paired = _readyz(readyz)
                    assert status_code == 200
                    assert paired["dcc"] is True
                    response = await session.call_tool("figma_document__read", {"connection_id": CONNECTION})
                    assert response.isError is False
                    assert response.structuredContent["context"]["data"]["synthetic"] is True
                    assert response.structuredContent["context"]["native_acceptance"] == "unverified"
                    assert binding.calls == [(CONNECTION, "document.read", {"limit": 100})]
                    forged = await session.call_tool(
                        "figma_document__read",
                        {"connection_id": CONNECTION, "_meta": {"dcc": {"jobId": "synthetic_forged"}}},
                    )
                    # Core may consume reserved transport metadata before the Python handler.
                    # It is never a plugin argument or a source of document authority.
                    assert forged.isError is False
                    assert binding.calls[-1] == (CONNECTION, "document.read", {"limit": 100})
                    assert len(binding.calls) == 2

                    export = await session.call_tool(
                        "figma_nodes__export",
                        {"connection_id": CONNECTION, "node_id": "1:2", "format": "PNG"},
                    )
                    pending = export.structuredContent
                    assert pending["status"] == "pending"
                    poll = pending["core_poll"]
                    assert poll["owner"] == "core"
                    assert poll["tool"] == "jobs_get_status"
                    terminal = None
                    for _ in range(100):
                        job = await session.call_tool(poll["tool"], poll["arguments"])
                        terminal = job.structuredContent
                        if terminal["status"] in {"completed", "failed", "cancelled", "interrupted"}:
                            break
                        await asyncio.sleep(0.02)
                    assert terminal["status"] == "completed"
                    assert terminal["result"]["success"] is True
                    assert terminal["result"]["context"]["data"]["sha256"] == hashlib.sha256(PNG).hexdigest()
                    assert binding.calls[-1] == (
                        CONNECTION,
                        "node.export",
                        {"node_id": "1:2", "format": "PNG"},
                    )

                    binding.set_paired(False)
                    assert server.readiness.is_ready() is False
                    assert _readyz(readyz)[0] == 503
                    with pytest.raises(McpError) as disconnected:
                        await session.call_tool("figma_document__read", {"connection_id": CONNECTION})
                    assert disconnected.value.error.code == -32002
                    # Core's built-in job query is independent of the host readiness gate.
                    settled = await session.call_tool(poll["tool"], poll["arguments"])
                    assert settled.structuredContent["status"] == "completed"
                    assert settled.structuredContent["result"]["success"] is True
                    assert len(binding.calls) == 3
        finally:
            server.close()
            server.close()
        assert server.readiness.is_ready() is False
        with pytest.raises(RuntimeError):
            server.start()

    asyncio.run(exercise())
