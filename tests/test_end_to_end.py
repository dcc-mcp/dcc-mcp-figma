"""Real Core HTTP and production plugin code, with a synthetic Figma host."""

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
from dcc_mcp_figma.http_bridge import PluginHttpBridge
from dcc_mcp_figma.server import FigmaMcpServer

TOKEN = "synthetic-test-token-not-a-real-credential-0001"


def _line(process):
    output = queue.Queue()
    threading.Thread(target=lambda: output.put(process.stdout.readline()), daemon=True).start()
    line = output.get(timeout=10)
    assert line, "Synthetic peer exited before producing evidence."
    return json.loads(line)


def _start_peer(node, port, environment):
    return subprocess.Popen(
        [node, str(Path(__file__).parent / "support" / "browser_peer.cjs"), str(port)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )


async def _call(session, name, arguments):
    response = await session.call_tool(name, arguments)
    data = response.structuredContent
    if isinstance(data, dict) and data.get("job_id"):
        route = data["core_poll"]
        assert route["owner"] == "core" and route["tool"] == "jobs_get_status"
        for _ in range(300):
            state = await session.call_tool(route["tool"], route["arguments"])
            terminal = state.structuredContent
            if terminal.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
                assert terminal["status"] == "completed", terminal
                data = terminal["result"]
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("Synthetic Core job did not reach a terminal state.")
    assert data["success"] is True, data
    assert data["context"]["native_acceptance"] == "unverified"
    assert data["context"]["persistence"] == "unverified"
    return data["context"]


def test_core_to_shipping_ui_main_and_runtime_read_write_export(tmp_path):
    """No Figma app is launched: browser DOM and Plugin API are explicit fixtures."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node must already be installed; this test does not install it.")
    pytest.importorskip("mcp")
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def exercise():
        binding = FigmaBinding(TOKEN, timeout=5)
        transport = PluginHttpBridge(binding).start()
        server = FigmaMcpServer(binding, registry_dir=tmp_path / "registry")
        handle = server.start()
        environment = dict(os.environ, DCC_FIGMA_SYNTHETIC_TOKEN=TOKEN)
        process = await asyncio.get_event_loop().run_in_executor(
            None, _start_peer, node, transport.port, environment
        )
        try:
            assert _line(process)["evidence"] == "synthetic-shipping-ui-and-main"
            current = binding.status()
            assert current["state"] == "paired" and current["document"]["marker"] is None
            connection = current["connection_id"]
            async with streamable_http_client(handle.mcp_url()) as (read, write, _):  # noqa: SIM117 - Py3.7.
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    snapshot = await _call(
                        session, "figma_document__read", {"connection_id": connection, "limit": 1}
                    )
                    assert len(snapshot["data"]["nodes"]) == 1
                    created = await _call(
                        session,
                        "figma_nodes__create_frame",
                        {
                            "connection_id": connection,
                            "name": "Synthetic frame through Core",
                            "width": 320,
                            "height": 180,
                        },
                    )
                    node_id = created["data"]["id"]
                    assert created["document"]["marker"] is not None
                    updated = await _call(
                        session,
                        "figma_nodes__update_frame",
                        {
                            "connection_id": connection,
                            "node_id": node_id,
                            "name": "Edited through Core",
                            "width": 360,
                            "fill": "#00AA88",
                        },
                    )
                    assert updated["data"]["width"] == 360
                    reread = await _call(
                        session, "figma_nodes__read", {"connection_id": connection, "node_id": node_id}
                    )
                    assert reread["data"]["name"] == "Edited through Core"
                    for format_name in ("PNG", "SVG"):
                        exported = await _call(
                            session,
                            "figma_nodes__export",
                            {
                                "connection_id": connection,
                                "node_id": node_id,
                                "format": format_name,
                            },
                        )
                        artifact = exported["data"]
                        raw = base64.b64decode(artifact["data_base64"], validate=True)
                        assert len(raw) == artifact["byte_length"]
                        assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]
            process.stdin.write("inspect\n")
            process.stdin.flush()
            evidence = _line(process)
            assert evidence["native_acceptance"] == "not_run"
            assert len([write for write in evidence["writes"] if write[0] == "createFrame"]) == 1
            assert len([write for write in evidence["writes"] if write[0] == "setPluginData"]) == 1
            assert any(call[0] == "getNodeByIdAsync" and call[1] == node_id for call in evidence["calls"])
            assert len([call for call in evidence["calls"] if call[0] == "exportAsync"]) == 2
        finally:
            process.terminate()
            process.communicate(timeout=5)
            transport.close()
            server.close()

    asyncio.run(exercise())
