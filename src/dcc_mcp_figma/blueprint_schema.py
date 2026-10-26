"""Discovery schema for the closed, data-only blueprint wire protocol.

References are local to this standalone schema. A containing MCP input schema
must lift these definitions to its own root without mutating this document.
The runtime validator additionally enforces per-type fields and graph budgets.
"""


def _object(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _ref(name):
    return {"$ref": "#/$defs/" + name}


def _array(items, maximum, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


KEY = {
    "type": "string",
    "minLength": 1,
    "maxLength": 200,
    "pattern": r"^[A-Za-z0-9][A-Za-z0-9_./:\-]{0,199}$",
}
NAME = {"type": "string", "minLength": 1, "maxLength": 120}
NUMBER = {"type": "number", "minimum": -1000000, "maximum": 1000000}
DIMENSION = {"type": "number", "minimum": 0, "maximum": 8192}
RGBA = _object(
    {key: {"type": "number", "minimum": 0, "maximum": 1} for key in ("r", "g", "b", "a")},
    ("r", "g", "b", "a"),
)
PAINT = {"anyOf": [_ref("rgba"), {"type": "null"}]}
LAYOUT = _object(
    {
        "mode": {"type": "string", "enum": ["NONE", "HORIZONTAL", "VERTICAL"]},
        "item_spacing": {"type": "number", "minimum": 0, "maximum": 8192},
        "padding": {
            "type": "array",
            "items": {"type": "number", "minimum": 0, "maximum": 8192},
            "minItems": 4,
            "maxItems": 4,
        },
        "primary_axis_sizing": {"type": "string", "enum": ["FIXED", "AUTO"]},
        "counter_axis_sizing": {"type": "string", "enum": ["FIXED", "AUTO"]},
        "primary_axis_align": {"type": "string", "enum": ["MIN", "CENTER", "MAX", "SPACE_BETWEEN"]},
        "counter_axis_align": {"type": "string", "enum": ["MIN", "CENTER", "MAX", "BASELINE"]},
    },
    (
        "mode",
        "item_spacing",
        "padding",
        "primary_axis_sizing",
        "counter_axis_sizing",
        "primary_axis_align",
        "counter_axis_align",
    ),
)
FONT = _object(
    {key: {"type": "string", "minLength": 1, "maxLength": 100} for key in ("family", "style")},
    ("family", "style"),
)
OVERRIDE = _object(
    {"target_key": KEY, "characters": {"type": "string", "maxLength": 8192}, "visible": {"type": "boolean"}},
    ("target_key",),
)
PATH = _object(
    {
        "windingRule": {"type": "string", "enum": ["NONZERO", "EVENODD"]},
        "data": {
            "type": "string",
            "minLength": 1,
            "maxLength": 131072,
            "description": "Canonical absolute M/L/Q/C/Z only, finite bounded numbers and single-space tokens.",
        },
    },
    ("windingRule", "data"),
)
ASSET = _object(
    {
        "key": KEY,
        "mime_type": {"type": "string", "enum": ["image/png"]},
        "data_base64": {"type": "string", "minLength": 1, "maxLength": 1398104},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "width": {"type": "integer", "minimum": 1, "maximum": 4096},
        "height": {"type": "integer", "minimum": 1, "maximum": 4096},
    },
    ("key", "mime_type", "data_base64", "sha256", "width", "height"),
)
VARIABLE = _object(
    {
        "key": KEY,
        "name": NAME,
        "type": {"type": "string", "enum": ["COLOR", "FLOAT"]},
        "value": {"oneOf": [_ref("rgba"), NUMBER]},
    },
    ("key", "name", "type", "value"),
)
COLLECTION = _object(
    {"key": KEY, "name": NAME, "mode_key": KEY, "mode_name": {"type": "string", "enum": ["Default"]}},
    ("key", "name", "mode_key", "mode_name"),
)
VARIANT_VALUES = {
    "type": "object",
    "maxProperties": 8,
    "propertyNames": {"type": "string", "minLength": 1, "maxLength": 40},
    "additionalProperties": _array({"type": "string", "minLength": 1, "maxLength": 80}, 64, 1),
}
VARIANT_SELECTION = {
    "type": "object",
    "maxProperties": 8,
    "propertyNames": {"type": "string", "minLength": 1, "maxLength": 40},
    "additionalProperties": {"type": "string", "minLength": 1, "maxLength": 80},
}
COMPONENT_SET = _object(
    {"key": KEY, "component_keys": _array(KEY, 2048, 2), "variant_properties": VARIANT_VALUES},
    ("key", "component_keys", "variant_properties"),
)
NODE_PROPERTIES = {
    "key": KEY,
    "type": {
        "type": "string",
        "enum": ["FRAME", "COMPONENT", "TEXT", "INSTANCE", "VECTOR", "IMAGE", "RECTANGLE", "ELLIPSE"],
    },
    "name": NAME,
    "bounds": _object(
        {"x": NUMBER, "y": NUMBER, "width": DIMENSION, "height": DIMENSION}, ("x", "y", "width", "height")
    ),
    "visible": {"type": "boolean"},
    "opacity": {"type": "number", "minimum": 0, "maximum": 1},
    "children": _array(_ref("node"), 2048),
    "fill": PAINT,
    "stroke": PAINT,
    "stroke_width": {"type": "number", "minimum": 0, "maximum": 128},
    "corner_radius": {"type": "number", "minimum": 0, "maximum": 4096},
    "stroke_cap": {"type": "string", "enum": ["NONE", "ROUND", "SQUARE"]},
    "stroke_join": {"type": "string", "enum": ["MITER", "ROUND", "BEVEL"]},
    "variable_bindings": _object(
        {key: KEY for key in ("fill", "stroke", "strokeWeight", "cornerRadius", "width", "height")}
    ),
    "layoutSizingHorizontal": {"type": "string", "enum": ["FIXED", "FILL", "HUG"]},
    "layoutSizingVertical": {"type": "string", "enum": ["FIXED", "FILL", "HUG"]},
    "layout_positioning": {"type": "string", "enum": ["AUTO", "ABSOLUTE"]},
    "constraints": _object(
        {
            key: {"type": "string", "enum": ["MIN", "CENTER", "MAX", "STRETCH", "SCALE"]}
            for key in ("horizontal", "vertical")
        },
        ("horizontal", "vertical"),
    ),
    "clip_content": {"type": "boolean"},
    "auto_layout": _ref("layout"),
    "component_set_ref": {"anyOf": [KEY, {"type": "null"}]},
    "variant_properties": VARIANT_SELECTION,
    "characters": {"type": "string", "maxLength": 8192},
    "font": _ref("font"),
    "font_size": {"type": "number", "minimum": 1, "maximum": 512},
    "line_height": {"type": "number", "minimum": 1, "maximum": 1024},
    "align": {"type": "string", "enum": ["left", "center", "right"]},
    "textAutoResize": {"type": "string", "enum": ["NONE", "HEIGHT", "WIDTH_AND_HEIGHT"]},
    "component_ref": KEY,
    "overrides": _array(_ref("override"), 64),
    "paths": _array(_ref("path"), 128, 1),
    "asset_ref": KEY,
    "image_fit": {"type": "string", "enum": ["CONTAIN"]},
}
BLUEPRINT_SCHEMA = _object(
    {
        "schema_version": {"type": "integer", "enum": [1]},
        "title": NAME,
        "assets": _array(_ref("asset"), 16),
        "variables": _object(
            {"collection": _ref("collection"), "items": _array(_ref("variable"), 64)}, ("collection", "items")
        ),
        "component_sets": _array(_ref("component_set"), 32),
        "node_trees": _array(_ref("node"), 2048, 1),
    },
    ("schema_version", "title", "assets", "variables", "component_sets", "node_trees"),
)
BLUEPRINT_SCHEMA["$defs"] = {
    "node": _object(NODE_PROPERTIES, ("key", "type", "name", "bounds", "visible", "opacity")),
    "rgba": RGBA,
    "layout": LAYOUT,
    "font": FONT,
    "override": OVERRIDE,
    "path": PATH,
    "asset": ASSET,
    "variable": VARIABLE,
    "collection": COLLECTION,
    "component_set": COMPONENT_SET,
}
BLUEPRINT_SCHEMA["description"] = (
    "Typed blueprint v1: no source metadata, eval or remote resource loading. "
    "Per-type fields, ownership-independent validation, 2 MiB bytes, 2048 expanded nodes including outer/set nodes, "
    "depth 24, 16 fonts, 1 MiB decoded PNGs and 256 KiB path data are enforced before dispatch."
)
