"""Strict, data-only blueprint compiler and validation before plugin dispatch.

Offline provenance/permission flags are never copied into the executable wire.
Text styles are explicitly projected to inline typography in this first wire
version; this module does not claim creation of native TextStyle resources.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
import struct
from copy import deepcopy
from xml.etree import ElementTree

from .blueprint_schema import BLUEPRINT_SCHEMA

__all__ = [
    "BLUEPRINT_SCHEMA",
    "BlueprintError",
    "blueprint_digest",
    "blueprint_stats",
    "compilation_report",
    "compile_blueprint",
    "normalize_path",
    "validate_blueprint",
]

MAX_BLUEPRINT_BYTES = 2 * 1024 * 1024
MAX_EXPANDED_NODES = 2048
MAX_DEPTH = 24
MAX_ASSETS = 16
MAX_VARIABLES = 64
MAX_FONTS = 16
MAX_DECODED_IMAGE_BYTES = 1024 * 1024
MAX_VECTOR_DATA_BYTES = 256 * 1024
NODE_TYPES = ("FRAME", "COMPONENT", "TEXT", "INSTANCE", "VECTOR", "IMAGE", "RECTANGLE", "ELLIPSE")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:\-]{0,199}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_PATH_TOKEN = re.compile(r"[MLHVCSQTAZmlhvcsqtaz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_COMMON = {
    "key",
    "type",
    "name",
    "bounds",
    "visible",
    "opacity",
    "fill",
    "stroke",
    "stroke_width",
    "variable_bindings",
    "layoutSizingHorizontal",
    "layoutSizingVertical",
    "layout_positioning",
    "constraints",
    "clip_content",
}
_TYPE_FIELDS = {
    "FRAME": {"children", "auto_layout", "corner_radius"},
    "COMPONENT": {"children", "auto_layout", "corner_radius", "component_set_ref", "variant_properties"},
    "TEXT": {"characters", "font", "font_size", "line_height", "align", "textAutoResize"},
    "INSTANCE": {"component_ref", "overrides"},
    "VECTOR": {"paths", "stroke_cap", "stroke_join"},
    "RECTANGLE": {"corner_radius"},
    "ELLIPSE": set(),
    "IMAGE": {"asset_ref", "image_fit"},
}
_REQUIRED_COMMON = {"key", "type", "name", "bounds", "visible", "opacity"}
_LAYOUT_FIELDS = {
    "mode",
    "item_spacing",
    "padding",
    "primary_axis_sizing",
    "counter_axis_sizing",
    "primary_axis_align",
    "counter_axis_align",
}
_BINDINGS = {"fill", "stroke", "strokeWeight", "cornerRadius", "width", "height"}
_SOURCE_TOP = {
    "schema_version",
    "title",
    "native_execution",
    "figma_ids_present",
    "identifier_kind",
    "execution_status",
    "current_adapter_missing_operations",
    "security",
    "layout_execution_constraints",
    "asset_policy",
    "native_acceptance",
    "complexity_estimate",
    "variables",
    "text_styles",
    "assets",
    "component_sets",
    "node_trees",
}


class BlueprintError(ValueError):
    """Fixed public diagnostics without source text, paths, images, or secrets."""

    def __init__(self, code="invalid_blueprint"):
        self.code = (
            code
            if code
            in {
                "invalid_blueprint",
                "blueprint_too_large",
                "node_budget_exceeded",
                "depth_exceeded",
                "unsupported_feature",
                "invalid_asset",
                "invalid_vector",
            }
            else "invalid_blueprint"
        )
        super().__init__(self.code)


def _require(condition, code="invalid_blueprint"):
    if not condition:
        raise BlueprintError(code)


def _exact(value, required, optional=()):
    _require(
        isinstance(value, dict)
        and set(required) <= set(value)
        and set(value) <= set(required) | set(optional)
    )


def _number(value, low=-1000000, high=1000000):
    _require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high)
    return value


def _text(value, limit=120, empty=False):
    _require(isinstance(value, str) and (empty or bool(value)) and len(value) <= limit)
    _require(not any(ord(c) < 32 and c not in "\n\t" for c in value))
    return value


def _key(value):
    _require(isinstance(value, str) and _KEY.fullmatch(value) is not None)
    _require("://" not in value)
    _require(value not in {"__proto__", "constructor", "prototype"})
    _require(not any(part in {".", ".."} for part in value.split("/")))
    return value


def _rgba(value):
    _exact(value, {"r", "g", "b", "a"})
    for channel in value.values():
        _number(channel, 0, 1)
    return value


def _dump(value):
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise BlueprintError() from None


def blueprint_digest(value):
    """Hash canonical UTF-8 wire data; the digest is correlation, not authority."""
    return hashlib.sha256(_dump(validate_blueprint(value))).hexdigest()


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node.get("children", []))


def _png_asset(asset):
    _exact(asset, {"key", "mime_type", "data_base64", "sha256", "width", "height"})
    _key(asset["key"])
    _require(asset["mime_type"] == "image/png" and isinstance(asset["data_base64"], str), "invalid_asset")
    _require(
        isinstance(asset["sha256"], str) and _HEX.fullmatch(asset["sha256"]) is not None, "invalid_asset"
    )
    try:
        raw = base64.b64decode(asset["data_base64"], validate=True)
    except (ValueError, binascii.Error):
        raise BlueprintError("invalid_asset") from None
    _require(base64.b64encode(raw).decode("ascii") == asset["data_base64"], "invalid_asset")
    _require(
        len(raw) >= 33
        and raw[:8] == b"\x89PNG\r\n\x1a\n"
        and raw[8:12] == b"\0\0\0\r"
        and raw[12:16] == b"IHDR",
        "invalid_asset",
    )
    width, height = struct.unpack(">II", raw[16:24])
    _require(
        type(asset["width"]) is int
        and type(asset["height"]) is int
        and width == asset["width"]
        and height == asset["height"]
        and 1 <= width <= 4096
        and 1 <= height <= 4096,
        "invalid_asset",
    )
    _require(hashlib.sha256(raw).hexdigest() == asset["sha256"], "invalid_asset")
    return len(raw)


def _path_segments(data, *, normalized_only=False):
    _require(isinstance(data, str) and 0 < len(data) <= 128 * 1024, "invalid_vector")
    tokens = _PATH_TOKEN.findall(data)
    residue = _PATH_TOKEN.sub("", data).replace(",", "").strip()
    _require(not residue and tokens, "invalid_vector")
    if normalized_only:
        _require(all(not token.isalpha() or token in "MLQCZ" for token in tokens), "invalid_vector")
    return tokens


def _validate_blueprint(value):
    """Validate and copy the complete executable wire without performing I/O."""
    _require(len(_dump(value)) <= MAX_BLUEPRINT_BYTES, "blueprint_too_large")
    _exact(value, {"schema_version", "title", "assets", "variables", "component_sets", "node_trees"})
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    _text(value["title"])
    all_keys = set()

    def reserve(key):
        _key(key)
        _require(key not in all_keys)
        all_keys.add(key)

    assets = value["assets"]
    _require(isinstance(assets, list) and len(assets) <= MAX_ASSETS)
    asset_keys = set()
    image_bytes = 0
    for asset in assets:
        image_bytes += _png_asset(asset)
        reserve(asset["key"])
        _require(asset["key"] not in asset_keys)
        asset_keys.add(asset["key"])
    _require(image_bytes <= MAX_DECODED_IMAGE_BYTES, "blueprint_too_large")
    variables = value["variables"]
    _exact(variables, {"collection", "items"})
    collection = variables["collection"]
    _exact(collection, {"key", "name", "mode_key", "mode_name"})
    reserve(collection["key"])
    reserve(collection["mode_key"])
    _text(collection["name"])
    _require(collection["mode_name"] == "Default")
    _require(isinstance(variables["items"], list) and len(variables["items"]) <= MAX_VARIABLES)
    variable_types = {}
    variable_values = {}
    for variable in variables["items"]:
        _exact(variable, {"key", "name", "type", "value"})
        reserve(variable["key"])
        _text(variable["name"])
        _require(variable["key"] not in variable_types and variable["type"] in {"COLOR", "FLOAT"})
        variable_types[variable["key"]] = variable["type"]
        variable_values[variable["key"]] = variable["value"]
        _rgba(variable["value"]) if variable["type"] == "COLOR" else _number(variable["value"])
    trees = value["node_trees"]
    _require(isinstance(trees, list) and 1 <= len(trees) <= MAX_EXPANDED_NODES)
    nodes = {}
    fonts = set()
    path_bytes = 0

    def check_node(n, depth, parent=None):
        nonlocal path_bytes
        _require(depth <= MAX_DEPTH, "depth_exceeded")
        _require(isinstance(n, dict) and n.get("type") in NODE_TYPES)
        _exact(n, _REQUIRED_COMMON, (_COMMON | _TYPE_FIELDS[n["type"]]) - _REQUIRED_COMMON)
        reserve(n["key"])
        _require(n["key"] not in nodes)
        nodes[n["key"]] = n
        _text(n["name"])
        _require(type(n["visible"]) is bool)
        _number(n["opacity"], 0, 1)
        b = n["bounds"]
        _exact(b, {"x", "y", "width", "height"})
        _number(b["x"])
        _number(b["y"])
        for axis in ("width", "height"):
            _number(b[axis], 0 if n["type"] == "VECTOR" else 0.01, 8192)
        for paint in ("fill", "stroke"):
            if n.get(paint) is not None:
                _rgba(n[paint])
        if "stroke_width" in n:
            _number(n["stroke_width"], 0, 128)
        if "corner_radius" in n:
            _number(n["corner_radius"], 0, 4096)
        for sizing in ("layoutSizingHorizontal", "layoutSizingVertical"):
            if sizing in n:
                _require(n[sizing] in {"FIXED", "FILL", "HUG"})
                if n[sizing] == "FILL":
                    _require(n["type"] != "VECTOR")
                    _require(
                        parent is not None
                        and isinstance(parent.get("auto_layout"), dict)
                        and parent["auto_layout"]["mode"] in {"HORIZONTAL", "VERTICAL"}
                    )
        if "layout_positioning" in n:
            _require(n["layout_positioning"] in {"AUTO", "ABSOLUTE"})
        if "clip_content" in n:
            _require(type(n["clip_content"]) is bool)
        if "constraints" in n:
            _exact(n["constraints"], {"horizontal", "vertical"})
            _require(
                all(v in {"MIN", "CENTER", "MAX", "STRETCH", "SCALE"} for v in n["constraints"].values())
            )
        if "auto_layout" in n:
            a = n["auto_layout"]
            _exact(a, _LAYOUT_FIELDS)
            _require(a["mode"] in {"NONE", "HORIZONTAL", "VERTICAL"})
            _number(a["item_spacing"], 0, 8192)
            _require(isinstance(a["padding"], list) and len(a["padding"]) == 4)
            for v in a["padding"]:
                _number(v, 0, 8192)
            _require(
                a["primary_axis_sizing"] in {"FIXED", "AUTO"}
                and a["counter_axis_sizing"] in {"FIXED", "AUTO"}
            )
            _require(
                a["primary_axis_align"] in {"MIN", "CENTER", "MAX", "SPACE_BETWEEN"}
                and a["counter_axis_align"] in {"MIN", "CENTER", "MAX", "BASELINE"}
                and (a["counter_axis_align"] != "BASELINE" or a["mode"] == "HORIZONTAL")
            )
        bindings = n.get("variable_bindings", {})
        _require(isinstance(bindings, dict) and set(bindings) <= _BINDINGS)
        for prop, ref in bindings.items():
            _require(
                ref in variable_types
                and variable_types[ref] == ("COLOR" if prop in {"fill", "stroke"} else "FLOAT")
            )
            if prop in {"fill", "stroke"}:
                _require(n.get(prop) is not None)
            if prop in {"width", "height"}:
                _number(variable_values[ref], 0.01, 8192)
                _require(n["type"] != "VECTOR" or b[prop] != 0)
                _require(n["type"] != "VECTOR" or abs(variable_values[ref] - b[prop]) <= 0.001)
            elif prop == "strokeWeight":
                _number(variable_values[ref], 0, 128)
            elif prop == "cornerRadius":
                _require(n["type"] in {"FRAME", "COMPONENT", "INSTANCE", "RECTANGLE"})
                _number(variable_values[ref], 0, 4096)
        if n["type"] in {"FRAME", "COMPONENT"}:
            _require(isinstance(n.get("children"), list))
            for child in n["children"]:
                check_node(child, depth + 1, n)
        if n["type"] == "COMPONENT":
            _require(n.get("component_set_ref") is None or isinstance(n["component_set_ref"], str))
            _require(isinstance(n.get("variant_properties"), dict))
            for k, v in n["variant_properties"].items():
                _text(k, 40)
                _text(v, 80)
        if n["type"] == "TEXT":
            _require({"characters", "font", "font_size", "line_height", "align"} <= set(n))
            _text(n["characters"], 8192, empty=True)
            _exact(n["font"], {"family", "style"})
            _text(n["font"]["family"], 100)
            _text(n["font"]["style"], 100)
            fonts.add((n["font"]["family"], n["font"]["style"]))
            _number(n["font_size"], 1, 512)
            _number(n["line_height"], 1, 1024)
            _require(n["align"] in {"left", "center", "right"})
            if "textAutoResize" in n:
                _require(n["textAutoResize"] in {"NONE", "HEIGHT", "WIDTH_AND_HEIGHT"})
        if n["type"] == "INSTANCE":
            _key(n.get("component_ref"))
            _require(isinstance(n.get("overrides"), list) and len(n["overrides"]) <= 64)
            for override in n["overrides"]:
                _exact(override, {"target_key"}, {"characters", "visible"})
                _key(override["target_key"])
                _require(len(override) > 1)
                if "characters" in override:
                    _text(override["characters"], 8192, empty=True)
                if "visible" in override:
                    _require(type(override["visible"]) is bool)
        if n["type"] == "VECTOR":
            if "stroke_cap" in n:
                _require(n["stroke_cap"] in {"NONE", "ROUND", "SQUARE"})
            if "stroke_join" in n:
                _require(n["stroke_join"] in {"MITER", "ROUND", "BEVEL"})
            _require(isinstance(n.get("paths"), list) and 1 <= len(n["paths"]) <= 128)
            path_bounds = []
            for p in n["paths"]:
                _exact(p, {"windingRule", "data"})
                _require(p["windingRule"] in {"NONZERO", "EVENODD"})
                _path_segments(p["data"], normalized_only=True)
                _require(normalize_path(p["data"]) == p["data"], "invalid_vector")
                path_bounds.append(_bounds(_segments(p["data"])))
                path_bytes += len(p["data"].encode("utf-8"))
            left, top = min(p[0] for p in path_bounds), min(p[1] for p in path_bounds)
            right, bottom = max(p[2] for p in path_bounds), max(p[3] for p in path_bounds)
            _require(
                all(
                    abs(actual - expected) <= 0.001
                    for actual, expected in zip(
                        (left, top, right - left, bottom - top), (0, 0, b["width"], b["height"])
                    )
                ),
                "invalid_vector",
            )
        if n["type"] == "IMAGE":
            _require(n.get("asset_ref") in asset_keys and n.get("image_fit") == "CONTAIN")

    for tree in trees:
        check_node(tree, 1)
    _require(len(fonts) <= MAX_FONTS and path_bytes <= MAX_VECTOR_DATA_BYTES, "blueprint_too_large")
    sets = value["component_sets"]
    _require(isinstance(sets, list) and len(sets) <= 32)
    sets_by_key = {}
    members = []
    for group in sets:
        _exact(group, {"key", "component_keys", "variant_properties"})
        reserve(group["key"])
        _require(group["key"] not in sets_by_key)
        sets_by_key[group["key"]] = group
        _require(isinstance(group["component_keys"], list) and len(group["component_keys"]) >= 2)
        _require(isinstance(group["variant_properties"], dict) and len(group["variant_properties"]) <= 8)
        for prop, options in group["variant_properties"].items():
            _text(prop, 40)
            _require(
                isinstance(options, list) and 1 <= len(options) <= 64 and len(options) == len(set(options))
            )
            for option in options:
                _text(option, 80)
        combinations = []
        for ref in group["component_keys"]:
            _require(
                ref in nodes
                and nodes[ref]["type"] == "COMPONENT"
                and nodes[ref].get("component_set_ref") == group["key"]
            )
            props = nodes[ref]["variant_properties"]
            _require(
                set(props) == set(group["variant_properties"])
                and all(v in group["variant_properties"][k] for k, v in props.items())
            )
            combinations.append(tuple(sorted(props.items())))
            members.append(ref)
        _require(len(combinations) == len(set(combinations)))
    _require(len(members) == len(set(members)))
    _require(
        set(members)
        == {
            n["key"]
            for n in nodes.values()
            if n["type"] == "COMPONENT" and n.get("component_set_ref") is not None
        }
    )

    def count(n, stack, depth):
        _require(depth <= MAX_DEPTH, "depth_exceeded")
        if n["type"] == "INSTANCE":
            ref = n["component_ref"]
            _require(ref in nodes and nodes[ref]["type"] == "COMPONENT" and ref not in stack)
            target = nodes[ref]
            descendants = {v["key"]: v for v in _walk(target["children"])}
            for override in n["overrides"]:
                _require(override["target_key"] in descendants)
                if "characters" in override:
                    _require(descendants[override["target_key"]]["type"] == "TEXT")
            descendants_to_count = target["children"]
            stack = stack + [ref]
        else:
            descendants_to_count = n.get("children", [])
        result = 1
        for child in descendants_to_count:
            result += count(child, stack, depth + 1)
            _require(result <= MAX_EXPANDED_NODES, "node_budget_exceeded")
        return result

    total = 1 + len(sets)
    for tree in trees:
        total += count(
            tree,
            [tree["key"]] if tree["type"] == "COMPONENT" else [],
            3 if tree["type"] == "COMPONENT" and tree.get("component_set_ref") else 2,
        )
        _require(total <= MAX_EXPANDED_NODES, "node_budget_exceeded")
    _require(total <= MAX_EXPANDED_NODES, "node_budget_exceeded")
    return deepcopy(value)


def _fmt(value):
    _number(value)
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _arc(start, values):
    rx, ry, rotation, large, sweep, x2, y2 = values
    x1, y1 = start
    _require(large in (0, 1) and sweep in (0, 1), "invalid_vector")
    rx, ry = abs(rx), abs(ry)
    if (x1, y1) == (x2, y2):
        return []
    if rx == 0 or ry == 0:
        return [("L", [x2, y2])]
    phi = math.radians(rotation % 360)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    xp, yp = cp * dx + sp * dy, -sp * dx + cp * dy
    scale = xp * xp / (rx * rx) + yp * yp / (ry * ry)
    if scale > 1:
        rx *= math.sqrt(scale)
        ry *= math.sqrt(scale)
    numerator = max(0, rx * rx * ry * ry - rx * rx * yp * yp - ry * ry * xp * xp)
    denominator = rx * rx * yp * yp + ry * ry * xp * xp
    coefficient = (-1 if large == sweep else 1) * math.sqrt(numerator / denominator if denominator else 0)
    cxp, cyp = coefficient * rx * yp / ry, -coefficient * ry * xp / rx
    cx, cy = cp * cxp - sp * cyp + (x1 + x2) / 2, sp * cxp + cp * cyp + (y1 + y2) / 2
    ux, uy = (xp - cxp) / rx, (yp - cyp) / ry
    vx, vy = (-xp - cxp) / rx, (-yp - cyp) / ry
    angle = math.atan2(uy, ux)
    delta = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    if not sweep and delta > 0:
        delta -= math.tau
    if sweep and delta < 0:
        delta += math.tau
    count = max(1, math.ceil(abs(delta) / (math.pi / 2)))
    step = delta / count
    segments = []

    def point(t):
        return cx + rx * cp * math.cos(t) - ry * sp * math.sin(t), cy + rx * sp * math.cos(
            t
        ) + ry * cp * math.sin(t)

    def derivative(t):
        return -rx * cp * math.sin(t) - ry * sp * math.cos(t), -rx * sp * math.sin(t) + ry * cp * math.cos(t)

    for index in range(count):
        a, b = angle + index * step, angle + (index + 1) * step
        k = 4 / 3 * math.tan(step / 4)
        p, q = point(a), point(b)
        u, v = derivative(a), derivative(b)
        segments.append(
            ("C", [p[0] + k * u[0], p[1] + k * u[1], q[0] - k * v[0], q[1] - k * v[1], q[0], q[1]])
        )
    segments[-1][1][-2:] = [x2, y2]
    return segments


def _segments(data):
    tokens = _path_segments(data)
    index = 0
    command = None
    current = (0.0, 0.0)
    start = current
    last = None
    control = None
    segments = []
    arity = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}
    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
            if command.upper() == "Z":
                _require(segments, "invalid_vector")
                segments.append(("Z", []))
                current = start
                last = "Z"
                control = None
                command = None
                continue
        _require(command is not None and command.upper() in arity, "invalid_vector")
        upper = command.upper()
        count = arity[upper]
        _require(
            index + count <= len(tokens) and all(not v.isalpha() for v in tokens[index : index + count]),
            "invalid_vector",
        )
        values = [float(v) for v in tokens[index : index + count]]
        index += count
        for number in values:
            _number(number)
        relative = command.islower()
        x, y = current
        if upper in {"M", "L", "C", "S", "Q", "T"} and relative:
            values = [v + (x if i % 2 == 0 else y) for i, v in enumerate(values)]
        if upper == "H":
            values = [values[0] + (x if relative else 0), y]
            upper = "L"
        elif upper == "V":
            values = [x, values[0] + (y if relative else 0)]
            upper = "L"
        elif upper == "S":
            reflected = [2 * x - control[0], 2 * y - control[1]] if last in {"C", "S"} and control else [x, y]
            values = reflected + values
            upper = "C"
        elif upper == "T":
            reflected = [2 * x - control[0], 2 * y - control[1]] if last in {"Q", "T"} and control else [x, y]
            values = reflected + values
            upper = "Q"
        elif upper == "A":
            if relative:
                values[-2] += x
                values[-1] += y
            segments.extend(_arc(current, values))
            current = tuple(values[-2:])
            last = "A"
            control = None
            continue
        if upper == "M":
            current = tuple(values)
            start = current
            segments.append(("M", values))
            command = "l" if relative else "L"
        else:
            _require(segments, "invalid_vector")
            segments.append((upper, values))
            current = tuple(values[-2:])
        control = tuple(values[-4:-2]) if upper in {"C", "Q"} else None
        last = upper
        _require(len(segments) <= 4096, "invalid_vector")
    _require(segments and segments[0][0] == "M", "invalid_vector")
    return segments


def _serialize_segments(segments):
    return " ".join(
        command + (" " + " ".join(_fmt(v) for v in values) if values else "") for command, values in segments
    )


def normalize_path(data):
    """Convert SVG numeric path commands to the Plugin API's absolute MLQCZ."""
    try:
        return _serialize_segments(_segments(data))
    except (ValueError, OverflowError, ZeroDivisionError, TypeError):
        raise BlueprintError("invalid_vector") from None


def _transform_segments(segments, sx=1, sy=1, dx=0, dy=0):
    return [
        (command, [v * (sx if i % 2 == 0 else sy) + (dx if i % 2 == 0 else dy) for i, v in enumerate(values)])
        for command, values in segments
    ]


def _bounds(segments):
    points = []
    current = (0.0, 0.0)
    start = current

    def roots(a, b, c):
        if abs(a) < 1e-12:
            return [] if abs(b) < 1e-12 else [-c / b]
        discriminant = b * b - 4 * a * c
        if discriminant < 0:
            return []
        return [(-b + math.sqrt(discriminant)) / (2 * a), (-b - math.sqrt(discriminant)) / (2 * a)]

    for command, values in segments:
        if command == "M":
            current = tuple(values)
            start = current
            points.append(current)
        elif command in {"L", "Z"}:
            current = tuple(values) if command == "L" else start
            points.append(current)
        else:
            p = [current] + [tuple(values[i : i + 2]) for i in range(0, len(values), 2)]
            times = {0.0, 1.0}
            for axis in (0, 1):
                coords = [v[axis] for v in p]
                if command == "Q":
                    denominator = coords[0] - 2 * coords[1] + coords[2]
                    candidates = [] if abs(denominator) < 1e-12 else [(coords[0] - coords[1]) / denominator]
                else:
                    a, b, c, d = coords
                    candidates = roots(3 * (-a + 3 * b - 3 * c + d), 6 * (a - 2 * b + c), 3 * (b - a))
                times.update(t for t in candidates if 0 < t < 1)
            for t in times:
                if command == "Q":
                    points.append(
                        tuple(
                            (1 - t) ** 2 * p[0][a] + 2 * (1 - t) * t * p[1][a] + t * t * p[2][a]
                            for a in (0, 1)
                        )
                    )
                else:
                    points.append(
                        tuple(
                            (1 - t) ** 3 * p[0][a]
                            + 3 * (1 - t) ** 2 * t * p[1][a]
                            + 3 * (1 - t) * t * t * p[2][a]
                            + t**3 * p[3][a]
                            for a in (0, 1)
                        )
                    )
            current = p[-1]
    _require(points, "invalid_vector")
    return (
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    )


def _ellipse_path(cx, cy, rx, ry):
    k = 0.5522847498307936
    return [
        ("M", [cx + rx, cy]),
        ("C", [cx + rx, cy + k * ry, cx + k * rx, cy + ry, cx, cy + ry]),
        ("C", [cx - k * rx, cy + ry, cx - rx, cy + k * ry, cx - rx, cy]),
        ("C", [cx - rx, cy - k * ry, cx - k * rx, cy - ry, cx, cy - ry]),
        ("C", [cx + k * rx, cy - ry, cx + rx, cy - k * ry, cx + rx, cy]),
        ("Z", []),
    ]


def _svg_paths(source):
    _require(isinstance(source, str) and len(source) <= 128 * 1024, "invalid_asset")
    _require("<!DOCTYPE" not in source.upper() and "<!ENTITY" not in source.upper(), "invalid_asset")
    try:
        root = ElementTree.fromstring(source)
    except (ElementTree.ParseError, ValueError):
        raise BlueprintError("invalid_asset") from None
    _require(root.tag == "{http://www.w3.org/2000/svg}svg", "invalid_asset")
    _require(
        set(root.attrib)
        <= {
            "width",
            "height",
            "viewBox",
            "fill",
            "stroke",
            "stroke-width",
            "stroke-linecap",
            "stroke-linejoin",
        },
        "invalid_asset",
    )
    view = [float(v) for v in root.attrib.get("viewBox", "").split()]
    _require(len(view) == 4 and view[:2] == [0.0, 0.0] and view[2] > 0 and view[3] > 0, "invalid_asset")
    result = []
    for element in root:
        name = element.tag.rsplit("}", 1)[-1]
        a = element.attrib
        _require(not list(element), "invalid_asset")
        if name == "path":
            _require(set(a) == {"d"}, "invalid_asset")
            segments = _segments(a["d"])
        elif name in {"circle", "ellipse"}:
            allowed = {"cx", "cy", "r"} if name == "circle" else {"cx", "cy", "rx", "ry"}
            _require(
                set(a) <= allowed and ("r" in a if name == "circle" else "rx" in a and "ry" in a),
                "invalid_asset",
            )
            cx, cy = float(a.get("cx", 0)), float(a.get("cy", 0))
            rx = float(a["r"] if name == "circle" else a["rx"])
            ry = float(a["r"] if name == "circle" else a["ry"])
            segments = _ellipse_path(cx, cy, rx, ry)
        elif name == "rect":
            _require(
                set(a) <= {"x", "y", "width", "height", "rx", "ry"} and {"width", "height"} <= set(a),
                "invalid_asset",
            )
            x, y, w, h = (float(a.get(k, 0)) for k in ("x", "y", "width", "height"))
            r = min(float(a.get("rx", a.get("ry", 0))), w / 2, h / 2)
            segments = _segments(
                f"M{x + r} {y} H{x + w - r} Q{x + w} {y} {x + w} {y + r} V{y + h - r} Q{x + w} {y + h} {x + w - r} {y + h} H{x + r} Q{x} {y + h} {x} {y + h - r} V{y + r} Q{x} {y} {x + r} {y} Z"
            )
        elif name == "line":
            _require(set(a) <= {"x1", "x2", "y1", "y2"}, "invalid_asset")
            x1, y1, x2, y2 = (float(a.get(k, 0)) for k in ("x1", "y1", "x2", "y2"))
            segments = _segments(f"M{x1} {y1} L{x2} {y2}")
        elif name in {"polyline", "polygon"}:
            _require(set(a) == {"points"}, "invalid_asset")
            numbers = [float(v) for v in re.split(r"[\s,]+", a["points"].strip())]
            _require(len(numbers) >= 4 and len(numbers) % 2 == 0, "invalid_asset")
            segments = [("M", numbers[:2])] + [("L", numbers[i : i + 2]) for i in range(2, len(numbers), 2)]
            if name == "polygon":
                segments.append(("Z", []))
        else:
            raise BlueprintError("unsupported_feature")
        result.append(segments)
    _require(1 <= len(result) <= 128, "invalid_asset")
    return result, view[2], view[3]


def compile_blueprint(source):
    """Lower the complete offline design IR to wire v1, without host access."""
    try:
        return _compile_blueprint(source)
    except BlueprintError:
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError):
        raise BlueprintError() from None


def _compile_blueprint(source):
    _exact(
        source,
        {"schema_version", "title", "variables", "text_styles", "assets", "component_sets", "node_trees"},
        _SOURCE_TOP
        - {"schema_version", "title", "variables", "text_styles", "assets", "component_sets", "node_trees"},
    )
    _require(type(source["schema_version"]) is int and source["schema_version"] == 1)
    _require(len(_dump(source)) <= MAX_BLUEPRINT_BYTES, "blueprint_too_large")
    collection = source["variables"]["collection"]
    modes = collection["modes"]
    _require(
        len(modes) == 1 and modes[0]["id"] == collection["default_mode_ref"] and modes[0]["name"] == "Default"
    )
    mode_key = modes[0]["id"]
    variables = []
    colors = {}
    for item in source["variables"]["items"]:
        _require(set(item["values_by_mode"]) == {mode_key} and item["collection_ref"] == collection["id"])
        variable = {
            "key": item["id"],
            "name": item["name"],
            "type": item["resolved_type"],
            "value": deepcopy(item["values_by_mode"][mode_key]),
        }
        variables.append(variable)
        if item["resolved_type"] == "COLOR":
            token_name = item["id"][9:] if item["id"].startswith("variable/") else item["id"]
            colors[token_name] = variable["value"]
    assets = []
    vector_assets = {}
    for asset in source["assets"]:
        if asset["kind"] == "IMAGE":
            _require(asset["mime_type"] == "image/png", "invalid_asset")
            assets.append(
                {
                    "key": asset["id"],
                    "mime_type": "image/png",
                    "data_base64": asset["data_base64"],
                    "sha256": asset["sha256"],
                    "width": asset["intrinsic_dimensions"][0],
                    "height": asset["intrinsic_dimensions"][1],
                }
            )
        elif asset["kind"] == "VECTOR_SVG":
            canonical = asset["svg"].replace("\r\n", "\n")
            hashes = {
                hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                hashlib.sha256(canonical.replace("\n", "\r\n").encode("utf-8")).hexdigest(),
            }
            _require(asset["sha256"] in hashes, "invalid_asset")
            vector_assets[asset["id"]] = _svg_paths(asset["svg"])
        else:
            raise BlueprintError("unsupported_feature")
    styles = {s["id"]: s for s in source["text_styles"]}
    all_source = {n["id"]: n for n in _walk(source["node_trees"])}
    _require(len(all_source) == sum(1 for _ in _walk(source["node_trees"])))
    source_allowed = {
        "id",
        "type",
        "name",
        "bounds",
        "visible",
        "opacity",
        "children",
        "fill",
        "stroke",
        "stroke_width",
        "variable_bindings",
        "layoutSizingHorizontal",
        "layoutSizingVertical",
        "layout_positioning",
        "constraints",
        "clip_content",
        "auto_layout",
        "radius",
        "geometry",
        "component_set_id",
        "variant_properties",
        "text",
        "text_style",
        "text_style_ref",
        "font",
        "font_size",
        "line_height",
        "align",
        "slot",
        "textAutoResize",
        "component_ref",
        "overrides",
        "asset",
        "image_fit",
        "preserve_pixels",
        "interaction",
        "purpose",
        "motion",
        "viewport",
        "state",
    }

    def paint(value):
        if value is None:
            return None
        if value in colors:
            return deepcopy(colors[value])
        _require(isinstance(value, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", value))
        return {
            **{channel: int(value[1 + i * 2 : 3 + i * 2], 16) / 255 for i, channel in enumerate("rgb")},
            "a": 1,
        }

    def lower(n):
        _require(isinstance(n, dict) and set(n) <= source_allowed)
        result = {
            "key": n["id"],
            "type": n["type"],
            "name": n.get("name", n["id"])[-120:],
            "bounds": deepcopy(n["bounds"]),
            "visible": n.get("visible", True),
            "opacity": n.get("opacity", 1),
        }
        for prop in (
            "stroke_width",
            "variable_bindings",
            "layoutSizingHorizontal",
            "layoutSizingVertical",
            "layout_positioning",
            "constraints",
            "clip_content",
        ):
            if prop in n:
                result[prop] = deepcopy(n[prop])
        for prop in ("fill", "stroke"):
            if prop in n:
                result[prop] = paint(n[prop])
        if "radius" in n:
            result["corner_radius"] = n["radius"]
        if n["type"] in {"FRAME", "COMPONENT"}:
            result["children"] = [lower(c) for c in n["children"]]
            a = n.get("auto_layout")
            if isinstance(a, dict):
                result["auto_layout"] = {key: deepcopy(a[key]) for key in _LAYOUT_FIELDS}
            if n["type"] == "COMPONENT":
                result.update(
                    component_set_ref=n["component_set_id"],
                    variant_properties=deepcopy(n["variant_properties"]) if n["component_set_id"] else {},
                )
        elif n["type"] == "TEXT":
            style = styles[n["text_style_ref"]]
            _require(
                n["font"]["family"] == style["family"]
                and n["font"]["style"] == style["style"]
                and n["font_size"] == style["font_size"]
                and n["line_height"] == style["line_height"]
            )
            result.update(
                characters=n["text"],
                font={"family": n["font"]["family"], "style": n["font"]["style"]},
                font_size=n["font_size"],
                line_height=n["line_height"],
                align=n["align"],
            )
            if "textAutoResize" in n:
                result["textAutoResize"] = n["textAutoResize"]
        elif n["type"] == "INSTANCE":
            target = all_source[n["component_ref"]]
            slots = {}
            for child in _walk(target["children"]):
                if "slot" in child:
                    _require(child["slot"] not in slots)
                    slots[child["slot"]] = child["id"]
            overrides = []
            for slot, changes in n["overrides"].items():
                _require(slot in slots and set(changes) <= {"text", "visible"})
                override = {"target_key": slots[slot]}
                if "text" in changes:
                    override["characters"] = changes["text"]
                if "visible" in changes:
                    override["visible"] = changes["visible"]
                overrides.append(override)
            result.update(component_ref=n["component_ref"], overrides=overrides)
        elif n["type"] == "IMAGE":
            result.update(asset_ref=n["asset"], image_fit=n["image_fit"])
        elif n["type"] == "VECTOR":
            geometry = n["geometry"]
            kind = geometry["kind"]
            if kind == "rect":
                result.update(type="RECTANGLE", corner_radius=geometry["radius"])
            elif kind == "ellipse":
                result["type"] = "ELLIPSE"
            elif kind in {"path", "lucide"}:
                if kind == "path":
                    paths = [_segments(geometry["d"])]
                    sx = sy = 1
                else:
                    paths, vw, vh = vector_assets[geometry["asset_ref"]]
                    sx = n["bounds"]["width"] / vw
                    sy = n["bounds"]["height"] / vh
                paths = [_transform_segments(p, sx, sy) for p in paths]
                bounds = [_bounds(p) for p in paths]
                left = min(b[0] for b in bounds)
                top = min(b[1] for b in bounds)
                right = max(b[2] for b in bounds)
                bottom = max(b[3] for b in bounds)
                data = [
                    {
                        "windingRule": "NONZERO",
                        "data": _serialize_segments(_transform_segments(p, dx=-left, dy=-top)),
                    }
                    for p in paths
                ]
                if kind == "path":
                    result["bounds"].update(
                        x=n["bounds"]["x"] + left,
                        y=n["bounds"]["y"] + top,
                        width=right - left,
                        height=bottom - top,
                    )
                    result.update(paths=data, stroke_cap="ROUND", stroke_join="ROUND")
                else:
                    child = {
                        "key": n["id"] + "/vector",
                        "type": "VECTOR",
                        "name": "Lucide vector geometry",
                        "bounds": {"x": left, "y": top, "width": right - left, "height": bottom - top},
                        "visible": True,
                        "opacity": 1,
                        "paths": data,
                        "stroke_cap": "ROUND",
                        "stroke_join": "ROUND",
                    }
                    for prop in ("fill", "stroke", "stroke_width", "variable_bindings"):
                        if prop in result:
                            child[prop] = result.pop(prop)
                    result.update(
                        type="FRAME",
                        children=[child],
                        auto_layout={
                            "mode": "NONE",
                            "item_spacing": 0,
                            "padding": [0, 0, 0, 0],
                            "primary_axis_sizing": "FIXED",
                            "counter_axis_sizing": "FIXED",
                            "primary_axis_align": "MIN",
                            "counter_axis_align": "MIN",
                        },
                    )
            else:
                raise BlueprintError("unsupported_feature")
        else:
            raise BlueprintError("unsupported_feature")
        return result

    groups = [
        {
            "key": g["id"],
            "component_keys": deepcopy(g["component_refs"]),
            "variant_properties": {key: deepcopy(v["values"]) for key, v in g["variant_properties"].items()},
        }
        for g in source["component_sets"]
    ]
    wire = {
        "schema_version": 1,
        "title": source["title"],
        "assets": assets,
        "variables": {
            "collection": {
                "key": collection["id"],
                "name": collection["id"],
                "mode_key": mode_key,
                "mode_name": "Default",
            },
            "items": variables,
        },
        "component_sets": groups,
        "node_trees": [lower(n) for n in source["node_trees"]],
    }
    return validate_blueprint(wire)


def validate_blueprint(value):
    try:
        return _validate_blueprint(value)
    except BlueprintError:
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError):
        raise BlueprintError() from None


def blueprint_stats(value):
    """Return bounded offline counts, never an observed native-node receipt."""
    wire = validate_blueprint(value)
    lookup = {n["key"]: n for n in _walk(wire["node_trees"])}

    def count(n):
        return 1 + sum(
            count(c)
            for c in (
                lookup[n["component_ref"]]["children"] if n["type"] == "INSTANCE" else n.get("children", [])
            )
        )

    return {
        "wire_bytes": len(_dump(wire)),
        "declared_nodes": len(lookup),
        "expanded_nodes_with_outer_and_sets": 1
        + len(wire["component_sets"])
        + sum(count(n) for n in wire["node_trees"]),
        "components": sum(n["type"] == "COMPONENT" for n in lookup.values()),
        "screen_roots": sum(n["type"] == "FRAME" for n in wire["node_trees"]),
        "component_sets": len(wire["component_sets"]),
        "variables": len(wire["variables"]["items"]),
        "image_assets": len(wire["assets"]),
        "native_execution": "NOT_RUN",
    }


def compilation_report(source, wire):
    """Describe intentional source-to-wire projections, separate from authority."""
    return {
        "schema_version": 1,
        "native_execution": "NOT_RUN",
        "stats": blueprint_stats(wire),
        "wire_sha256": blueprint_digest(wire),
        "projections": {
            "text_styles_inlined": len(source["text_styles"]),
            "native_text_style_assets_created": False,
            "svg_assets_lowered_to_typed_paths": sum(a["kind"] == "VECTOR_SVG" for a in source["assets"]),
            "svg_line_endings": "Canonical LF or exact reconstructed CRLF must match the pinned input digest.",
            "standalone_component_annotations_removed": [
                n["id"]
                for n in source["node_trees"]
                if n["type"] == "COMPONENT"
                and n.get("component_set_id") is None
                and n.get("variant_properties")
            ],
            "nonexecuting_metadata": [
                "native_execution",
                "security",
                "native_acceptance",
                "execution_status",
                "current_adapter_missing_operations",
                "layout_execution_constraints",
                "complexity_estimate",
                "interaction",
                "motion",
                "purpose",
                "viewport",
                "state",
            ],
        },
        "permissions_or_pairing_granted": False,
        "native_count_observed": False,
    }
