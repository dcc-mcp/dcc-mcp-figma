"""Public Core MCP composition for the unreleased Figma adapter."""

from __future__ import annotations

import json
import os
from uuid import UUID

from dcc_mcp_core import McpHttpConfig, McpHttpServer, ReadinessProbe, ToolRegistry

from . import __version__
from .tools import TOOL_DEFINITIONS, FigmaTools

# Core's registry reader trims strings and has no public metadata length cap.
# These are adapter limits, not Core requirements; omit invalid values rather
# than truncate identifiers or resolve paths against a different working dir.
_LAUNCH_METADATA_FIELDS = (
    ("DCC_MCP_START_OPERATION_ID", "dcc_mcp_operation_id", 128),
    ("DCC_MCP_START_PROJECT", "dcc_mcp_project", 32768),
)
_ASYNC_TOOLS = {"figma_nodes__export", "figma_design__apply_blueprint", "figma_design__read_blueprint"}


def _launch_metadata():
    """Copy only Core's two startup hints; neither grants plugin authority."""
    metadata = {}
    for source, target, limit in _LAUNCH_METADATA_FIELDS:
        value = os.environ.get(source, "").strip()
        if value and len(value) <= limit and all(ord(char) >= 32 and ord(char) != 127 for char in value):
            metadata[target] = value
    return metadata


class FigmaMcpServer:
    """Own one Core listener while the caller owns the plugin binding.

    Core's readiness gate applies to adapter-native calls, including status.
    Its builtin job polling remains available after a plugin disconnect.
    Before pairing, ``tools/list`` and ``/v1/readyz`` remain diagnostic entry
    points. No gateway is started or reconfigured by this composition root.
    """

    def __init__(self, binding, port=0, registry_dir=None):
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("port must be an integer between zero and 65535.")
        self.binding = binding
        self.tools = FigmaTools(binding)
        self.registry = ToolRegistry()
        self.config = McpHttpConfig(
            port=port,
            server_name="dcc-mcp-figma",
            server_version=__version__,
            enable_cors=False,
            request_timeout_ms=125000,
        )
        self.config.host = "127.0.0.1"
        self.config.gateway_port = 0
        self.config.dcc_type = "figma"
        self.config.instance_metadata = {
            "dcc_mcp_instance_type": "standalone",
            "adapter": "dcc-mcp-figma",
            "native_acceptance": "unverified",
            **_launch_metadata(),
        }
        if registry_dir is not None:
            self.config.registry_dir = str(registry_dir)
        self.native_server = McpHttpServer(self.registry, self.config)
        self.readiness = ReadinessProbe()
        self.readiness.set_dispatcher_ready(True)
        self.native_server.set_readiness_probe(self.readiness)
        for definition in TOOL_DEFINITIONS:
            name = definition["name"]
            self.registry.register(
                name=name,
                description=definition["description"],
                input_schema=json.dumps(definition["schema"]),
                dcc="figma",
                category="design",
                version=__version__,
                execution="async" if name in _ASYNC_TOOLS else "sync",
                timeout_hint_secs=(30 if name == "figma_nodes__export" else 120)
                if name in _ASYNC_TOOLS
                else None,
                thread_affinity="any",
            )
            self.native_server.register_handler(name, self._handler(name), thread_affinity="any")
        self._handle = None
        self._closed = False
        self.binding.set_change_callback(self._binding_changed)

    def _handler(self, name):
        def invoke(parameters):
            if isinstance(parameters, str):
                try:
                    parameters = json.loads(parameters)
                except ValueError:
                    parameters = None
            if isinstance(parameters, dict) and name in _ASYNC_TOOLS:
                metadata = parameters.get("_meta")
                if self._core_job_metadata(metadata):
                    # Core injects this correlation field after async admission. It grants no authority.
                    parameters = dict(parameters)
                    parameters.pop("_meta")
            return self.tools.invoke(name, parameters)

        return invoke

    @staticmethod
    def _core_job_metadata(metadata):
        if not isinstance(metadata, dict) or set(metadata) != {"dcc"}:
            return False
        dcc = metadata["dcc"]
        if not isinstance(dcc, dict) or set(dcc) != {"jobId"} or not isinstance(dcc["jobId"], str):
            return False
        try:
            return str(UUID(dcc["jobId"])) == dcc["jobId"]
        except ValueError:
            return False

    def _binding_changed(self, status):
        paired = isinstance(status, dict) and status.get("state") == "paired" and not self._closed
        self.readiness.set_dcc_ready(paired)
        self.readiness.set_host_execution_bridge_ready(paired)
        self.readiness.set_main_thread_executor_ready(paired)

    def start(self):
        if self._closed:
            raise RuntimeError("Create a new Figma MCP server after closing it.")
        if self._handle is None:
            self._handle = self.native_server.start()
        return self._handle

    def close(self):
        self._closed = True
        self.binding.set_change_callback(None)
        self._binding_changed({"state": "disconnected"})
        handle, self._handle = self._handle, None
        if handle is not None:
            handle.shutdown()
