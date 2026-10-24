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

MAX_EXPORT_BYTES = 1024 * 1024
_MAX_BASE64_CHARS = 4 * ((MAX_EXPORT_BYTES + 2) // 3)
_NODE_ID = re.compile(r"[A-Za-z0-9:;_-]{1,128}\Z")
_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\Z")
_MIME_TYPES = {"PNG": "image/png", "SVG": "image/svg+xml"}
_FRAME_FIELDS = {"name", "x", "y", "width", "height", "fill"}


def _schema(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


_CONNECTION = {"type": "string", "minLength": 1, "maxLength": 128}
_NODE = {"type": "string", "pattern": r"^[A-Za-z0-9:;_-]{1,128}$", "maxLength": 128}
_FRAME_PROPERTIES = {
    "name": {"type": "string", "minLength": 1, "maxLength": 120},
    "width": {"type": "number", "minimum": 1, "maximum": 8192},
    "height": {"type": "number", "minimum": 1, "maximum": 8192},
    "x": {"type": "number", "minimum": -1000000, "maximum": 1000000},
    "y": {"type": "number", "minimum": -1000000, "maximum": 1000000},
    "fill": {"type": "string", "pattern": r"^#[0-9A-Fa-f]{6}$"},
}
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


def _failure(code, dispatched=False):
    return ToolResultEnvelope.fail(
        "The Figma operation could not complete.",
        error=code,
        dispatched=dispatched,
        outcome="indeterminate" if dispatched else "not_dispatched",
        persistence="unverified",
        native_acceptance="unverified",
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
            return _failure(error.code, error.dispatched is True)
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
            return _failure("invalid_response", dispatched=True)
