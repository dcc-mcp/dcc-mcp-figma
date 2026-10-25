"""Typed adapter operations; transport and document binding live elsewhere."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
from copy import deepcopy
from xml.etree import ElementTree

from dcc_mcp_core.result_envelope import ToolResultEnvelope

from .binding import BindingError
from .blueprint import BLUEPRINT_SCHEMA, validate_blueprint
from .receipts import partial_receipt

MAX_EXPORT_BYTES = 1024 * 1024
_MAX_BASE64_CHARS = 4 * ((MAX_EXPORT_BYTES + 2) // 3)
_NODE_ID = re.compile(r"[A-Za-z0-9:;_-]{1,128}\Z")
_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\Z")
_MIME_TYPES = {"PNG": "image/png", "SVG": "image/svg+xml"}
_FRAME_FIELDS = {"name", "x", "y", "width", "height", "fill"}
_OPERATION_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_LOGICAL_KEY = re.compile(r"[A-Za-z0-9/_:.-]{1,200}\Z")
_BLUEPRINT_METHOD = "design.blueprint.apply"


def _schema(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


_CONNECTION = {"type": "string", "minLength": 1, "maxLength": 128}
_NODE = {"type": "string", "pattern": r"^[A-Za-z0-9:;_-]{1,128}$", "maxLength": 128}
_OPERATION = {"type": "string", "pattern": r"^[A-Za-z0-9_-]{1,80}$", "maxLength": 80}
_FRAME_PROPERTIES = {
    "name": {"type": "string", "minLength": 1, "maxLength": 120},
    "width": {"type": "number", "minimum": 1, "maximum": 8192},
    "height": {"type": "number", "minimum": 1, "maximum": 8192},
    "x": {"type": "number", "minimum": -1000000, "maximum": 1000000},
    "y": {"type": "number", "minimum": -1000000, "maximum": 1000000},
    "fill": {"type": "string", "pattern": r"^#[0-9A-Fa-f]{6}$"},
}


def _blueprint_schema():
    wire = deepcopy(BLUEPRINT_SCHEMA)
    definitions = wire.pop("$defs", None)
    schema = _schema(
        {"connection_id": _CONNECTION, "operation_id": _OPERATION, "blueprint": wire},
        ("connection_id", "operation_id", "blueprint"),
    )
    if definitions:
        # Fragment references resolve from the MCP input schema, not a nested property.
        schema["$defs"] = definitions
    return schema


TOOL_DEFINITIONS = (
    {
        "name": "figma_session__status",
        "description": "Read adapter binding status without invoking Figma; native acceptance remains unverified.",
        "schema": _schema({}),
        "method": None,
    },
    {
        "name": "figma_document__read",
        "description": "Read a bounded snapshot from the explicitly paired current Figma page.",
        "schema": _schema(
            {
                "connection_id": _CONNECTION,
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100},
            },
            ("connection_id",),
        ),
        "method": "document.read",
    },
    {
        "name": "figma_nodes__read",
        "description": "Read one node in the paired Figma page using an observed node ID.",
        "schema": _schema({"connection_id": _CONNECTION, "node_id": _NODE}, ("connection_id", "node_id")),
        "method": "node.read",
    },
    {
        "name": "figma_nodes__create_frame",
        "description": "Create one frame in the paired page. This changes the document; persistence needs reopen readback.",
        "schema": _schema(
            {
                "connection_id": _CONNECTION,
                **_FRAME_PROPERTIES,
                "x": {**_FRAME_PROPERTIES["x"], "default": 0},
                "y": {**_FRAME_PROPERTIES["y"], "default": 0},
                "fill": {**_FRAME_PROPERTIES["fill"], "default": "#3366FF"},
            },
            ("connection_id", "name", "width", "height"),
        ),
        "method": "frame.create",
    },
    {
        "name": "figma_nodes__update_frame",
        "description": "Modify at least one declared property of an observed frame in the paired page.",
        "schema": _schema(
            {"connection_id": _CONNECTION, "node_id": _NODE, **_FRAME_PROPERTIES},
            ("connection_id", "node_id"),
        ),
        "method": "frame.update",
    },
    {
        "name": "figma_design__apply_blueprint",
        "description": "Create a bounded editable design from typed data in the paired page. Never replay an indeterminate apply; partial receipts are observations, not rollback or persistence proof.",
        "schema": _blueprint_schema(),
        "method": _BLUEPRINT_METHOD,
    },
    {
        "name": "figma_design__read_blueprint",
        "description": "Read a bounded subtree of an observed blueprint run root and its owned local variable resources. Operation IDs are correlation, not authorization.",
        "schema": _schema(
            {
                "connection_id": _CONNECTION,
                "operation_id": _OPERATION,
                "root_node_id": _NODE,
                "limit": {"type": "integer", "minimum": 1, "maximum": 2048, "default": 2048},
            },
            ("connection_id", "operation_id", "root_node_id"),
        ),
        "method": "design.blueprint.read",
    },
    {
        "name": "figma_nodes__export",
        "description": "Export one paired-page node as PNG or SVG, at most 1 MiB; return bytes and SHA-256 without writing files.",
        "schema": _schema(
            {
                "connection_id": _CONNECTION,
                "node_id": _NODE,
                "format": {"type": "string", "enum": ["PNG", "SVG"]},
            },
            ("connection_id", "node_id", "format"),
        ),
        "method": "node.export",
    },
)
_DEFINITIONS = {definition["name"]: definition for definition in TOOL_DEFINITIONS}


def _number(value, minimum, maximum):
    return type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum


def _arguments(definition, value):
    if not isinstance(value, dict):
        raise TypeError("invalid_arguments")
    schema = definition["schema"]
    if set(value) - set(schema["properties"]) or set(schema["required"]) - set(value):
        raise ValueError("invalid_arguments")
    arguments = deepcopy(value)
    method = definition["method"]
    if method is None:
        return None, arguments
    connection = arguments.pop("connection_id")
    if not isinstance(connection, str) or not 1 <= len(connection) <= 128 or connection != connection.strip():
        raise ValueError("invalid_arguments")
    if "node_id" in arguments and (
        not isinstance(arguments["node_id"], str) or not _NODE_ID.fullmatch(arguments["node_id"])
    ):
        raise ValueError("invalid_arguments")
    if method.startswith("design.blueprint."):
        operation = arguments["operation_id"]
        if (
            not isinstance(operation, str)
            or not _OPERATION_ID.fullmatch(operation)
            or operation in {"__proto__", "constructor", "prototype"}
        ):
            raise ValueError("invalid_arguments")
        if method == _BLUEPRINT_METHOD:
            arguments["blueprint"] = validate_blueprint(arguments["blueprint"])
        else:
            root_id = arguments["root_node_id"]
            if not isinstance(root_id, str) or not _NODE_ID.fullmatch(root_id):
                raise ValueError("invalid_arguments")
            arguments.setdefault("limit", 2048)
            if type(arguments["limit"]) is not int or not 1 <= arguments["limit"] <= 2048:
                raise ValueError("invalid_arguments")
    if method == "document.read":
        arguments.setdefault("limit", 100)
        if type(arguments["limit"]) is not int or not 1 <= arguments["limit"] <= 200:
            raise ValueError("invalid_arguments")
    if method == "frame.create":
        arguments.setdefault("x", 0)
        arguments.setdefault("y", 0)
        arguments.setdefault("fill", "#3366FF")
    if method == "frame.update" and not _FRAME_FIELDS.intersection(arguments):
        raise ValueError("invalid_arguments")
    for key in _FRAME_FIELDS.intersection(arguments):
        item = arguments[key]
        if key == "name":
            valid = isinstance(item, str) and 1 <= len(item) <= 120 and bool(item.strip())
        elif key == "fill":
            valid = isinstance(item, str) and bool(_COLOR.fullmatch(item))
        elif key in {"width", "height"}:
            valid = _number(item, 1, 8192)
        else:
            valid = _number(item, -1000000, 1000000)
        if not valid:
            raise ValueError("invalid_arguments")
    if method == "node.export" and arguments["format"] not in _MIME_TYPES:
        raise ValueError("invalid_arguments")
    return connection, arguments


def _export(data, arguments):
    required = {"node_id", "format", "mime_type", "data_base64", "byte_length"}
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("invalid_response")
    if data["node_id"] != arguments["node_id"] or data["format"] != arguments["format"]:
        raise ValueError("invalid_response")
    if data["mime_type"] != _MIME_TYPES[arguments["format"]]:
        raise ValueError("invalid_response")
    length = data["byte_length"]
    encoded = data["data_base64"]
    if type(length) is not int or not 1 <= length <= MAX_EXPORT_BYTES:
        raise ValueError("invalid_response")
    if not isinstance(encoded, str) or len(encoded) > _MAX_BASE64_CHARS:
        raise ValueError("invalid_response")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("invalid_response") from None
    if len(decoded) != length or base64.b64encode(decoded).decode("ascii") != encoded:
        raise ValueError("invalid_response")
    if arguments["format"] == "PNG":
        if not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("invalid_response")
    else:
        if b"<!DOCTYPE" in decoded.upper() or b"<!ENTITY" in decoded.upper():
            raise ValueError("invalid_response")
        try:
            root = ElementTree.fromstring(decoded)
        except (ElementTree.ParseError, ValueError):
            raise ValueError("invalid_response") from None
        if root.tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
            raise ValueError("invalid_response")
    output = deepcopy(data)
    output["sha256"] = hashlib.sha256(decoded).hexdigest()
    return output


def _blueprint_result(data, arguments):
    fields = {
        "receipt",
        "nodes",
        "collections",
        "variables",
        "component_sets",
        "roots",
        "expanded_node_count",
        "run_root_id",
    }
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("invalid_response")
    receipt = partial_receipt(data["receipt"], arguments["operation_id"])
    if receipt is None or receipt["stage"] != "complete" or not receipt["mutation_attempted"]:
        raise ValueError("invalid_response")
    count = data["expanded_node_count"]
    created = set(receipt["created_node_ids"])
    if type(count) is not int or not 1 <= count <= 2048 or count != len(created):
        raise ValueError("invalid_response")
    root_id = data["run_root_id"]
    if not isinstance(root_id, str) or root_id not in created:
        raise ValueError("invalid_response")
    if data["roots"] != [root_id] or receipt["root_ids"] != [root_id]:
        raise ValueError("invalid_response")
    domains = {
        "nodes": (2048, created),
        "collections": (1, set(receipt["collection_ids"])),
        "variables": (64, set(receipt["variable_ids"])),
        "component_sets": (32, set(receipt["component_set_ids"])),
    }
    blueprint = arguments["blueprint"]
    expected_nodes = {}

    def collect(node):
        expected_nodes[node["key"]] = node
        for child in node.get("children", []):
            collect(child)

    for node in blueprint["node_trees"]:
        collect(node)
    expected_keys = {
        "nodes": set(expected_nodes),
        "collections": {blueprint["variables"]["collection"]["key"]},
        "variables": {item["key"] for item in blueprint["variables"]["items"]},
        "component_sets": {item["key"] for item in blueprint["component_sets"]},
    }
    for name, (limit, known_ids) in domains.items():
        mapping = data[name]
        if not isinstance(mapping, dict) or len(mapping) > limit or set(mapping) != expected_keys[name]:
            raise ValueError("invalid_response")
        if any(
            not isinstance(key, str)
            or not _LOGICAL_KEY.fullmatch(key)
            or key in {"__proto__", "constructor", "prototype"}
            or not isinstance(value, str)
            or not _NODE_ID.fullmatch(value)
            or value not in known_ids
            for key, value in mapping.items()
        ):
            raise ValueError("invalid_response")
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("invalid_response")
        if name != "nodes" and set(mapping.values()) != known_ids:
            raise ValueError("invalid_response")
    if not set(receipt["component_set_ids"]).issubset(created):
        raise ValueError("invalid_response")
    counts = {}

    def expanded(node):
        key = node["key"]
        if key not in counts:
            counts[key] = (
                expanded(expected_nodes[node["component_ref"]])
                if node["type"] == "INSTANCE"
                else 1 + sum(expanded(child) for child in node.get("children", []))
            )
        return counts[key]

    expected_count = (
        1 + len(blueprint["component_sets"]) + sum(expanded(node) for node in blueprint["node_trees"])
    )
    if count != expected_count:
        raise ValueError("invalid_response")
    return deepcopy(data)


def _blueprint_read_result(data, arguments):
    fields = {
        "receipt",
        "run_root_id",
        "nodes",
        "collections",
        "variables",
        "component_sets",
        "truncated",
        "expanded_node_count",
    }
    if not isinstance(data, dict) or set(data) != fields or data["run_root_id"] != arguments["root_node_id"]:
        raise ValueError("invalid_response")
    receipt = partial_receipt(data["receipt"], arguments["operation_id"])
    if receipt is None or receipt["stage"] != "read" or receipt["mutation_attempted"]:
        raise ValueError("invalid_response")
    if any(
        receipt[key]
        for key in ("created_node_ids", "collection_ids", "variable_ids", "component_set_ids", "root_ids")
    ):
        raise ValueError("invalid_response")
    nodes = data["nodes"]
    count = data["expanded_node_count"]
    if (
        not isinstance(nodes, list)
        or type(count) is not int
        or count != len(nodes)
        or not 1 <= count <= arguments["limit"]
        or type(data["truncated"]) is not bool
    ):
        raise ValueError("invalid_response")
    ids = []
    for node in nodes:
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("id"), str)
            or not _NODE_ID.fullmatch(node["id"])
        ):
            raise ValueError("invalid_response")
        ids.append(node["id"])
    if len(set(ids)) != count or ids[0] != data["run_root_id"]:
        raise ValueError("invalid_response")
    for key, limit in (("collections", 1), ("variables", 64), ("component_sets", 32)):
        if not isinstance(data[key], list) or len(data[key]) > limit:
            raise ValueError("invalid_response")
        identifiers = []
        for resource in data[key]:
            identifier = (
                resource
                if key == "component_sets"
                else resource.get("id")
                if isinstance(resource, dict)
                else None
            )
            if not isinstance(identifier, str) or not _NODE_ID.fullmatch(identifier):
                raise ValueError("invalid_response")
            identifiers.append(identifier)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("invalid_response")
    collection_ids = {item["id"] for item in data["collections"]}
    if any(item.get("collection_id") not in collection_ids for item in data["variables"]):
        raise ValueError("invalid_response")
    if len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("invalid_response")
    return deepcopy(data)


def _failure(code, dispatched=False, receipt=None):
    context = {"partial_receipt": receipt} if receipt is not None else {}
    return ToolResultEnvelope.fail(
        "The Figma operation could not complete.",
        error=code,
        dispatched=dispatched,
        outcome="indeterminate" if dispatched else "not_dispatched",
        persistence="unverified",
        native_acceptance="unverified",
        **context,
    ).to_dict()


class FigmaTools:
    """Validate one typed operation and invoke the binding exactly once."""

    def __init__(self, binding):
        self.binding = binding

    def invoke(self, name, parameters):
        definition = _DEFINITIONS.get(name)
        if definition is None:
            return _failure("invalid_arguments")
        try:
            connection, arguments = _arguments(definition, parameters)
        except (TypeError, ValueError, OverflowError, RecursionError):
            return _failure("invalid_arguments")
        if definition["method"] is None:
            try:
                status = deepcopy(self.binding.status())
                if not isinstance(status, dict) or status.get("state") not in {
                    "disconnected",
                    "paired",
                    "unavailable",
                }:
                    raise ValueError("invalid_response")
                status["persistence"] = status["native_acceptance"] = "unverified"
                return ToolResultEnvelope.ok("Observed adapter binding status.", **status).to_dict()
            except Exception:  # noqa: BLE001 - Never expose binding or pairing details across this boundary.
                return _failure("internal_error")
        try:
            result = self.binding.call(connection, definition["method"], arguments)
        except BindingError as error:
            receipt = (
                partial_receipt(error.receipt, arguments.get("operation_id"))
                if definition["method"] == _BLUEPRINT_METHOD
                else None
            )
            return _failure(error.code, error.dispatched is True, receipt)
        except Exception:  # noqa: BLE001 - An unexpected binding failure has an indeterminate native outcome.
            return _failure("internal_error", dispatched=True)
        try:
            if (
                not isinstance(result, dict)
                or result.get("ok") is not True
                or not isinstance(result.get("document"), dict)
                or not isinstance(result.get("data"), dict)
            ):
                raise ValueError("invalid_response")
            document = deepcopy(result["document"])
            data = deepcopy(result["data"])
            if definition["method"] == "node.export":
                data = _export(data, arguments)
            elif definition["method"] == _BLUEPRINT_METHOD:
                data = _blueprint_result(data, arguments)
            elif definition["method"] == "design.blueprint.read":
                data = _blueprint_read_result(data, arguments)
            json.dumps({"document": document, "data": data}, allow_nan=False)
            return ToolResultEnvelope.ok(
                "Figma response received; native persistence requires reopen readback.",
                document=document,
                data=data,
                persistence="unverified",
                native_acceptance="unverified",
                verified=False,
            ).to_dict()
        except (TypeError, ValueError, OverflowError, RecursionError):
            receipt = None
            if definition["method"] == _BLUEPRINT_METHOD and isinstance(result, dict):
                payload = result.get("data")
                if isinstance(payload, dict):
                    receipt = partial_receipt(payload.get("receipt"), arguments.get("operation_id"))
            invalidate = getattr(self.binding, "invalidate_response", None)
            if callable(invalidate):
                try:
                    invalidate(connection)
                except Exception:  # noqa: BLE001, S110 - Never log a foreign callback's private details.
                    pass
            return _failure("invalid_response", dispatched=True, receipt=receipt)
