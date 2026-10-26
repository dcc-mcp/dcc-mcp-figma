"""Official MCP/Core through the prepared shipping plugin, synthetic Figma only."""

import asyncio
import base64
import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from dcc_mcp_figma.binding import FigmaBinding
from dcc_mcp_figma.blueprint import validate_blueprint
from dcc_mcp_figma.client import discover, invoke
from dcc_mcp_figma.http_bridge import PluginHttpBridge
from dcc_mcp_figma.manifest import prepare_plugin
from dcc_mcp_figma.server import FigmaMcpServer


def _line(process):
    output = queue.Queue()
    threading.Thread(target=lambda: output.put(process.stdout.readline()), daemon=True).start()
    line = output.get(timeout=15)
    assert line, "Synthetic peer stopped before returning evidence."
    return json.loads(line)


def _start_peer(node, port, prepared, token):
    return subprocess.Popen(
        [
            node,
            str(Path(__file__).parent / "support" / "browser_peer.cjs"),
            str(port),
            str(prepared),
            "blueprint",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=dict(os.environ, DCC_FIGMA_SYNTHETIC_TOKEN=token),
    )


def exercise_prepared_bundle(tmp_path, wire, expected_count, export_key):
    node = shutil.which("node")
    if not node:
        pytest.skip("The synthetic peer needs an existing Node installation.")
    pytest.importorskip("mcp")
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    wire = validate_blueprint(wire)
    token = "synthetic-blueprint-token-not-a-credential-0001"
    prepared = tmp_path / "prepared"
    prepare_plugin("1234567890123456", 19061, prepared)

    async def exercise():
        binding = FigmaBinding(token, timeout=10)
        transport = PluginHttpBridge(binding).start()
        server = FigmaMcpServer(binding, registry_dir=tmp_path / "registry")
        handle = server.start()
        process = await asyncio.get_event_loop().run_in_executor(
            None,
            _start_peer,
            node,
            transport.port,
            prepared,
            token,
        )
        try:
            ready = await asyncio.get_event_loop().run_in_executor(None, _line, process)
            assert ready["prepared_bundle"] is True and ready["evidence"] == "synthetic-shipping-ui-and-main"
            connection = binding.status()["connection_id"]
            async with streamable_http_client(handle.mcp_url()) as (read, write, _):  # noqa: SIM117 - Py3.7.
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    catalogue = await discover(session)
                    applied = await invoke(
                        session,
                        catalogue,
                        "figma_design__apply_blueprint",
                        {
                            "connection_id": connection,
                            "operation_id": "synthetic_apply_001",
                            "blueprint": wire,
                        },
                    )
                    assert applied["persistence"] == applied["native_acceptance"] == "unverified"
                    data = applied["data"]
                    assert data["expanded_node_count"] == expected_count
                    assert data["receipt"]["stage"] == "complete"
                    result = await invoke(
                        session,
                        catalogue,
                        "figma_design__read_blueprint",
                        {
                            "connection_id": connection,
                            "operation_id": "synthetic_apply_001",
                            "root_node_id": data["run_root_id"],
                        },
                    )
                    observed = result["data"]
                    assert observed["truncated"] is False
                    assert observed["expanded_node_count"] == expected_count
                    assert len(observed["variables"]) == 30
                    assert any(item.get("characters") == "Email" for item in observed["nodes"])
                    assert any(item.get("main_component_id") for item in observed["nodes"])
                    assert observed["receipt"]["mutation_attempted"] is False
                    exported = await invoke(
                        session,
                        catalogue,
                        "figma_nodes__export",
                        {
                            "connection_id": connection,
                            "node_id": data["nodes"][export_key],
                            "format": "SVG",
                        },
                    )
                    raw = base64.b64decode(exported["data"]["data_base64"], validate=True)
                    assert hashlib.sha256(raw).hexdigest() == exported["data"]["sha256"]
                    assert binding.status()["state"] == "paired"
                    return {"application": data, "readback": observed}
        finally:
            binding.close()
            process.terminate()
            process.communicate(timeout=10)
            transport.close()
            server.close()

    return asyncio.run(exercise())


def test_prepared_bundle_blueprint_round_trip_over_actual_core_jobs(tmp_path):
    wire = json.loads(
        (Path(__file__).parent / "support" / "blueprint_fixture.json").read_text(encoding="utf-8")
    )
    exercise_prepared_bundle(tmp_path, wire, 16, "screen/fixture")
