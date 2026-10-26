"""Synthetic launch hints only; no Runtime, process launch, or Figma host runs."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from dcc_mcp_figma.server import FigmaMcpServer

_OPERATION = "782f3a55-732d-48f8-930e-31716cc5aa4e"
_FIELDS = (
    ("DCC_MCP_START_OPERATION_ID", "dcc_mcp_operation_id", 128),
    ("DCC_MCP_START_PROJECT", "dcc_mcp_project", 32768),
)
_DEFAULT_METADATA = {
    "dcc_mcp_instance_type": "standalone",
    "adapter": "dcc-mcp-figma",
    "native_acceptance": "unverified",
}


class SyntheticBinding:
    """Minimal readiness fixture; launch metadata must never invoke the host."""

    def __init__(self):
        self.paired = False
        self.callback = None

    def status(self):
        return {"state": "paired" if self.paired else "disconnected"}

    def set_change_callback(self, callback):
        self.callback = callback
        if callback is not None:
            callback(self.status())

    def set_paired(self, paired):
        self.paired = paired
        self.callback(self.status())

    def call(self, *_args, **_kwargs):
        pytest.fail("Launch hints must not dispatch a host operation.")


@pytest.fixture(autouse=True)
def clean_launch_hints(monkeypatch):
    for source, _target, _limit in _FIELDS:
        monkeypatch.delenv(source, raising=False)


@pytest.fixture
def server(tmp_path):
    instance = FigmaMcpServer(SyntheticBinding(), registry_dir=tmp_path / "synthetic-registry")
    try:
        yield instance
    finally:
        instance.close()


def test_absent_launch_hints_preserve_existing_metadata(server):
    assert server.config.instance_metadata == _DEFAULT_METADATA


def test_core_launch_sources_are_copied_without_resolving_or_mutating(monkeypatch, tmp_path):
    # Core supplies an existing canonical project; the adapter copies its string
    # rather than probing it, selecting another project, or creating a directory.
    project = str(tmp_path / "synthetic-not-created-project")
    monkeypatch.setenv("DCC_MCP_START_OPERATION_ID", _OPERATION)
    monkeypatch.setenv("DCC_MCP_START_PROJECT", project)
    instance = FigmaMcpServer(SyntheticBinding(), registry_dir=tmp_path / "registry")
    try:
        assert instance.config.instance_metadata == {
            **_DEFAULT_METADATA,
            "dcc_mcp_operation_id": _OPERATION,
            "dcc_mcp_project": project,
        }
        assert not Path(project).exists()
        assert instance.config.instance_metadata["dcc_mcp_operation_id"] == _OPERATION
        monkeypatch.setenv("DCC_MCP_START_OPERATION_ID", "a-later-environment-value")
        assert instance.config.instance_metadata["dcc_mcp_operation_id"] == _OPERATION
    finally:
        instance.close()


@pytest.mark.parametrize(("source", "target", "_limit"), _FIELDS)
def test_values_follow_core_reader_trim_rule(monkeypatch, tmp_path, source, target, _limit):
    value = _OPERATION if target == "dcc_mcp_operation_id" else str(tmp_path / "synthetic-project")
    monkeypatch.setenv(source, " \t" + value + "\r\n")
    instance = FigmaMcpServer(SyntheticBinding(), registry_dir=tmp_path / "registry")
    try:
        assert instance.config.instance_metadata[target] == value
    finally:
        instance.close()


@pytest.mark.parametrize(("source", "target", "limit"), _FIELDS)
@pytest.mark.parametrize("extra", [0, 1])
def test_adapter_length_limits_omit_instead_of_truncating(
    monkeypatch, tmp_path, source, target, limit, extra
):
    # Core metadata has no UUID/path-length validator. These are explicitly
    # adapter-defined character bounds; Core-generated UUIDv4 IDs fit intact.
    value = "x" * (limit + extra)
    # Test the adapter's boundary independently of Windows' 32767-character
    # process-environment limit; this synthetic mapping never changes native env.
    monkeypatch.setattr("dcc_mcp_figma.server.os.environ", {source: value})
    instance = FigmaMcpServer(SyntheticBinding(), registry_dir=tmp_path / "registry")
    try:
        if extra:
            assert target not in instance.config.instance_metadata
        else:
            assert instance.config.instance_metadata[target] == value
    finally:
        instance.close()


@pytest.mark.parametrize(("source", "target", "_limit"), _FIELDS)
@pytest.mark.parametrize(
    "value", ["", " \t\r\n", "first\nsecond", "first\tsecond", "first\x01second", "first\x7fsecond"]
)
def test_empty_or_control_character_hints_are_omitted(monkeypatch, tmp_path, source, target, _limit, value):
    monkeypatch.setenv(source, value)
    instance = FigmaMcpServer(SyntheticBinding(), registry_dir=tmp_path / "registry")
    try:
        assert target not in instance.config.instance_metadata
        assert instance.config.instance_metadata == _DEFAULT_METADATA
    finally:
        instance.close()


def test_only_two_sources_are_read_and_no_token_or_environment_is_published(monkeypatch, tmp_path):
    secret = "synthetic-secret-never-a-real-credential"
    monkeypatch.setenv("DCC_MCP_FIGMA_TOKEN", secret)
    monkeypatch.setenv("DCC_MCP_START_DCC_TYPE", "a-synthetic-other-dcc")
    monkeypatch.setenv("DCC_MCP_LAUNCH_ID", "unrelated-launch-id")
    monkeypatch.setenv("dcc_mcp_operation_id", "not-a-supported-source")
    monkeypatch.setenv("dcc_mcp_project", "not-a-supported-source")
    instance = FigmaMcpServer(SyntheticBinding(), registry_dir=tmp_path / "registry")
    try:
        assert instance.config.instance_metadata == _DEFAULT_METADATA
        assert secret not in json.dumps(instance.config.instance_metadata)
        assert instance.config.dcc_type == "figma"
    finally:
        instance.close()


def test_launch_hints_do_not_pair_or_change_readiness_permissions_or_native_claims(monkeypatch, tmp_path):
    monkeypatch.setenv("DCC_MCP_START_OPERATION_ID", _OPERATION)
    monkeypatch.setenv("DCC_MCP_START_PROJECT", str(tmp_path))
    binding = SyntheticBinding()
    instance = FigmaMcpServer(binding, registry_dir=tmp_path / "registry")
    try:
        assert binding.status()["state"] == "disconnected"
        assert instance.readiness.is_ready() is False
        assert instance.config.host == "127.0.0.1"
        assert instance.config.gateway_port == 0
        assert instance.config.enable_cors is False
        assert instance.config.instance_metadata["native_acceptance"] == "unverified"
        binding.set_paired(True)
        assert instance.readiness.is_ready() is True
        binding.set_paired(False)
        assert instance.readiness.is_ready() is False
        assert instance.config.instance_metadata["dcc_mcp_operation_id"] == _OPERATION
    finally:
        instance.close()
    assert instance.readiness.is_ready() is False


def test_server_module_keeps_python37_grammar():
    import dcc_mcp_figma.server as server_module

    ast.parse(Path(server_module.__file__).read_text(encoding="utf-8"), feature_version=(3, 7))
