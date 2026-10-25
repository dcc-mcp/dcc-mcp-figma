"""Actual trial orchestration and prepared plugin bytes against a synthetic host.

Core HTTP, the official MCP SDK, the production trial client and the prepared
UI/main/runtime execute unchanged. The browser DOM, document and assigned ID
are explicit fixtures; these tests establish no native Figma acceptance.
"""

import asyncio
import hashlib
import importlib.util
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from dcc_mcp_figma.binding import FigmaBinding
from dcc_mcp_figma.client import TrialError
from dcc_mcp_figma.http_bridge import PluginHttpBridge
from dcc_mcp_figma.manifest import prepare_plugin
from dcc_mcp_figma.server import FigmaMcpServer

_ROOT = Path(__file__).resolve().parents[1]
_TOKEN = "synthetic-test-token-not-a-real-credential-0001"
_PLUGIN_ID = "1234567890123456"


def _line(process):
    output = queue.Queue()
    threading.Thread(target=lambda: output.put(process.stdout.readline()), daemon=True).start()
    line = output.get(timeout=10)
    assert line, "The synthetic prepared-plugin peer stopped before producing evidence."
    return json.loads(line)


def _command(process, command):
    process.stdin.write(command + "\n")
    process.stdin.flush()
    return _line(process)


@contextmanager
def _expected_trial_failure():
    # The official SDK may wrap a local TrialError in nested AnyIO exception
    # groups on context exit. Check every leaf without requiring Python 3.11.
    with pytest.raises(Exception) as rejected:
        yield

    def leaves(error):
        children = getattr(error, "exceptions", None)
        if children is None:
            return [error]
        return [leaf for child in children for leaf in leaves(child)]

    errors = leaves(rejected.value)
    assert errors and all(isinstance(error, TrialError) for error in errors)


@pytest.fixture
def native_trial():
    pytest.importorskip("mcp")
    spec = importlib.util.spec_from_file_location(
        "production_native_trial", _ROOT / "scripts/native_trial.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _paired_trial(tmp_path, mode="native-trial"):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node must already be installed; these tests never install it.")
    binding = FigmaBinding(_TOKEN, timeout=5)
    transport = PluginHttpBridge(binding).start()
    server = FigmaMcpServer(binding, registry_dir=tmp_path / "registry")
    process = None
    try:
        handle = server.start()
        plugin = tmp_path / "prepared-plugin"
        prepared = prepare_plugin(_PLUGIN_ID, transport.port, plugin)
        assert prepared["plugin_installed"] is prepared["plugin_id_verified_by_figma"] is False
        environment = dict(os.environ, DCC_FIGMA_SYNTHETIC_TOKEN=_TOKEN)
        process = subprocess.Popen(
            [
                node,
                str(Path(__file__).parent / "support/browser_peer.cjs"),
                str(transport.port),
                str(plugin),
                mode,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        ready = _line(process)
        assert ready["ready"] is ready["prepared_bundle"] is True
        assert ready["mode"] == mode
        assert ready["code_sha256"] == hashlib.sha256((plugin / "code.js").read_bytes()).hexdigest()
        assert binding.status()["state"] == "paired"
        assert binding.status()["document"]["marker"] is None
        yield SimpleNamespace(binding=binding, process=process, mcp_url=handle.mcp_url(), plugin=plugin)
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)
        transport.close()
        server.close()


def _arguments(peer, output, *, phase="write", evidence=None):
    return SimpleNamespace(mcp_url=peer.mcp_url, output_dir=str(output), phase=phase, evidence=evidence)


def _assert_edited_node(node):
    for field, expected in {
        "type": "FRAME",
        "name": "DCC-MCP Native Trial Edited",
        "width": 360,
        "height": 180,
        "fill": "#00AA88",
    }.items():
        assert node[field] == expected
    assert isinstance(node["id"], str) and node["id"]


def _assert_no_replayed_mutation(evidence, *, formats):
    assert evidence["native_acceptance"] == "not_run"
    assert len([write for write in evidence["writes"] if write[0] == "createFrame"]) == 1
    assert len([write for write in evidence["writes"] if write[0] == "setPluginData"]) == 1
    assert [call[2]["format"] for call in evidence["calls"] if call[0] == "exportAsync"] == formats


def test_actual_trial_write_and_reconnect_use_prepared_plugin_and_real_core(tmp_path, native_trial):
    with _paired_trial(tmp_path) as peer:
        output = tmp_path / "write-evidence"
        environment = dict(os.environ, PYTHONPATH=str(_ROOT / "src"))
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(_ROOT / "scripts/native_trial.py"),
                "--mcp-url",
                peer.mcp_url,
                "--output-dir",
                str(output),
            ],
            capture_output=True,
            text=True,
            env=environment,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        summary = json.loads(completed.stdout)
        assert summary == {"phase": "write", "native_effects": "observed", "persistence": "unverified"}
        assert "verified" not in summary
        written = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
        assert written["phase"] == "write" and written["stage"] == "complete"
        assert written["native_effects"] == "observed"
        assert written["persistence"] == "unverified"
        _assert_edited_node(written["node"])
        assert written["expected_node"]["id"] == written["node"]["id"]
        assert written["expected_node"]["fill"] == "#00AA88"
        assert {artifact["file"] for artifact in written["artifacts"]} == {
            "native-trial.png",
            "native-trial.svg",
        }
        for artifact in written["artifacts"]:
            raw = (output / artifact["file"]).read_bytes()
            assert raw and len(raw) == artifact["bytes"]
            assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]
        assert (output / "native-trial.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert b"<svg" in (output / "native-trial.svg").read_bytes()
        before = _command(peer.process, "inspect")
        _assert_no_replayed_mutation(before, formats=["PNG", "SVG"])
        assert _command(peer.process, "reconnect")["reconnected"] is True
        assert peer.binding.status()["connection_id"] != written["connection_id"]
        assert peer.binding.status()["document"]["marker"] == written["document"]["marker"]
        readback = asyncio.run(
            native_trial.trial(
                _arguments(
                    peer,
                    tmp_path / "readback-evidence",
                    phase="reconnect-readback",
                    evidence=str(output / "receipt.json"),
                )
            )
        )
        assert readback["reconnect_readback"] == "passed"
        assert readback["persistence"] == "unverified"
        assert readback["node"] == written["node"]
        after = _command(peer.process, "inspect")
        assert after["writes"] == before["writes"]
        _assert_no_replayed_mutation(after, formats=["PNG", "SVG"])


def test_actual_trial_export_failure_retains_partial_receipt_without_replay(tmp_path, native_trial):
    with _paired_trial(tmp_path, "native-trial-export-failure") as peer:
        output = tmp_path / "partial-evidence"
        with _expected_trial_failure():
            asyncio.run(native_trial.trial(_arguments(peer, output)))
        receipt = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
        assert receipt["stage"] == "export_svg"
        assert receipt["native_effects"] == "not_completed"
        assert receipt["native_outcome"] == "indeterminate"
        assert receipt["persistence"] == "unverified"
        _assert_edited_node(receipt["node"])
        assert len(receipt["artifacts"]) == 1
        artifact = receipt["artifacts"][0]
        assert artifact["file"] == "native-trial.png"
        assert hashlib.sha256((output / artifact["file"]).read_bytes()).hexdigest() == artifact["sha256"]
        assert not (output / "native-trial.svg").exists()
        assert peer.binding.status()["state"] == "unavailable"
        _assert_no_replayed_mutation(_command(peer.process, "inspect"), formats=["PNG", "SVG"])


def test_actual_trial_does_not_overwrite_existing_output_or_start_operations(tmp_path, native_trial):
    with _paired_trial(tmp_path) as peer:
        output = tmp_path / "existing-output"
        output.mkdir()
        sentinel = output / "keep.txt"
        sentinel.write_bytes(b"Existing private output stays unchanged.")
        before = _command(peer.process, "inspect")
        with pytest.raises(FileExistsError):
            asyncio.run(native_trial.trial(_arguments(peer, output)))
        assert sentinel.read_bytes() == b"Existing private output stays unchanged."
        assert sorted(path.name for path in output.iterdir()) == ["keep.txt"]
        after = _command(peer.process, "inspect")
        assert after["writes"] == before["writes"]
        assert after["calls"] == before["calls"]


@pytest.mark.parametrize("mode", ["native-trial-wrong-width", "native-trial-wrong-fill"])
def test_actual_trial_rejects_wrong_observed_dimensions_or_color(tmp_path, native_trial, mode):
    with _paired_trial(tmp_path, mode) as peer:
        output = tmp_path / "rejected-evidence"
        with _expected_trial_failure():
            asyncio.run(native_trial.trial(_arguments(peer, output)))
        receipt = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
        assert receipt["native_effects"] == "not_completed"
        assert receipt["native_outcome"] == "indeterminate"
        assert receipt["persistence"] == "unverified"
        assert not (output / "native-trial.png").exists()
        assert not (output / "native-trial.svg").exists()
        _assert_no_replayed_mutation(_command(peer.process, "inspect"), formats=[])


@pytest.mark.parametrize(
    ("field", "value"), [("native_effects", "not_completed"), ("width", 359), ("fill", "#FF0000")]
)
def test_invalid_prior_receipt_is_read_only_and_creates_no_output(tmp_path, native_trial, field, value):
    previous = tmp_path / "invalid-receipt.json"
    payload = {
        "phase": "write",
        "native_effects": "observed",
        "node": {
            "id": "1:10",
            "type": "FRAME",
            "name": "DCC-MCP Native Trial Edited",
            "width": 360,
            "height": 180,
            "fill": "#00AA88",
        },
    }
    if field == "native_effects":
        payload[field] = value
    else:
        payload["node"][field] = value
    original = json.dumps(payload).encode("utf-8")
    previous.write_bytes(original)
    output = tmp_path / "must-not-be-created"
    args = SimpleNamespace(
        mcp_url="http://127.0.0.1:19061/mcp",
        output_dir=str(output),
        phase="reconnect-readback",
        evidence=str(previous),
    )
    with pytest.raises(TrialError):
        asyncio.run(native_trial.trial(args))
    assert previous.read_bytes() == original
    assert not output.exists()
