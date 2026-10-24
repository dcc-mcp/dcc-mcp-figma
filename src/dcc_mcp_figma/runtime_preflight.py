"""Read-only shared Runtime contract check; never install or launch a payload.

The public dcc-mcp-runtime 0.2.0 package requires Python >=3.9. Its example
manifest targets CPython 3.11 / cp311-win_amd64, which is a separate payload ABI
declaration, not the package's minimum Python version. This module itself keeps
the adapter's Python 3.7 syntax compatibility and imports Runtime only lazily.
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any, Dict

_ROOT_ENV = "DCC_MCP_RUNTIME_ROOT"
_HANDSHAKE_ERROR_PREFIX = "DCC_MCP_RUNTIME_HANDSHAKE_FAILED:"
_REJECTIONS = frozenset(
    (
        "embedded_adapter_requires_host_runtime",
        "python_abi_mismatch",
        "dcc_mcp_core_mismatch",
    )
)
_UPSTREAM_BLOCKERS = (
    "trusted_runtime_payload_contract_missing",
    "adapter_launch_contract_missing",
    "dependency_isolation_unverified",
    "runtime_capability_probe_contract_missing",
)


def _report(reason: str, selection_source: str, handshake_accepted: bool = False) -> Dict[str, Any]:  # noqa: UP006 - Python 3.7 typing compatibility.
    """Return only fixed, JSON-safe diagnostics; no provider payload is echoed."""
    return {
        "success": False,
        "status": "blocked",
        "runtime_provider": "dcc-mcp-runtime",
        "adapter_id": "figma",
        "selection_source": selection_source,
        "reason": reason,
        "handshake_accepted": handshake_accepted,
        "ready_for_launch": False,
        "trusted_authority": False,
        "upstream_blockers": list(_UPSTREAM_BLOCKERS),
    }


def runtime_preflight() -> Dict[str, Any]:  # noqa: UP006 - Python 3.7 typing compatibility.
    """Delegate Runtime selection publicly, without fallback, retry, or mutation.

    An accepted public manifest handshake carries declarations and a capability
    fingerprint. It does not verify a signature, the running interpreter/Core,
    dependency isolation, or a launch command. The current public contract has
    no such trusted payload/launcher/probe interfaces, so launch remains blocked.
    """
    selection_source = "operator_environment" if os.environ.get(_ROOT_ENV) else "package_relative"

    def report(reason, accepted=False):
        return _report(reason, selection_source, accepted)

    # Follow the package's requires-python, not its example payload's cp311 ABI.
    if sys.version_info < (3, 9):
        return report("runtime_python_unsupported")

    try:
        bootstrap = importlib.import_module("dcc_mcp_runtime.bootstrap")
    except ModuleNotFoundError as error:
        if error.name in ("dcc_mcp_runtime", "dcc_mcp_runtime.bootstrap"):
            return report("runtime_package_unavailable")
        return report("runtime_import_failed")
    except Exception:  # noqa: BLE001 - Foreign import failures must not leak private diagnostics.
        return report("runtime_import_failed")

    try:
        # Reuse the package's env-or-package-relative resolver, not an adapter
        # search of PATH, system Python, or another project's virtualenv.
        root = bootstrap.runtime_root()
        if not os.path.isdir(root):
            return report("runtime_root_unavailable")
    except PermissionError:
        return report("runtime_access_denied")
    except OSError:
        return report("runtime_root_unavailable")
    except (ValueError, TypeError, AttributeError):
        return report("runtime_root_invalid")
    except Exception:  # noqa: BLE001 - Foreign resolver errors must not disclose local paths.
        return report("runtime_root_failed")

    try:
        result = bootstrap.require_adapter("figma")
        accepted = getattr(result, "accepted", None)
        if accepted is not True:
            reason = getattr(result, "reason", None)
            if isinstance(reason, str) and reason in _REJECTIONS:
                return report(reason)
            return report("runtime_handshake_rejected")
        if getattr(result, "handshake", None) is None:
            return report("runtime_handshake_invalid")
    except FileNotFoundError:
        return report("runtime_manifest_missing")
    except PermissionError:
        return report("runtime_access_denied")
    except (ValueError, TypeError, KeyError):
        return report("runtime_manifest_invalid")
    except RuntimeError as error:
        # require_adapter exposes only these documented stable negotiation codes.
        # Never propagate arbitrary exception text or treat it as authorization.
        for reason in _REJECTIONS:
            if error.args == (_HANDSHAKE_ERROR_PREFIX + reason,):
                return report(reason)
        return report("runtime_handshake_failed")
    except Exception:  # noqa: BLE001 - Foreign bootstrap failures must not leak private diagnostics.
        return report("runtime_handshake_failed")

    return report("runtime_handshake_accepted_launch_blocked", accepted=True)
