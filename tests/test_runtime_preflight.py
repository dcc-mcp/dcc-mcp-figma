"""Synthetic Runtime bootstrap fixtures; no Runtime payload or Figma host runs."""

from __future__ import annotations

import ast
import builtins
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import dcc_mcp_figma.runtime_preflight as preflight

PRIVATE = "synthetic-secret-and-private-path"


@pytest.fixture
def selected_root(monkeypatch, tmp_path):
    root = tmp_path / PRIVATE
    root.mkdir()
    monkeypatch.setenv("DCC_MCP_RUNTIME_ROOT", str(root))
    return root


def install_synthetic_bootstrap(monkeypatch, *, result=None, error=None, default_root=None, root_error=None):
    calls = []

    def require_adapter(adapter_id):
        calls.append(adapter_id)
        if error is not None:
            raise error
        return result

    def runtime_root():
        # Synthetic version of the documented env-or-package-relative selection.
        if root_error is not None:
            raise root_error
        selected = os.environ.get("DCC_MCP_RUNTIME_ROOT")
        return Path(selected) if selected else default_root

    bootstrap = SimpleNamespace(runtime_root=runtime_root, require_adapter=require_adapter)

    def import_module(name):
        assert name == "dcc_mcp_runtime.bootstrap"
        return bootstrap

    monkeypatch.setattr(preflight.importlib, "import_module", import_module)
    return calls


def assert_blocked(report, reason, accepted=False):
    assert report["reason"] == reason
    assert report["handshake_accepted"] is accepted
    assert report["ready_for_launch"] is False
    assert report["success"] is False
    assert report["trusted_authority"] is False
    assert report["status"] == "blocked"
    assert report["upstream_blockers"] == [
        "trusted_runtime_payload_contract_missing",
        "adapter_launch_contract_missing",
        "dependency_isolation_unverified",
        "runtime_capability_probe_contract_missing",
    ]
    serialized = json.dumps(report, allow_nan=False)
    assert PRIVATE not in serialized


@pytest.mark.parametrize("value", [None, ""])
def test_default_selection_delegates_to_package_relative_root(monkeypatch, tmp_path, value):
    if value is None:
        monkeypatch.delenv("DCC_MCP_RUNTIME_ROOT", raising=False)
    else:
        monkeypatch.setenv("DCC_MCP_RUNTIME_ROOT", value)
    calls = install_synthetic_bootstrap(
        monkeypatch, default_root=tmp_path, result=SimpleNamespace(accepted=True, handshake=object())
    )
    report = preflight.runtime_preflight()
    assert_blocked(report, "runtime_handshake_accepted_launch_blocked", True)
    assert report["selection_source"] == "package_relative"
    assert calls == ["figma"]


def test_explicit_selection_uses_the_same_public_resolver(monkeypatch, selected_root):
    calls = install_synthetic_bootstrap(
        monkeypatch, result=SimpleNamespace(accepted=True, handshake=object())
    )
    report = preflight.runtime_preflight()
    assert_blocked(report, "runtime_handshake_accepted_launch_blocked", True)
    assert report["selection_source"] == "operator_environment"
    assert calls == ["figma"]


def test_missing_root_does_not_handshake_or_create_it(monkeypatch, tmp_path):
    root = tmp_path / PRIVATE
    monkeypatch.setenv("DCC_MCP_RUNTIME_ROOT", str(root))
    calls = install_synthetic_bootstrap(monkeypatch)
    assert_blocked(preflight.runtime_preflight(), "runtime_root_unavailable")
    assert not root.exists()
    assert calls == []


def test_root_file_is_not_a_runtime(monkeypatch, tmp_path):
    root = tmp_path / PRIVATE
    root.write_text("synthetic fixture", encoding="utf-8")
    monkeypatch.setenv("DCC_MCP_RUNTIME_ROOT", str(root))
    calls = install_synthetic_bootstrap(monkeypatch)
    assert_blocked(preflight.runtime_preflight(), "runtime_root_unavailable")
    assert calls == []


def test_inaccessible_root_is_safe(monkeypatch, selected_root):
    def unavailable(_root):
        raise PermissionError(PRIVATE)

    install_synthetic_bootstrap(monkeypatch)
    monkeypatch.setattr(preflight.os.path, "isdir", unavailable)
    assert_blocked(preflight.runtime_preflight(), "runtime_access_denied")


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (PermissionError(PRIVATE), "runtime_access_denied"),
        (OSError(PRIVATE), "runtime_root_unavailable"),
        (ValueError(PRIVATE), "runtime_root_invalid"),
        (TypeError(PRIVATE), "runtime_root_invalid"),
        (AttributeError(PRIVATE), "runtime_root_invalid"),
        (RuntimeError(PRIVATE), "runtime_root_failed"),
    ],
)
def test_resolver_failure_is_safe_without_handshake(monkeypatch, selected_root, error, reason):
    calls = install_synthetic_bootstrap(monkeypatch, root_error=error)
    assert_blocked(preflight.runtime_preflight(), reason)
    assert calls == []


def test_resolved_directory_alone_does_not_establish_installed_runtime(monkeypatch, tmp_path):
    monkeypatch.delenv("DCC_MCP_RUNTIME_ROOT", raising=False)
    calls = install_synthetic_bootstrap(monkeypatch, default_root=tmp_path, error=FileNotFoundError(PRIVATE))
    report = preflight.runtime_preflight()
    assert_blocked(report, "runtime_manifest_missing")
    assert report["selection_source"] == "package_relative"
    assert calls == ["figma"]


@pytest.mark.parametrize("version", [(3, 7), (3, 8)])
def test_package_minimum_python_checked_before_import(monkeypatch, selected_root, version):
    monkeypatch.setattr(preflight.sys, "version_info", version)
    calls = install_synthetic_bootstrap(monkeypatch)
    assert_blocked(preflight.runtime_preflight(), "runtime_python_unsupported")
    assert calls == []


@pytest.mark.parametrize("version", [(3, 9), (3, 10), (3, 11), (3, 12)])
def test_package_compatibility_is_not_payload_abi(monkeypatch, selected_root, version):
    # Official package >=3.9 differs from the example manifest's cp311 ABI.
    monkeypatch.setattr(preflight.sys, "version_info", version)
    calls = install_synthetic_bootstrap(
        monkeypatch,
        result=SimpleNamespace(accepted=True, handshake=object()),
    )
    assert_blocked(preflight.runtime_preflight(), "runtime_handshake_accepted_launch_blocked", True)
    assert calls == ["figma"]


@pytest.mark.parametrize("module", ["dcc_mcp_runtime", "dcc_mcp_runtime.bootstrap"])
def test_runtime_package_missing_is_safe(monkeypatch, selected_root, module):
    def unavailable(_name):
        raise ModuleNotFoundError(PRIVATE, name=module)

    monkeypatch.setattr(preflight.importlib, "import_module", unavailable)
    assert_blocked(preflight.runtime_preflight(), "runtime_package_unavailable")


@pytest.mark.parametrize(
    "error",
    [ModuleNotFoundError(PRIVATE, name=PRIVATE), ImportError(PRIVATE), RuntimeError(PRIVATE)],
)
def test_import_failures_do_not_leak_or_fallback(monkeypatch, selected_root, error):
    calls = []

    def unavailable(name):
        calls.append(name)
        raise error

    monkeypatch.setattr(preflight.importlib, "import_module", unavailable)
    assert_blocked(preflight.runtime_preflight(), "runtime_import_failed")
    assert calls == ["dcc_mcp_runtime.bootstrap"]


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (FileNotFoundError(PRIVATE), "runtime_manifest_missing"),
        (PermissionError(PRIVATE), "runtime_access_denied"),
        (ValueError(PRIVATE), "runtime_manifest_invalid"),
        (TypeError(PRIVATE), "runtime_manifest_invalid"),
        (KeyError(PRIVATE), "runtime_manifest_invalid"),
        (RuntimeError(PRIVATE), "runtime_handshake_failed"),
        (OSError(PRIVATE), "runtime_handshake_failed"),
    ],
)
def test_bootstrap_failure_is_safe_and_never_retried(monkeypatch, selected_root, error, reason):
    calls = install_synthetic_bootstrap(monkeypatch, error=error)
    assert_blocked(preflight.runtime_preflight(), reason)
    assert calls == ["figma"]


@pytest.mark.parametrize("reason", sorted(preflight._REJECTIONS))
def test_official_stable_rejection_codes(monkeypatch, selected_root, reason):
    error = RuntimeError("DCC_MCP_RUNTIME_HANDSHAKE_FAILED:" + reason)
    calls = install_synthetic_bootstrap(monkeypatch, error=error)
    assert_blocked(preflight.runtime_preflight(), reason)
    assert calls == ["figma"]


def test_unknown_or_suffixed_rejection_does_not_echo_payload(monkeypatch, selected_root):
    error = RuntimeError("DCC_MCP_RUNTIME_HANDSHAKE_FAILED:python_abi_mismatch:" + PRIVATE)
    install_synthetic_bootstrap(monkeypatch, error=error)
    assert_blocked(preflight.runtime_preflight(), "runtime_handshake_failed")


@pytest.mark.parametrize("reason", sorted(preflight._REJECTIONS) + [PRIVATE])
def test_negative_result_is_not_authority(monkeypatch, selected_root, reason):
    calls = install_synthetic_bootstrap(
        monkeypatch,
        result=SimpleNamespace(accepted=False, reason=reason, handshake=object()),
    )
    expected = reason if reason in preflight._REJECTIONS else "runtime_handshake_rejected"
    assert_blocked(preflight.runtime_preflight(), expected)
    assert calls == ["figma"]


@pytest.mark.parametrize("value", [True, 1, "true"])
def test_malformed_accepted_result_is_not_authority(monkeypatch, selected_root, value):
    install_synthetic_bootstrap(monkeypatch, result=SimpleNamespace(accepted=value, handshake=None))
    expected = "runtime_handshake_invalid" if value is True else "runtime_handshake_rejected"
    assert_blocked(preflight.runtime_preflight(), expected)


def test_provider_payload_is_not_copied_into_report(monkeypatch, selected_root):
    install_synthetic_bootstrap(
        monkeypatch,
        result=SimpleNamespace(
            accepted=True,
            handshake=SimpleNamespace(runtime_id=PRIVATE, signature="approved", capabilities=(PRIVATE,)),
        ),
    )
    report = preflight.runtime_preflight()
    assert_blocked(report, "runtime_handshake_accepted_launch_blocked", True)
    assert "handshake" not in report
    report["upstream_blockers"].clear()
    assert preflight.runtime_preflight()["upstream_blockers"]
    assert list(selected_root.iterdir()) == []


def test_preflight_never_spawns_installs_or_falls_back(monkeypatch, selected_root):
    def forbidden(*_args, **_kwargs):
        pytest.fail("A contract-only preflight attempted to execute a process.")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(os, "execv", forbidden)
    monkeypatch.setattr(os, "execve", forbidden)
    calls = install_synthetic_bootstrap(
        monkeypatch, result=SimpleNamespace(accepted=True, handshake=object())
    )
    assert_blocked(preflight.runtime_preflight(), "runtime_handshake_accepted_launch_blocked", True)
    assert calls == ["figma"]
    assert list(selected_root.iterdir()) == []


def test_cli_returns_two_even_when_manifest_handshake_is_accepted(monkeypatch, selected_root, capsys):
    from dcc_mcp_figma.__main__ import main

    monkeypatch.setattr(preflight.sys, "argv", ["dcc-mcp-figma", "runtime-preflight"])
    calls = install_synthetic_bootstrap(
        monkeypatch, result=SimpleNamespace(accepted=True, handshake=object())
    )
    assert main() == 2
    assert_blocked(json.loads(capsys.readouterr().out), "runtime_handshake_accepted_launch_blocked", True)
    assert calls == ["figma"]


def test_cli_wiring_returns_two_and_only_json_without_starting_services(monkeypatch, capsys):
    from dcc_mcp_figma.__main__ import main

    report = {"success": False, "ready_for_launch": False, "reason": "synthetic_blocked"}
    calls = []

    def synthetic_report():
        calls.append("preflight")
        return report

    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("dcc_mcp_core") or (level and name in {"binding", "http_bridge", "server"}):
            pytest.fail("Runtime preflight attempted a service/Core import.")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(preflight, "runtime_preflight", synthetic_report)
    monkeypatch.setattr(preflight.sys, "argv", ["dcc-mcp-figma", "runtime-preflight"])
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert main() == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == report
    assert captured.err == ""
    assert calls == ["preflight"]


def test_adapter_module_keeps_python37_grammar():
    source = Path(preflight.__file__).read_text(encoding="utf-8")
    ast.parse(source, feature_version=(3, 7))
