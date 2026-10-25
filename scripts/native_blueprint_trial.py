"""Run an approved typed blueprint trial; never install, pair, or replay writes.

Input is strict executable wire JSON, never the offline design-source IR.
Reconnect readback cannot establish trusted same-file close/reopen or cloud-save
provenance. Native acceptance and persistence remain unverified in every receipt.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import hashlib
import json
import math
import re
import struct
import sys
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

from dcc_mcp_figma.blueprint import (
    MAX_BLUEPRINT_BYTES,
    MAX_EXPANDED_NODES,
    blueprint_digest,
    blueprint_stats,
    normalize_path,
    validate_blueprint,
)
from dcc_mcp_figma.client import TrialError, discover, invoke, local_endpoint
from dcc_mcp_figma.receipts import partial_receipt

_SCREENS = tuple(
    "screen/" + viewport + "/" + state
    for viewport in ("desktop", "mobile")
    for state in ("default", "error", "loading")
)
_ID = re.compile(r"[A-Za-z0-9:;_-]{1,128}\Z")
_OPERATION = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_MAX_EXPORT_BYTES = 1024 * 1024
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024
_RESOURCE_LISTS = ("created_node_ids", "collection_ids", "variable_ids", "component_set_ids", "root_ids")


def require(condition, message="Observed blueprint properties do not match the requested wire."):
    if not condition:
        raise TrialError(message)


def _number(actual, expected, *, absolute=1e-4):
    require(
        type(actual) in (int, float)
        and math.isfinite(actual)
        and math.isclose(actual, expected, rel_tol=1e-6, abs_tol=absolute)
    )


def _same_path(actual, expected):
    """Compare supported geometry after Figma's documented quadratic-to-cubic normalization."""

    def canonical(data):
        tokens = normalize_path(data).split()
        result, current, start = [], (0, 0), (0, 0)
        arities = {"M": 2, "L": 2, "Q": 4, "C": 6, "Z": 0}
        index = 0
        while index < len(tokens):
            command = tokens[index]
            index += 1
            size = arities[command]
            values = [float(value) for value in tokens[index : index + size]]
            index += size
            if command == "Q":
                control, end = values[:2], values[2:]
                values = (
                    [current[a] + 2 / 3 * (control[a] - current[a]) for a in (0, 1)]
                    + [end[a] + 2 / 3 * (control[a] - end[a]) for a in (0, 1)]
                    + end
                )
                command = "C"
            if command == "Z":
                current = start
            else:
                current = tuple(values[-2:])
                if command == "M":
                    start = current
            result.append((command, values))
        return result

    left, right = canonical(actual), canonical(expected)
    require(len(left) == len(right))
    for (command, values), (other, expected_values) in zip(left, right):
        require(command == other and len(values) == len(expected_values))
        for actual_value, expected_value in zip(values, expected_values):
            _number(actual_value, expected_value, absolute=0.001)


def _operation(value):
    require(
        isinstance(value, str)
        and _OPERATION.fullmatch(value)
        and value not in {"__proto__", "prototype", "constructor"},
        "Use a bounded operation correlation ID.",
    )
    return value


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "Duplicate JSON keys are not accepted.")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise TrialError("Nonfinite JSON values are not accepted.")


def _load_json(path, limit):
    with Path(path).open("rb") as source:
        raw = source.read(limit + 1)
    require(len(raw) <= limit, "The selected input exceeds the bounded trial size.")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_invalid_constant)


def _walk(trees):
    for node in trees:
        yield node
        yield from _walk(node.get("children", []))


def _document(value, *, marker=False):
    require(isinstance(value, dict) and set(value) == {"name", "page_id", "page_name", "marker"})
    require(all(isinstance(value[key], str) and len(value[key]) <= 512 for key in ("name", "page_name")))
    require(isinstance(value["page_id"], str) and _ID.fullmatch(value["page_id"]))
    require(value["marker"] is None or isinstance(value["marker"], str) and _ID.fullmatch(value["marker"]))
    require(not marker or value["marker"] is not None, "The observed write must retain its document marker.")
    return deepcopy(value)


def _same_document(actual, expected, *, allow_new_marker=False):
    _document(actual)
    require(
        all(actual[key] == expected[key] for key in ("name", "page_id", "page_name")),
        "The selected document/page changed during the trial.",
    )
    if not allow_new_marker or expected["marker"] is not None:
        require(actual["marker"] == expected["marker"], "The selected document marker changed.")


def _application(data, wire, operation):
    require(
        isinstance(data, dict)
        and set(data)
        == {
            "receipt",
            "nodes",
            "collections",
            "variables",
            "component_sets",
            "roots",
            "expanded_node_count",
            "run_root_id",
        }
    )
    observed = partial_receipt(data["receipt"], operation)
    require(observed is not None and observed["stage"] == "complete" and observed["mutation_attempted"])
    created = set(observed["created_node_ids"])
    count = blueprint_stats(wire)["expanded_nodes_with_outer_and_sets"]
    require(type(data["expanded_node_count"]) is int and data["expanded_node_count"] == count == len(created))
    root = data["run_root_id"]
    require(isinstance(root, str) and root in created and data["roots"] == observed["root_ids"] == [root])
    expected = {
        "nodes": {node["key"] for node in _walk(wire["node_trees"])},
        "collections": {wire["variables"]["collection"]["key"]},
        "variables": {item["key"] for item in wire["variables"]["items"]},
        "component_sets": {item["key"] for item in wire["component_sets"]},
    }
    domains = {
        "nodes": created,
        "collections": set(observed["collection_ids"]),
        "variables": set(observed["variable_ids"]),
        "component_sets": set(observed["component_set_ids"]),
    }
    for name, keys in expected.items():
        mapping = data[name]
        require(isinstance(mapping, dict) and set(mapping) == keys)
        require(all(isinstance(value, str) and _ID.fullmatch(value) for value in mapping.values()))
        require(len(set(mapping.values())) == len(mapping) and set(mapping.values()) <= domains[name])
        if name != "nodes":
            require(set(mapping.values()) == domains[name])
    require(set(data["component_sets"].values()) <= created and root not in data["nodes"].values())
    return deepcopy(data)


def _alias(value, identifier):
    require(
        isinstance(value, dict) and value.get("type") == "VARIABLE_ALIAS" and value.get("id") == identifier
    )


def _numeric_binding(aliases, field, identifier):
    actual = aliases.get(field)
    if field != "cornerRadius":
        if identifier is None:
            require(actual is None)
        else:
            _alias(actual, identifier)
        return
    corners = [
        aliases.get(key)
        for key in ("topLeftRadius", "topRightRadius", "bottomLeftRadius", "bottomRightRadius")
    ]
    if identifier is None:
        require(actual is None and all(value is None for value in corners))
        return
    require(actual is not None or any(value is not None for value in corners))
    if actual is not None:
        _alias(actual, identifier)
    if any(value is not None for value in corners):
        for value in corners:
            _alias(value, identifier)


def _rgba(actual, expected):
    require(isinstance(actual, dict))
    for channel in ("r", "g", "b", "a"):
        _number(actual.get(channel, 1 if channel == "a" else None), expected[channel])


def _paint(node, name, expected, variable_id=None):
    paints = node.get("fills" if name == "fill" else "strokes")
    require(isinstance(paints, list))
    if expected is None:
        require(paints == [])
        return
    require(len(paints) == 1 and paints[0].get("type") == "SOLID")
    paint = paints[0]
    require(paint.get("visible", True) is True and paint.get("blendMode", "NORMAL") == "NORMAL")
    color = dict(paint.get("color", {}), a=paint.get("opacity", 1))
    _rgba(color, expected)
    if variable_id is not None:
        _alias(paint.get("boundVariables", {}).get("color"), variable_id)
    else:
        require(paint.get("boundVariables", {}).get("color") is None)


def _fixed_axis(spec, axis):
    sizing = "layoutSizingHorizontal" if axis == "width" else "layoutSizingVertical"
    if spec.get(sizing, "FIXED") != "FIXED":
        return False
    if spec["type"] == "TEXT" and spec.get("textAutoResize", "NONE") in (
        {"WIDTH_AND_HEIGHT"} if axis == "width" else {"WIDTH_AND_HEIGHT", "HEIGHT"}
    ):
        return False
    layout = spec.get("auto_layout", {})
    if layout.get("mode") in {"HORIZONTAL", "VERTICAL"}:
        primary = (axis == "width") == (layout["mode"] == "HORIZONTAL")
        if layout["primary_axis_sizing" if primary else "counter_axis_sizing"] == "AUTO":
            return False
    return True


def _target_path(spec, target, lookup):
    children = (
        lookup[spec["component_ref"]]["children"] if spec["type"] == "INSTANCE" else spec.get("children", [])
    )
    for index, child in enumerate(children):
        if child["key"] == target:
            return (index,)
        nested = _target_path(child, target, lookup)
        if nested is not None:
            return (index,) + nested
    return None


def verify_readback(data, wire, application, operation):
    """Check typed observations, including master/clone paths and actual aliases."""
    require(isinstance(data, dict) and data.get("truncated") is False)
    read_receipt = partial_receipt(data.get("receipt"), operation)
    require(
        read_receipt is not None
        and read_receipt["stage"] == "read"
        and read_receipt["mutation_attempted"] is False
        and all(not read_receipt[key] for key in _RESOURCE_LISTS)
    )
    nodes = data.get("nodes")
    require(isinstance(nodes, list) and len(nodes) == application["expanded_node_count"])
    require(
        data.get("expanded_node_count") == len(nodes)
        and data.get("run_root_id") == application["run_root_id"]
    )
    require(all(isinstance(node, dict) and isinstance(node.get("id"), str) for node in nodes))
    observed = {node["id"]: node for node in nodes}
    require(len(observed) == len(nodes) and set(observed) == set(application["receipt"]["created_node_ids"]))
    require(nodes[0]["id"] == application["run_root_id"])
    for node in nodes:
        require(
            not any(
                node.get(flag, False)
                for flag in ("child_ids_truncated", "name_truncated", "characters_truncated")
            )
        )
        children = node.get("child_ids", [])
        require(
            isinstance(children, list)
            and len(children) == len(set(children))
            and all(
                child in observed and observed[child].get("parent_id") == node["id"] for child in children
            )
        )
    lookup = {node["key"]: node for node in _walk(wire["node_trees"])}
    variable_specs = {item["key"]: item for item in wire["variables"]["items"]}
    groups = {item["key"]: item for item in wire["component_sets"]}
    visited = {application["run_root_id"]}
    root = observed[application["run_root_id"]]
    require(root.get("type") == "FRAME" and root.get("name") == wire["title"])

    def verify(spec, identifier, parent, *, clone=False, overrides=None, parent_spec=None):
        require(identifier in observed and identifier not in visited)
        visited.add(identifier)
        node = observed[identifier]
        effective = deepcopy(spec)
        if overrides and () in overrides:
            effective.update(overrides[()])
        master = lookup[spec["component_ref"]] if spec["type"] == "INSTANCE" else None
        inherited = dict(master or {})
        inherited.update(effective)
        bindings = dict((master or {}).get("variable_bindings", {}))
        for field in ("fill", "stroke"):
            if master and field in effective:
                bindings.pop(field, None)
        bindings.update(effective.get("variable_bindings", {}))
        kind = "RECTANGLE" if spec["type"] == "IMAGE" else spec["type"]
        require(node.get("type") == kind and node.get("parent_id") == parent)
        name = effective["name"]
        if kind == "COMPONENT" and effective.get("component_set_ref"):
            name = ", ".join(
                key + "=" + effective["variant_properties"][key]
                for key in sorted(groups[effective["component_set_ref"]]["variant_properties"])
            )
        require(node.get("name") == name and node.get("visible") is effective["visible"])
        _number(node.get("opacity"), effective["opacity"])
        if parent_spec is not None and not clone:
            parent_mode = parent_spec.get("auto_layout", {}).get("mode", "NONE")
            if parent_mode == "NONE" or effective.get("layout_positioning") == "ABSOLUTE":
                for coordinate, size, constraint in (
                    ("x", "width", "horizontal"),
                    ("y", "height", "vertical"),
                ):
                    if (
                        parent_mode != "NONE"
                        and not _fixed_axis(parent_spec, size)
                        and effective.get("constraints", {}).get(constraint, "MIN") != "MIN"
                    ):
                        continue  # Native constraint projection in an auto-sized parent.
                    _number(node.get(coordinate), effective["bounds"][coordinate])
        for axis in ("width", "height"):
            if spec["type"] == "VECTOR" or _fixed_axis(inherited, axis):
                expected = (
                    variable_specs[bindings[axis]]["value"] if axis in bindings else effective["bounds"][axis]
                )
                _number(node.get(axis), expected, absolute=0.001 if spec["type"] == "VECTOR" else 1e-4)
        if kind == "INSTANCE":
            require(node.get("main_component_id") == application["nodes"][spec["component_ref"]])
        if kind == "COMPONENT":
            require(node.get("variant_properties") == spec["variant_properties"])
        if kind == "TEXT":
            require(
                node.get("characters") == effective["characters"] and node.get("has_missing_font") is False
            )
            typography = node.get("typography", {})
            require(typography.get("fontName") == effective["font"])
            _number(typography.get("fontSize"), effective["font_size"])
            require(typography.get("lineHeight", {}).get("unit") == "PIXELS")
            _number(typography["lineHeight"].get("value"), effective["line_height"])
            require(
                typography.get("textAlignHorizontal") == effective["align"].upper()
                and typography.get("textAutoResize") == effective.get("textAutoResize", "NONE")
            )
        if spec["type"] == "IMAGE":
            paints = node.get("fills", [])
            require(
                len(paints) == 1
                and paints[0].get("type") == "IMAGE"
                and paints[0].get("scaleMode") == "FIT"
                and isinstance(paints[0].get("imageHash"), str)
                and 1 <= len(paints[0]["imageHash"]) <= 128
            )
        else:
            for field in ("fill", "stroke"):
                expected = (
                    variable_specs[bindings[field]]["value"] if field in bindings else inherited.get(field)
                )
                _paint(node, field, expected, application["variables"].get(bindings.get(field)))
        for field, native_name in (("stroke_width", "strokeWeight"), ("corner_radius", "cornerRadius")):
            if native_name in bindings or field in inherited:
                expected = (
                    variable_specs[bindings[native_name]]["value"]
                    if native_name in bindings
                    else inherited[field]
                )
                _number(node.get(native_name), expected)
        for field in ("strokeWeight", "cornerRadius", "width", "height"):
            _numeric_binding(
                node.get("boundVariables", {}),
                field,
                application["variables"][bindings[field]] if field in bindings else None,
            )
        layout = node.get("layout", {})
        planned_layout = inherited.get("auto_layout")
        if planned_layout:
            require(layout.get("layoutMode") == planned_layout["mode"])
            if planned_layout["mode"] != "NONE":
                for key, value in {
                    "itemSpacing": planned_layout["item_spacing"],
                    "paddingTop": planned_layout["padding"][0],
                    "paddingRight": planned_layout["padding"][1],
                    "paddingBottom": planned_layout["padding"][2],
                    "paddingLeft": planned_layout["padding"][3],
                }.items():
                    _number(layout.get(key), value)
                for key, value in {
                    "primaryAxisSizingMode": planned_layout["primary_axis_sizing"],
                    "counterAxisSizingMode": planned_layout["counter_axis_sizing"],
                    "primaryAxisAlignItems": planned_layout["primary_axis_align"],
                    "counterAxisAlignItems": planned_layout["counter_axis_align"],
                }.items():
                    require(layout.get(key) == value)
        for key in (
            "layoutSizingHorizontal",
            "layoutSizingVertical",
            "constraints",
            "stroke_cap",
            "stroke_join",
        ):
            native_key = {"stroke_cap": "strokeCap", "stroke_join": "strokeJoin"}.get(key, key)
            if key in inherited:
                require(node.get(native_key, layout.get(native_key)) == inherited[key])
        if "layout_positioning" in inherited:
            require(node.get("layoutPositioning") == inherited["layout_positioning"])
        if "clip_content" in inherited:
            require(layout.get("clipsContent") is inherited["clip_content"])
        if kind == "VECTOR":
            paths = node.get("paths")
            require(isinstance(paths, list) and len(paths) == len(effective["paths"]))
            for actual, expected in zip(paths, effective["paths"]):
                require(actual.get("windingRule") == expected["windingRule"])
                _same_path(actual.get("data"), expected["data"])
        child_specs = master["children"] if master else spec.get("children", [])
        child_ids = node.get("child_ids", [])
        require(len(child_ids) == len(child_specs))
        child_overrides = {}
        if master:
            for item in spec["overrides"]:
                path = _target_path(master, item["target_key"], lookup)
                require(path is not None)
                child_overrides.setdefault(path, {}).update(
                    {key: value for key, value in item.items() if key != "target_key"}
                )
        for path, changes in (overrides or {}).items():
            child_overrides.setdefault(path, {}).update(changes)
        for index, (child, child_id) in enumerate(zip(child_specs, child_ids)):
            if not clone and master is None:
                require(child_id == application["nodes"][child["key"]])
            projected = {
                path[1:]: changes for path, changes in child_overrides.items() if path and path[0] == index
            }
            verify(
                child,
                child_id,
                identifier,
                clone=clone or master is not None,
                overrides=projected,
                parent_spec=inherited,
            )

    for tree in wire["node_trees"]:
        parent = application["component_sets"].get(tree.get("component_set_ref"), application["run_root_id"])
        verify(tree, application["nodes"][tree["key"]], parent)
    require(set(data.get("component_sets", [])) == set(application["component_sets"].values()))
    for key, group in groups.items():
        identifier = application["component_sets"][key]
        require(identifier not in visited)
        visited.add(identifier)
        node = observed[identifier]
        require(
            node.get("type") == "COMPONENT_SET"
            and node.get("name") == key
            and node.get("parent_id") == application["run_root_id"]
            and node.get("child_ids") == [application["nodes"][ref] for ref in group["component_keys"]]
        )
        definitions = node.get("component_property_definitions", {})
        for name, options in group["variant_properties"].items():
            matches = [value for prop, value in definitions.items() if prop.split("#", 1)[0] == name]
            require(
                len(matches) == 1
                and matches[0].get("type") == "VARIANT"
                and set(matches[0].get("variantOptions", [])) == set(options)
            )
    require(
        visited == set(observed)
        and set(root.get("child_ids", []))
        == {
            application["nodes"][tree["key"]]
            for tree in wire["node_trees"]
            if not tree.get("component_set_ref")
        }
        | set(application["component_sets"].values())
    )
    _verify_variables(data, wire, application)
    return _structure_digest(data)


def _verify_variables(data, wire, application):
    collections = data.get("collections")
    require(isinstance(collections, list) and len(collections) == 1)
    collection = collections[0]
    spec = wire["variables"]["collection"]
    collection_id = application["collections"][spec["key"]]
    require(collection.get("id") == collection_id and collection.get("name") == spec["name"])
    modes = collection.get("modes")
    require(
        isinstance(modes, list)
        and len(modes) == 1
        and modes[0].get("name") == "Default"
        and modes[0].get("modeId") == collection.get("default_mode_id")
    )
    mode_id = collection["default_mode_id"]
    require(isinstance(mode_id, str) and _ID.fullmatch(mode_id))
    require(set(collection.get("variable_ids", [])) == set(application["variables"].values()))
    variables = data.get("variables")
    require(isinstance(variables, list) and len(variables) == len(wire["variables"]["items"]))
    lookup = {item["id"]: item for item in variables}
    require(len(lookup) == len(variables) and set(lookup) == set(application["variables"].values()))
    for variable in wire["variables"]["items"]:
        observed = lookup[application["variables"][variable["key"]]]
        require(
            observed.get("name") == variable["name"]
            and observed.get("type") == variable["type"]
            and observed.get("collection_id") == collection_id
        )
        values = observed.get("values_by_mode", {})
        require(set(values) == {mode_id})
        if variable["type"] == "COLOR":
            _rgba(values[mode_id], variable["value"])
        else:
            _number(values[mode_id], variable["value"])


def _structure_digest(data):
    value = {key: deepcopy(value) for key, value in data.items() if key != "receipt"}
    for key in ("nodes", "collections", "variables"):
        value[key].sort(key=lambda item: item["id"])
    value["component_sets"].sort()
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
            "utf-8"
        )
    ).hexdigest()


def _export_bytes(data, identifier, format_name):
    require(
        isinstance(data, dict) and data.get("node_id") == identifier and data.get("format") == format_name
    )
    mime = "image/png" if format_name == "PNG" else "image/svg+xml"
    require(
        data.get("mime_type") == mime
        and type(data.get("byte_length")) is int
        and 0 < data["byte_length"] <= _MAX_EXPORT_BYTES
    )
    encoded = data.get("data_base64")
    require(isinstance(encoded, str) and len(encoded) <= 4 * ((_MAX_EXPORT_BYTES + 2) // 3))
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise TrialError("The export encoding is invalid.") from None
    require(base64.b64encode(raw).decode("ascii") == encoded and len(raw) == data["byte_length"])
    digest = hashlib.sha256(raw).hexdigest()
    require(data.get("sha256") == digest, "Export bytes did not match the observed SHA-256.")
    dimensions = None
    if format_name == "PNG":
        require(len(raw) >= 24 and raw.startswith(b"\x89PNG\r\n\x1a\n") and raw[12:16] == b"IHDR")
        dimensions = list(struct.unpack(">II", raw[16:24]))
        require(all(dimension > 0 for dimension in dimensions))
    else:
        require(b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper())
        root = ElementTree.fromstring(raw)
        require(root.tag in {"svg", "{http://www.w3.org/2000/svg}svg"})
    return raw, digest, mime, dimensions


def _known_failure_receipt(error, operation):
    pending, seen = [error], set()
    while pending and len(seen) < 64:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, TrialError):
            observed = partial_receipt(getattr(current, "receipt", None), operation)
            if observed is not None:
                return observed
        children = getattr(current, "exceptions", ())
        if isinstance(children, (list, tuple)):
            pending.extend(children)
    return None


def _previous_artifacts(artifacts, screens, application):
    require(isinstance(artifacts, list) and len(artifacts) == 12)
    expected = {}
    for key in _SCREENS:
        label = key[len("screen/") :].replace("/", "-")
        for format_name in ("PNG", "SVG"):
            expected[label + "." + format_name.lower()] = (key, format_name)
    seen = set()
    for artifact in artifacts:
        require(
            isinstance(artifact, dict)
            and set(artifact)
            == {"file", "node_id", "format", "mime_type", "byte_length", "sha256", "png_dimensions"}
        )
        filename = artifact["file"]
        require(isinstance(filename, str) and filename in expected and filename not in seen)
        seen.add(filename)
        key, format_name = expected[filename]
        require(
            artifact["node_id"] == application["nodes"][key]
            and artifact["format"] == format_name
            and artifact["mime_type"] == ("image/png" if format_name == "PNG" else "image/svg+xml")
            and type(artifact["byte_length"]) is int
            and 0 < artifact["byte_length"] <= _MAX_EXPORT_BYTES
            and isinstance(artifact["sha256"], str)
            and _DIGEST.fullmatch(artifact["sha256"])
        )
        dimensions = artifact["png_dimensions"]
        if format_name == "PNG":
            require(
                isinstance(dimensions, list)
                and len(dimensions) == 2
                and all(type(value) is int and value > 0 for value in dimensions)
            )
            if screens[key].get("clip_content") is True:
                require(
                    dimensions == [math.ceil(screens[key]["bounds"][axis]) for axis in ("width", "height")]
                )
        else:
            require(dimensions is None)


async def trial(args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    endpoint = local_endpoint(args.mcp_url)
    wire = validate_blueprint(_load_json(args.blueprint, MAX_BLUEPRINT_BYTES))
    digest = blueprint_digest(wire)
    screens = {node["key"]: node for node in wire["node_trees"] if node["type"] == "FRAME"}
    require(set(screens) == set(_SCREENS), "Supply exactly the six desktop/mobile state screen roots.")
    previous = None
    if args.phase in ("reconnect-readback", "reconnect-export"):
        require(args.evidence is not None, "Readback requires the completed write receipt.")
        previous = _load_json(args.evidence, _MAX_RECEIPT_BYTES)
        require(
            isinstance(previous, dict)
            and previous.get("phase") == "write"
            and previous.get("stage") == "complete"
            and previous.get("native_effects") == "observed"
            and previous.get("persistence") == "unverified"
            and previous.get("native_acceptance") == "unverified"
            and type(previous.get("schema_version")) is int
            and previous["schema_version"] == 1
            and previous.get("wire_sha256") == digest
        )
        operation = _operation(previous.get("operation_id"))
        require(
            args.operation_id is None or _operation(args.operation_id) == operation,
            "Readback must correlate to the previous blueprint run.",
        )
        application = _application(previous.get("application"), wire, operation)
        _document(previous.get("document"), marker=True)
        require(
            isinstance(previous.get("connection_id"), str)
            and previous["connection_id"]
            and isinstance(previous.get("structure_sha256"), str)
            and _DIGEST.fullmatch(previous["structure_sha256"])
        )
        _previous_artifacts(previous.get("artifacts"), screens, application)
    else:
        require(args.phase == "write", "Use write, reconnect-readback or reconnect-export phase.")
        operation = _operation(args.operation_id if args.operation_id is not None else uuid4().hex)
        application = None
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema_version": 1,
        "phase": args.phase,
        "operation_id": operation,
        "wire_sha256": digest,
        "native_effects": "not_completed",
        "native_acceptance": "unverified",
        "persistence": "unverified",
        "stage": "connect",
        "artifacts": [],
    }
    try:
        async with streamable_http_client(endpoint) as (read, write, _):  # noqa: SIM117 - Python 3.7 source.
            async with ClientSession(read, write) as session:
                await session.initialize()
                catalogue = await discover(session)
                receipt["stage"] = "read_status"
                status = await invoke(session, catalogue, "figma_session__status", {}, timeout=125)
                require(
                    status.get("state") == "paired",
                    "Pair the already approved plugin in the selected file first.",
                )
                connection = status.get("connection_id")
                require(isinstance(connection, str) and 1 <= len(connection) <= 128)
                receipt["connection_id"] = connection
                receipt["stage"] = "read_page"
                page = await invoke(
                    session, catalogue, "figma_document__read", {"connection_id": connection}, timeout=125
                )
                document = _document(page.get("document"))
                receipt["document"] = document
                if previous is None:
                    require(
                        page.get("data", {}).get("truncated") is False and page["data"].get("nodes") == [],
                        "Select an empty disposable page before the explicit write phase.",
                    )
                    receipt["stage"] = "apply_blueprint"
                    applied = await invoke(
                        session,
                        catalogue,
                        "figma_design__apply_blueprint",
                        {"connection_id": connection, "operation_id": operation, "blueprint": wire},
                        timeout=125,
                    )
                    # Retain bounded observed IDs before later semantic checks can fail.
                    observed_partial = partial_receipt(applied.get("data", {}).get("receipt"), operation)
                    if observed_partial is not None:
                        receipt["partial_receipt"] = observed_partial
                    receipt["stage"] = "verify_application"
                    _same_document(applied.get("document"), document, allow_new_marker=True)
                    document = _document(applied["document"], marker=True)
                    receipt["document"] = document
                    application = _application(applied.get("data"), wire, operation)
                else:
                    require(
                        connection != previous["connection_id"], "Readback requires a new plugin connection."
                    )
                    _same_document(document, previous["document"])
                receipt["application"] = application
                receipt["stage"] = "typed_readback"
                observed = await invoke(
                    session,
                    catalogue,
                    "figma_design__read_blueprint",
                    {
                        "connection_id": connection,
                        "operation_id": operation,
                        "root_node_id": application["run_root_id"],
                        "limit": MAX_EXPANDED_NODES,
                    },
                    timeout=125,
                )
                _same_document(observed.get("document"), document)
                receipt["structure_sha256"] = verify_readback(
                    observed.get("data"), wire, application, operation
                )
                if previous is not None:
                    require(
                        receipt["structure_sha256"] == previous["structure_sha256"],
                        "The same native IDs did not retain their observed typed structure.",
                    )
                    receipt["reconnect_readback"] = "passed"
                if previous is None or args.phase == "reconnect-export":
                    receipt["export_observation"] = (
                        "write_phase" if previous is None else "after_reconnect_readback"
                    )
                    for screen_key in _SCREENS:
                        identifier = application["nodes"][screen_key]
                        for format_name in ("PNG", "SVG"):
                            label = screen_key[len("screen/") :].replace("/", "-")
                            filename = label + "." + format_name.lower()
                            receipt["stage"] = "export_" + label + "_" + format_name.lower()
                            exported = await invoke(
                                session,
                                catalogue,
                                "figma_nodes__export",
                                {"connection_id": connection, "node_id": identifier, "format": format_name},
                                timeout=125,
                            )
                            _same_document(exported.get("document"), document)
                            raw, export_digest, mime, dimensions = _export_bytes(
                                exported.get("data"), identifier, format_name
                            )
                            if dimensions is not None and screens[screen_key].get("clip_content") is True:
                                require(
                                    dimensions
                                    == [
                                        math.ceil(screens[screen_key]["bounds"][axis])
                                        for axis in ("width", "height")
                                    ]
                                )
                            with (output / filename).open("xb") as target:
                                target.write(raw)
                            receipt["artifacts"].append(
                                {
                                    "file": filename,
                                    "node_id": identifier,
                                    "format": format_name,
                                    "mime_type": mime,
                                    "byte_length": len(raw),
                                    "sha256": export_digest,
                                    "png_dimensions": dimensions,
                                }
                            )
                receipt["stage"] = "complete"
                receipt["native_effects"] = "observed"
                receipt["persistence_note"] = (
                    "Typed observations and exports do not prove trusted same-file close/reopen or cloud save. "
                    "Retain independent authorized host evidence; reconnect alone leaves persistence unverified."
                )
    except BaseException as error:  # Save evidence, then preserve cancellation/interrupt semantics.
        receipt["native_outcome"] = "indeterminate"
        observed_partial = _known_failure_receipt(error, operation)
        if observed_partial is not None:
            receipt["partial_receipt"] = observed_partial
        raise
    finally:
        with (output / "receipt.json").open("x", encoding="utf-8") as target:
            json.dump(receipt, target, ensure_ascii=False, indent=2, allow_nan=False)
            target.write("\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcp-url", required=True)
    parser.add_argument(
        "--blueprint", required=True, help="Strict wire JSON; offline source IR is not accepted."
    )
    parser.add_argument("--output-dir", required=True, help="A new private evidence directory.")
    parser.add_argument("--operation-id", help="Optional correlation ID, not a credential or authority.")
    parser.add_argument(
        "--phase", choices=("write", "reconnect-readback", "reconnect-export"), default="write"
    )
    parser.add_argument("--evidence", help="Completed write receipt for either reconnect phase.")
    args = parser.parse_args()
    try:
        result = asyncio.run(trial(args))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print(
            "Blueprint trial interrupted. Inspect private evidence; never replay an uncertain apply.",
            file=sys.stderr,
        )
        return 130
    except Exception:  # noqa: BLE001 - do not print private SDK, document, asset, or path errors.
        print(
            "Blueprint trial stopped. Inspect private evidence; never replay an uncertain apply.",
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {key: result[key] for key in ("phase", "native_effects", "native_acceptance", "persistence")}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
