"""Synthetic MCP peer for the blueprint trial; no Figma/GUI/native acceptance.

The production trial and client job polling run against explicitly authored
in-memory observations. These fixtures do not establish native API behavior,
font availability, image fidelity, file reopening, or persistence.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import json
import struct
import sys
import zlib
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from dcc_mcp_figma.blueprint import blueprint_digest, blueprint_stats, validate_blueprint
from dcc_mcp_figma.client import NATIVE_TOOLS, TrialError

_ROOT = Path(__file__).resolve().parents[1]
_OPERATION = "synthetic_blueprint_trial"
_WHITE = {"r": 1, "g": 1, "b": 1, "a": 1}
_BLUE = {"r": 0.1, "g": 0.2, "b": 0.3, "a": 1}


def _node(key, kind, **extra):
    return {
        "key": key,
        "type": kind,
        "name": key,
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 40},
        "visible": True,
        "opacity": 1,
        **extra,
    }


def _label(key, characters):
    return _node(
        key,
        "TEXT",
        characters=characters,
        font={"family": "Inter", "style": "Regular"},
        font_size=16,
        line_height=24,
        align="left",
        textAutoResize="NONE",
        fill=deepcopy(_WHITE),
    )


def _layout():
    return {
        "mode": "HORIZONTAL",
        "item_spacing": 0,
        "padding": [0, 0, 0, 0],
        "primary_axis_sizing": "FIXED",
        "counter_axis_sizing": "FIXED",
        "primary_axis_align": "MIN",
        "counter_axis_align": "CENTER",
    }


def _wire():
    components = []
    for state in ("default", "loading"):
        key = "button/" + state
        components.append(
            _node(
                key,
                "COMPONENT",
                children=[_label(key + "/label", "Sign in" if state == "default" else "Signing in…")],
                component_set_ref="set/button",
                variant_properties={"state": state},
                auto_layout=_layout(),
                fill=deepcopy(_BLUE),
                corner_radius=8,
                variable_bindings={"fill": "color/brand", "cornerRadius": "radius/control"},
            )
        )
    screens = []
    for viewport in ("desktop", "mobile"):
        for state in ("default", "error", "loading"):
            key = "screen/" + viewport + "/" + state
            master = "button/loading" if state == "loading" else "button/default"
            overrides = (
                [{"target_key": master + "/label", "characters": "Try again"}] if state == "error" else []
            )
            screens.append(
                _node(
                    key,
                    "FRAME",
                    children=[
                        _label(key + "/heading", "Welcome back"),
                        _node(key + "/submit", "INSTANCE", component_ref=master, overrides=overrides),
                    ],
                    bounds={
                        "x": 0,
                        "y": 0,
                        "width": 1440 if viewport == "desktop" else 390,
                        "height": 1024 if viewport == "desktop" else 844,
                    },
                    auto_layout={**_layout(), "mode": "NONE"},
                    clip_content=True,
                    fill=deepcopy(_WHITE),
                )
            )
    return validate_blueprint(
        {
            "schema_version": 1,
            "title": "Synthetic six-screen login",
            "assets": [],
            "variables": {
                "collection": {
                    "key": "tokens",
                    "name": "Synthetic tokens",
                    "mode_key": "tokens/default",
                    "mode_name": "Default",
                },
                "items": [
                    {"key": "color/brand", "name": "Brand", "type": "COLOR", "value": deepcopy(_BLUE)},
                    {"key": "radius/control", "name": "Radius", "type": "FLOAT", "value": 8},
                ],
            },
            "component_sets": [
                {
                    "key": "set/button",
                    "component_keys": ["button/default", "button/loading"],
                    "variant_properties": {"state": ["default", "loading"]},
                }
            ],
            "node_trees": components + screens,
        }
    )


def _walk(trees):
    for node in trees:
        yield node
        yield from _walk(node.get("children", []))


def _receipt(operation, stage, created=(), *, mutated=False):
    return {
        "schema_version": 1,
        "operation_id": operation,
        "stage": stage,
        "mutation_attempted": mutated,
        "completed_steps": len(created),
        "created_node_ids": list(created),
        "collection_ids": [],
        "variable_ids": [],
        "component_set_ids": [],
        "root_ids": [],
    }


def _observations(wire, operation):
    """Author explicit Figma-shaped fixture snapshots, including clone IDs."""
    cursor = 0

    def identifier():
        nonlocal cursor
        cursor += 1
        return "10:" + str(cursor)

    root_id = identifier()
    lookup = {node["key"]: node for node in _walk(wire["node_trees"])}
    mapping = {key: identifier() for key in lookup}
    set_ids = {group["key"]: identifier() for group in wire["component_sets"]}
    collection_id = "VariableCollectionId:20:0"
    variable_ids = {
        item["key"]: "VariableID:20:" + str(index + 1)
        for index, item in enumerate(wire["variables"]["items"])
    }
    variables = {item["key"]: item for item in wire["variables"]["items"]}
    records = {
        root_id: {"id": root_id, "type": "FRAME", "name": wire["title"], "parent_id": "1:0", "child_ids": []}
    }

    def paint(value, reference=None):
        if value is None:
            return []
        result = {
            "type": "SOLID",
            "color": {key: value[key] for key in ("r", "g", "b")},
            "opacity": value["a"],
        }
        if reference is not None:
            result["boundVariables"] = {"color": {"type": "VARIABLE_ALIAS", "id": variable_ids[reference]}}
        return [result]

    def materialize(spec, parent, *, clone=False, overrides=None):
        actual_id = identifier() if clone else mapping[spec["key"]]
        effective = deepcopy(spec)
        effective.update((overrides or {}).get(spec["key"], {}))
        master = lookup[spec["component_ref"]] if spec["type"] == "INSTANCE" else None
        inherited = {**(master or {}), **effective}
        bindings = {**(master or {}).get("variable_bindings", {}), **effective.get("variable_bindings", {})}
        name = effective["name"]
        if effective["type"] == "COMPONENT" and effective.get("component_set_ref"):
            name = ", ".join(
                key + "=" + value for key, value in sorted(effective["variant_properties"].items())
            )
        record = {
            "id": actual_id,
            "type": effective["type"],
            "name": name,
            "parent_id": parent,
            "x": 0,
            "y": 0,
            "width": effective["bounds"]["width"],
            "height": effective["bounds"]["height"],
            "visible": effective["visible"],
            "opacity": effective["opacity"],
            "boundVariables": {},
        }
        for field, native in (("fill", "fills"), ("stroke", "strokes")):
            reference = bindings.get(field)
            value = variables[reference]["value"] if reference else inherited.get(field)
            record[native] = paint(value, reference)
        for key, reference in bindings.items():
            if key not in {"fill", "stroke"}:
                record["boundVariables"][key] = {"type": "VARIABLE_ALIAS", "id": variable_ids[reference]}
        if "corner_radius" in inherited:
            record["cornerRadius"] = inherited["corner_radius"]
        if inherited.get("auto_layout"):
            layout = inherited["auto_layout"]
            record["layout"] = {
                "layoutMode": layout["mode"],
                "itemSpacing": layout["item_spacing"],
                "paddingTop": layout["padding"][0],
                "paddingRight": layout["padding"][1],
                "paddingBottom": layout["padding"][2],
                "paddingLeft": layout["padding"][3],
                "primaryAxisSizingMode": layout["primary_axis_sizing"],
                "counterAxisSizingMode": layout["counter_axis_sizing"],
                "primaryAxisAlignItems": layout["primary_axis_align"],
                "counterAxisAlignItems": layout["counter_axis_align"],
                "clipsContent": inherited.get("clip_content", False),
            }
        if spec["type"] == "COMPONENT":
            record["variant_properties"] = deepcopy(spec["variant_properties"])
        if spec["type"] == "TEXT":
            record.update(
                characters=effective["characters"],
                has_missing_font=False,
                typography={
                    "fontName": effective["font"],
                    "fontSize": effective["font_size"],
                    "lineHeight": {"unit": "PIXELS", "value": effective["line_height"]},
                    "textAlignHorizontal": effective["align"].upper(),
                    "textAutoResize": effective.get("textAutoResize", "NONE"),
                },
            )
        if master:
            record["main_component_id"] = mapping[spec["component_ref"]]
        records[actual_id] = record
        children = master["children"] if master else spec.get("children", [])
        child_overrides = {
            item["target_key"]: {key: value for key, value in item.items() if key != "target_key"}
            for item in spec.get("overrides", [])
        }
        child_ids = [
            materialize(child, actual_id, clone=clone or master is not None, overrides=child_overrides)
            for child in children
        ]
        if spec["type"] in {"FRAME", "COMPONENT", "INSTANCE"}:
            record["child_ids"] = child_ids
        return actual_id

    for group in wire["component_sets"]:
        group_id = set_ids[group["key"]]
        records[root_id]["child_ids"].append(group_id)
        records[group_id] = {
            "id": group_id,
            "type": "COMPONENT_SET",
            "name": group["key"],
            "parent_id": root_id,
            "child_ids": [mapping[key] for key in group["component_keys"]],
            "component_property_definitions": {
                key: {"type": "VARIANT", "variantOptions": value}
                for key, value in group["variant_properties"].items()
            },
        }
        for key in group["component_keys"]:
            materialize(lookup[key], group_id)
    for tree in wire["node_trees"]:
        if tree.get("component_set_ref") is None:
            records[root_id]["child_ids"].append(materialize(tree, root_id))
    ordered = []

    def visit(actual_id):
        ordered.append(records[actual_id])
        for child_id in records[actual_id].get("child_ids", []):
            visit(child_id)

    visit(root_id)
    created = [item["id"] for item in ordered]
    progress = _receipt(operation, "complete", created, mutated=True)
    progress.update(
        collection_ids=[collection_id],
        variable_ids=list(variable_ids.values()),
        component_set_ids=list(set_ids.values()),
        root_ids=[root_id],
    )
    applied = {
        "receipt": progress,
        "nodes": mapping,
        "collections": {wire["variables"]["collection"]["key"]: collection_id},
        "variables": variable_ids,
        "component_sets": set_ids,
        "roots": [root_id],
        "expanded_node_count": len(created),
        "run_root_id": root_id,
    }
    read = {
        "receipt": _receipt(operation, "read"),
        "run_root_id": root_id,
        "nodes": ordered,
        "collections": [
            {
                "id": collection_id,
                "name": wire["variables"]["collection"]["name"],
                "default_mode_id": "20:0",
                "modes": [{"modeId": "20:0", "name": "Default"}],
                "variable_ids": list(variable_ids.values()),
            }
        ],
        "variables": [
            {
                "id": variable_ids[item["key"]],
                "name": item["name"],
                "type": item["type"],
                "collection_id": collection_id,
                "values_by_mode": {"20:0": deepcopy(item["value"])},
            }
            for item in wire["variables"]["items"]
        ],
        "component_sets": list(set_ids.values()),
        "truncated": False,
        "expanded_node_count": len(created),
    }
    assert len(created) == blueprint_stats(wire)["expanded_nodes_with_outer_and_sets"]
    return applied, read


def _png(width, height):
    def chunk(name, payload):
        return (
            struct.pack(">I", len(payload))
            + name
            + payload
            + struct.pack(">I", zlib.crc32(name + payload) & 0xFFFFFFFF)
        )

    pixels = (b"\0" + b"\0\0\0\0" * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


class SyntheticPeer:
    """Fake MCP peer with Core-shaped jobs and explicitly synthetic document state."""

    def __init__(self, wire):
        self.wire = wire
        self.connection = "synthetic_connection_one"
        self.document = {
            "name": "Synthetic document",
            "page_id": "1:0",
            "page_name": "Fixture",
            "marker": None,
        }
        self.calls = []
        self.jobs = {}
        self.application = self.read = None
        self.sessions = 0
        self.read_fault = None
        self.apply_failure = False
        self.export_failure = False
        self.cancel_apply = False
        self.busy_page = False
        self.before_export = None

    def _job(self, result):
        identifier = "synthetic_job_" + str(len(self.jobs) + 1)
        self.jobs[identifier] = result
        return {
            "job_id": identifier,
            "core_poll": {
                "owner": "core",
                "tool": "jobs_get_status",
                "arguments": {"job_id": identifier, "include_result": True},
            },
        }

    async def call_tool(self, name, arguments):
        self.calls.append((name, deepcopy(arguments)))
        if name == "jobs_get_status":
            result = {"status": "completed", "result": deepcopy(self.jobs[arguments["job_id"]])}
        elif name == "figma_session__status":
            result = {"success": True, "context": {"state": "paired", "connection_id": self.connection}}
        elif name == "figma_document__read":
            result = {
                "success": True,
                "context": {
                    "document": deepcopy(self.document),
                    "data": {
                        "nodes": [{"id": "10:1"}] if self.application or self.busy_page else [],
                        "truncated": False,
                    },
                },
            }
        elif name == "figma_design__apply_blueprint":
            if self.cancel_apply:
                raise asyncio.CancelledError("synthetic-private-cancel-reason")
            assert arguments["blueprint"] == self.wire
            self.application, self.read = _observations(self.wire, arguments["operation_id"])
            self.document["marker"] = "synthetic_document_marker"
            if self.apply_failure:
                partial = deepcopy(self.application["receipt"])
                partial.update(
                    stage="nodes",
                    created_node_ids=["10:1"],
                    completed_steps=2,
                    collection_ids=[],
                    variable_ids=[],
                    component_set_ids=[],
                    root_ids=["10:1"],
                )
                result = self._job({"success": False, "context": {"partial_receipt": partial}})
            else:
                result = self._job(
                    {
                        "success": True,
                        "context": {"document": deepcopy(self.document), "data": deepcopy(self.application)},
                    }
                )
        elif name == "figma_design__read_blueprint":
            assert arguments["root_node_id"] == self.application["run_root_id"]
            data = deepcopy(self.read)
            data["receipt"]["operation_id"] = arguments["operation_id"]
            if self.read_fault is not None:
                self.read_fault(data)
            result = {"success": True, "context": {"document": deepcopy(self.document), "data": data}}
        elif name == "figma_nodes__export":
            if self.before_export is not None:
                self.before_export()
            screen = next(
                node
                for node in self.wire["node_trees"]
                if self.application["nodes"][node["key"]] == arguments["node_id"]
            )
            width, height = (screen["bounds"][key] for key in ("width", "height"))
            format_name = arguments["format"]
            raw = (
                _png(width, height)
                if format_name == "PNG"
                else (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"/>').encode()
            )
            data = {
                "node_id": arguments["node_id"],
                "format": format_name,
                "mime_type": "image/png" if format_name == "PNG" else "image/svg+xml",
                "data_base64": base64.b64encode(raw).decode("ascii"),
                "byte_length": len(raw),
                "sha256": "0" * 64 if self.export_failure else hashlib.sha256(raw).hexdigest(),
                "file": "../../untrusted-host-path",
            }
            result = self._job(
                {"success": True, "context": {"document": deepcopy(self.document), "data": data}}
            )
        else:
            pytest.fail("Unexpected synthetic tool call.")
        return SimpleNamespace(isError=False, structuredContent=result)

    def count(self, name):
        return sum(tool == name for tool, _arguments in self.calls)


@pytest.fixture
def trial_module():
    pytest.importorskip("mcp")
    spec = importlib.util.spec_from_file_location(
        "synthetic_blueprint_trial", _ROOT / "scripts/native_blueprint_trial.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    mcp = pytest.importorskip("mcp")
    from mcp.client import streamable_http

    wire = _wire()
    path = tmp_path / "strict-wire.json"
    path.write_text(json.dumps(wire), encoding="utf-8")
    peer = SyntheticPeer(wire)

    class Session:
        def __init__(self, *_streams):
            peer.sessions += 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_error):
            return False

        async def initialize(self):
            return None

        async def list_tools(self, cursor=None):
            assert cursor is None
            return SimpleNamespace(
                tools=[SimpleNamespace(name=name) for name in NATIVE_TOOLS | {"jobs_get_status"}],
                nextCursor=None,
            )

        async def call_tool(self, name, arguments):
            return await peer.call_tool(name, arguments)

    @asynccontextmanager
    async def transport(endpoint):
        assert endpoint == "http://127.0.0.1:19061/mcp"
        yield object(), object(), None

    monkeypatch.setattr(mcp, "ClientSession", Session)
    monkeypatch.setattr(streamable_http, "streamable_http_client", transport)
    return SimpleNamespace(wire=wire, path=path, peer=peer, root=tmp_path)


def _arguments(prepared, name="write", *, phase="write", evidence=None, operation=_OPERATION):
    return SimpleNamespace(
        mcp_url="http://127.0.0.1:19061/mcp",
        blueprint=str(prepared.path),
        output_dir=str(prepared.root / name),
        operation_id=operation,
        phase=phase,
        evidence=evidence,
    )


def test_synthetic_write_polls_core_jobs_and_exports_six_screens_exclusively(prepared, trial_module):
    result = asyncio.run(trial_module.trial(_arguments(prepared)))
    assert result["stage"] == "complete" and result["native_effects"] == "observed"
    assert result["persistence"] == result["native_acceptance"] == "unverified"
    assert result["wire_sha256"] == blueprint_digest(prepared.wire)
    assert prepared.peer.count("figma_design__apply_blueprint") == 1
    assert prepared.peer.count("figma_design__read_blueprint") == 1
    assert prepared.peer.count("figma_nodes__export") == 12
    assert prepared.peer.count("jobs_get_status") == 13
    assert len(result["artifacts"]) == 12
    output = prepared.root / "write"
    for artifact in result["artifacts"]:
        raw = (output / artifact["file"]).read_bytes()
        assert len(raw) == artifact["byte_length"]
        assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]
        assert artifact["file"].startswith(("desktop-", "mobile-"))
    assert len(list(output.iterdir())) == 13
    saved = (output / "receipt.json").read_text(encoding="utf-8")
    assert "node_trees" not in saved and "data_base64" not in saved and "untrusted-host-path" not in saved


def test_synthetic_reconnect_reads_same_ids_without_reapplying_or_exporting(prepared, trial_module):
    written = asyncio.run(trial_module.trial(_arguments(prepared)))
    prepared.peer.connection = "synthetic_connection_two"
    before = len(prepared.peer.calls)
    result = asyncio.run(
        trial_module.trial(
            _arguments(
                prepared,
                "readback",
                phase="reconnect-readback",
                evidence=str(prepared.root / "write/receipt.json"),
                operation=None,
            )
        )
    )
    assert result["reconnect_readback"] == "passed"
    assert result["application"] == written["application"]
    assert result["structure_sha256"] == written["structure_sha256"]
    assert result["persistence"] == "unverified" and result["artifacts"] == []
    assert [name for name, _arguments in prepared.peer.calls[before:]] == [
        "figma_session__status",
        "figma_document__read",
        "figma_design__read_blueprint",
    ]


@pytest.mark.parametrize("field", ["width", "characters", "alias", "main_component", "mode", "truncated"])
def test_wrong_observed_properties_stop_before_export_without_replay(prepared, trial_module, field):
    def fault(data):
        if field == "width":
            next(node for node in data["nodes"] if node.get("name") == "screen/desktop/default")["width"] = (
                1439
            )
        elif field == "characters":
            next(node for node in data["nodes"] if node.get("type") == "TEXT")["characters"] = "Wrong text"
        elif field == "alias":
            next(node for node in data["nodes"] if node.get("type") == "COMPONENT")["fills"][0][
                "boundVariables"
            ]["color"]["id"] = "VariableID:99:99"
        elif field == "main_component":
            next(node for node in data["nodes"] if node.get("type") == "INSTANCE")["main_component_id"] = (
                "99:99"
            )
        elif field == "mode":
            data["collections"][0]["modes"].append({"modeId": "20:2", "name": "Extra"})
        else:
            data["truncated"] = True

    prepared.peer.read_fault = fault
    with pytest.raises(TrialError):
        asyncio.run(trial_module.trial(_arguments(prepared)))
    saved = json.loads((prepared.root / "write/receipt.json").read_text(encoding="utf-8"))
    assert saved["stage"] == "typed_readback"
    assert saved["native_effects"] == "not_completed" and saved["native_outcome"] == "indeterminate"
    assert saved["partial_receipt"]["operation_id"] == _OPERATION
    assert prepared.peer.count("figma_design__apply_blueprint") == 1
    assert prepared.peer.count("figma_nodes__export") == 0


def test_synthetic_partial_apply_failure_retains_only_known_receipt_and_never_replays(prepared, trial_module):
    prepared.peer.apply_failure = True
    with pytest.raises(TrialError):
        asyncio.run(trial_module.trial(_arguments(prepared)))
    saved = json.loads((prepared.root / "write/receipt.json").read_text(encoding="utf-8"))
    assert saved["stage"] == "apply_blueprint" and saved["partial_receipt"]["created_node_ids"] == ["10:1"]
    assert saved["native_outcome"] == "indeterminate" and saved["persistence"] == "unverified"
    assert prepared.peer.count("figma_design__apply_blueprint") == 1
    assert (
        prepared.peer.count("figma_design__read_blueprint") == prepared.peer.count("figma_nodes__export") == 0
    )


def test_existing_output_is_untouched_and_no_session_is_started(prepared, trial_module):
    output = prepared.root / "write"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_bytes(b"Existing output remains unchanged.")
    with pytest.raises(FileExistsError):
        asyncio.run(trial_module.trial(_arguments(prepared)))
    assert sentinel.read_bytes() == b"Existing output remains unchanged."
    assert list(output.iterdir()) == [sentinel]
    assert prepared.peer.sessions == 0 and prepared.peer.calls == []


def test_export_hash_failure_stops_without_replay_or_output_artifact(prepared, trial_module):
    prepared.peer.export_failure = True
    with pytest.raises(TrialError):
        asyncio.run(trial_module.trial(_arguments(prepared)))
    saved = json.loads((prepared.root / "write/receipt.json").read_text(encoding="utf-8"))
    assert saved["stage"] == "export_desktop-default_png" and saved["artifacts"] == []
    assert prepared.peer.count("figma_nodes__export") == 1
    assert prepared.peer.count("figma_design__apply_blueprint") == 1
    assert list((prepared.root / "write").iterdir()) == [prepared.root / "write/receipt.json"]


def test_nonempty_page_stops_before_any_apply(prepared, trial_module):
    prepared.peer.busy_page = True
    with pytest.raises(TrialError):
        asyncio.run(trial_module.trial(_arguments(prepared)))
    assert prepared.peer.count("figma_design__apply_blueprint") == 0


@pytest.mark.parametrize("kind", ["same_connection", "marker", "wire_digest", "operation"])
def test_invalid_reconnect_evidence_never_replays_write(prepared, trial_module, kind):
    asyncio.run(trial_module.trial(_arguments(prepared)))
    path = prepared.root / "write/receipt.json"
    before = len(prepared.peer.calls)
    prepared.peer.connection = "synthetic_connection_two"
    operation = None
    if kind == "same_connection":
        prepared.peer.connection = "synthetic_connection_one"
    elif kind == "marker":
        prepared.peer.document["marker"] = "different_marker"
    elif kind == "wire_digest":
        previous = json.loads(path.read_text(encoding="utf-8"))
        previous["wire_sha256"] = "0" * 64
        path.write_text(json.dumps(previous), encoding="utf-8")
    else:
        operation = "different_operation"
    with pytest.raises(TrialError):
        asyncio.run(
            trial_module.trial(
                _arguments(
                    prepared, "readback", phase="reconnect-readback", evidence=str(path), operation=operation
                )
            )
        )
    assert all(
        name not in {"figma_design__apply_blueprint", "figma_nodes__export"}
        for name, _arguments in prepared.peer.calls[before:]
    )
    if kind in {"wire_digest", "operation"}:
        assert not (prepared.root / "readback").exists()


def test_offline_ir_or_duplicate_json_keys_are_not_dispatched(prepared, trial_module):
    prepared.path.write_text(json.dumps({**prepared.wire, "native_execution": "NOT_RUN"}), encoding="utf-8")
    with pytest.raises(ValueError):
        asyncio.run(trial_module.trial(_arguments(prepared)))
    assert prepared.peer.calls == [] and not (prepared.root / "write").exists()
    raw = '{"schema_version":1,"schema_version":1}'
    prepared.path.write_text(raw, encoding="utf-8")
    with pytest.raises(TrialError, match="Duplicate"):
        asyncio.run(trial_module.trial(_arguments(prepared)))
    assert prepared.path.read_text(encoding="utf-8") == raw and prepared.peer.calls == []


def test_cancellation_preserves_indeterminate_receipt_and_propagates(prepared, trial_module):
    prepared.peer.cancel_apply = True
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(trial_module.trial(_arguments(prepared)))
    saved_text = (prepared.root / "write/receipt.json").read_text(encoding="utf-8")
    saved = json.loads(saved_text)
    assert saved["native_outcome"] == "indeterminate" and saved["stage"] == "apply_blueprint"
    assert "synthetic-private-cancel-reason" not in saved_text
    assert prepared.peer.count("figma_design__apply_blueprint") == 1


def test_trial_cli_redacts_private_errors_and_returns_failure(monkeypatch, trial_module, capsys):
    async def failed(_args):
        raise TrialError("synthetic-private-error-path-and-secret")

    monkeypatch.setattr(trial_module, "trial", failed)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "native_blueprint_trial.py",
            "--mcp-url",
            "http://127.0.0.1:19061/mcp",
            "--blueprint",
            "synthetic-wire.json",
            "--output-dir",
            "synthetic-evidence",
        ],
    )
    assert trial_module.main() == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "synthetic-private" not in captured.err


@pytest.mark.parametrize("scalar", [False, True])
def test_official_expanded_corner_aliases_are_accepted_strictly(prepared, trial_module, scalar):
    def expanded(data):
        for node in data["nodes"]:
            aliases = node.get("boundVariables", {})
            if "cornerRadius" in aliases:
                value = aliases["cornerRadius"]
                for corner in ("topLeftRadius", "topRightRadius", "bottomLeftRadius", "bottomRightRadius"):
                    aliases[corner] = deepcopy(value)
                if not scalar:
                    aliases.pop("cornerRadius")

    prepared.peer.read_fault = expanded
    result = asyncio.run(trial_module.trial(_arguments(prepared)))
    assert result["stage"] == "complete" and result["native_acceptance"] == "unverified"


@pytest.mark.parametrize("kind", ["mixed", "partial", "scalar_conflict", "unexpected_unbound"])
def test_expanded_corner_aliases_reject_mixed_partial_or_unrequested_bindings(prepared, trial_module, kind):
    def wrong(data):
        if kind == "unexpected_unbound":
            aliases = next(node for node in data["nodes"] if node.get("type") == "TEXT")["boundVariables"]
            value = {"type": "VARIABLE_ALIAS", "id": "VariableID:20:2"}
        else:
            aliases = next(node for node in data["nodes"] if node.get("type") == "COMPONENT")[
                "boundVariables"
            ]
            value = aliases.pop("cornerRadius")
        for corner in ("topLeftRadius", "topRightRadius", "bottomLeftRadius", "bottomRightRadius"):
            aliases[corner] = deepcopy(value)
        if kind == "mixed":
            aliases["topRightRadius"]["id"] = "VariableID:99:99"
        elif kind == "partial":
            aliases.pop("topRightRadius")
        elif kind == "scalar_conflict":
            aliases["cornerRadius"] = {"type": "VARIABLE_ALIAS", "id": "VariableID:99:99"}

    prepared.peer.read_fault = wrong
    with pytest.raises(TrialError):
        asyncio.run(trial_module.trial(_arguments(prepared)))
    assert prepared.peer.count("figma_nodes__export") == 0
    assert prepared.peer.count("figma_design__apply_blueprint") == 1


def test_export_target_created_by_another_writer_is_never_overwritten(prepared, trial_module):
    target = prepared.root / "write/desktop-default.png"

    def occupied():
        target.write_bytes(b"Synthetic other-writer evidence.")

    prepared.peer.before_export = occupied
    with pytest.raises(FileExistsError):
        asyncio.run(trial_module.trial(_arguments(prepared)))
    assert target.read_bytes() == b"Synthetic other-writer evidence."
    saved = json.loads((prepared.root / "write/receipt.json").read_text(encoding="utf-8"))
    assert saved["artifacts"] == [] and saved["native_outcome"] == "indeterminate"
    assert prepared.peer.count("figma_nodes__export") == 1


def test_tampered_previous_artifact_is_rejected_before_session_or_output(prepared, trial_module):
    asyncio.run(trial_module.trial(_arguments(prepared)))
    path = prepared.root / "write/receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["artifacts"][0]["file"] = "../../private-file"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    before = prepared.peer.sessions
    with pytest.raises(TrialError):
        asyncio.run(
            trial_module.trial(
                _arguments(prepared, "readback", phase="reconnect-readback", evidence=str(path))
            )
        )
    assert prepared.peer.sessions == before and not (prepared.root / "readback").exists()


def test_automatic_text_axis_is_verified_without_comparing_fixed_height(prepared, trial_module):
    key = "screen/desktop/default/heading"
    spec = next(node for node in _walk(prepared.wire["node_trees"]) if node["key"] == key)
    spec["textAutoResize"] = "HEIGHT"
    prepared.path.write_text(json.dumps(prepared.wire), encoding="utf-8")

    def resized(data):
        node = next(node for node in data["nodes"] if node.get("name") == key)
        node["height"] = 80

    prepared.peer.read_fault = resized
    result = asyncio.run(trial_module.trial(_arguments(prepared)))
    assert result["stage"] == "complete"


def test_instance_explicit_paint_removes_inherited_color_alias(prepared, trial_module):
    key = "screen/desktop/default/submit"
    spec = next(node for node in _walk(prepared.wire["node_trees"]) if node["key"] == key)
    spec["fill"] = None
    prepared.path.write_text(json.dumps(prepared.wire), encoding="utf-8")

    def replaced(data):
        next(node for node in data["nodes"] if node.get("name") == key)["fills"] = []

    prepared.peer.read_fault = replaced
    result = asyncio.run(trial_module.trial(_arguments(prepared)))
    assert result["stage"] == "complete"


def test_script_keeps_python37_grammar(trial_module):
    import ast

    ast.parse(Path(trial_module.__file__).read_text(encoding="utf-8"), feature_version=(3, 7))
