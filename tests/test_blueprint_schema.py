"""Closed discovery schemas and local references; no Figma host is involved."""

from copy import deepcopy

import pytest

from dcc_mcp_figma.blueprint import BLUEPRINT_SCHEMA as REEXPORTED_SCHEMA
from dcc_mcp_figma.blueprint_schema import BLUEPRINT_SCHEMA


def _node(node_type="FRAME"):
    return {
        "key": "screen/default",
        "type": node_type,
        "name": "Synthetic schema fixture",
        "bounds": {"x": 0, "y": 0, "width": 320, "height": 180},
        "visible": True,
        "opacity": 1,
    }


_RGBA = {"r": 0, "g": 0.5, "b": 1, "a": 1}
_LAYOUT = {
    "mode": "VERTICAL",
    "item_spacing": 8,
    "padding": [8, 8, 8, 8],
    "primary_axis_sizing": "FIXED",
    "counter_axis_sizing": "FIXED",
    "primary_axis_align": "MIN",
    "counter_axis_align": "MIN",
}
_COLLECTION = {"key": "tokens", "name": "Tokens", "mode_key": "default", "mode_name": "Default"}
_ASSET = {
    "key": "brand",
    "mime_type": "image/png",
    "data_base64": "AA==",
    "sha256": "0" * 64,
    "width": 1,
    "height": 1,
}
_COMPONENT_SET = {
    "key": "button",
    "component_keys": ["button/default", "button/loading"],
    "variant_properties": {"State": ["Default", "Loading"]},
}
_WIRE = {
    "schema_version": 1,
    "title": "Synthetic discovery schema fixture",
    "assets": [],
    "variables": {"collection": _COLLECTION, "items": []},
    "component_sets": [],
    "node_trees": [_node()],
}
_NODE_FIELDS = {
    "key",
    "type",
    "name",
    "bounds",
    "visible",
    "opacity",
    "children",
    "fill",
    "stroke",
    "stroke_width",
    "corner_radius",
    "stroke_cap",
    "stroke_join",
    "variable_bindings",
    "layoutSizingHorizontal",
    "layoutSizingVertical",
    "layout_positioning",
    "constraints",
    "clip_content",
    "auto_layout",
    "component_set_ref",
    "variant_properties",
    "characters",
    "font",
    "font_size",
    "line_height",
    "align",
    "textAutoResize",
    "component_ref",
    "overrides",
    "paths",
    "asset_ref",
    "image_fit",
}

# Each entry independently specifies the public property allowlist and required
# fields. Dynamic variant-property maps have separate bounded-map contracts.
_CLOSED_OBJECTS = [
    ((), set(_WIRE), set(_WIRE), _WIRE),
    (
        ("properties", "variables"),
        {"collection", "items"},
        {"collection", "items"},
        _WIRE["variables"],
    ),
    (
        ("$defs", "node"),
        _NODE_FIELDS,
        {"key", "type", "name", "bounds", "visible", "opacity"},
        _node(),
    ),
    (
        ("$defs", "node", "properties", "bounds"),
        {"x", "y", "width", "height"},
        {"x", "y", "width", "height"},
        _node()["bounds"],
    ),
    (
        ("$defs", "node", "properties", "variable_bindings"),
        {"fill", "stroke", "strokeWeight", "cornerRadius", "width", "height"},
        set(),
        {"height": "variable/control-height"},
    ),
    (
        ("$defs", "node", "properties", "constraints"),
        {"horizontal", "vertical"},
        {"horizontal", "vertical"},
        {"horizontal": "MIN", "vertical": "MIN"},
    ),
    (("$defs", "rgba"), set(_RGBA), set(_RGBA), _RGBA),
    (("$defs", "layout"), set(_LAYOUT), set(_LAYOUT), _LAYOUT),
    (
        ("$defs", "font"),
        {"family", "style"},
        {"family", "style"},
        {"family": "Noto Sans SC", "style": "Regular"},
    ),
    (
        ("$defs", "override"),
        {"target_key", "characters", "visible"},
        {"target_key"},
        {"target_key": "button/label"},
    ),
    (
        ("$defs", "path"),
        {"windingRule", "data"},
        {"windingRule", "data"},
        {"windingRule": "NONZERO", "data": "M 0 0 L 1 1"},
    ),
    (("$defs", "asset"), set(_ASSET), set(_ASSET), _ASSET),
    (
        ("$defs", "variable"),
        {"key", "name", "type", "value"},
        {"key", "name", "type", "value"},
        {"key": "variable/blue", "name": "Blue", "type": "COLOR", "value": _RGBA},
    ),
    (("$defs", "collection"), set(_COLLECTION), set(_COLLECTION), _COLLECTION),
    (("$defs", "component_set"), set(_COMPONENT_SET), set(_COMPONENT_SET), _COMPONENT_SET),
]


def _at(path, document=BLUEPRINT_SCHEMA):
    for part in path:
        document = document[part]
    return document


def _walk_schema(value, path=()):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _walk_schema(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_schema(child, path + (index,))


def _fragment(path):
    schema = deepcopy(_at(path))
    schema["$defs"] = deepcopy(BLUEPRINT_SCHEMA["$defs"])
    return schema


@pytest.fixture
def jsonschema():
    return pytest.importorskip("jsonschema", reason="Use the installed validator only; never install it.")


def test_standalone_reexport_and_every_reference_resolves_locally():
    assert REEXPORTED_SCHEMA is BLUEPRINT_SCHEMA
    assert "node" in BLUEPRINT_SCHEMA["$defs"]
    references = [schema["$ref"] for _, schema in _walk_schema(BLUEPRINT_SCHEMA) if "$ref" in schema]
    assert "#/$defs/node" in references
    for reference in references:
        assert reference.startswith("#/$defs/")
        assert isinstance(_at(tuple(reference[2:].split("/"))), dict)


def test_standalone_schema_and_minimal_wire_validate(jsonschema):
    jsonschema.Draft202012Validator.check_schema(BLUEPRINT_SCHEMA)
    jsonschema.Draft202012Validator(BLUEPRINT_SCHEMA).validate(deepcopy(_WIRE))


def test_closed_object_inventory_covers_every_typed_object():
    actual = {
        path
        for path, schema in _walk_schema(BLUEPRINT_SCHEMA)
        if schema.get("type") == "object" and "properties" in schema
    }
    assert actual == {path for path, _, _, _ in _CLOSED_OBJECTS}


@pytest.mark.parametrize(
    "path,allowed,required,example",
    _CLOSED_OBJECTS,
    ids=["/".join(row[0]) or "root" for row in _CLOSED_OBJECTS],
)
def test_typed_object_property_allowlists_are_closed(path, allowed, required, example):
    schema = _at(path)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == allowed
    assert set(schema["required"]) == required
    assert len(schema["required"]) == len(required)


@pytest.mark.parametrize(
    "path,allowed,required,example",
    _CLOSED_OBJECTS,
    ids=["/".join(row[0]) or "root" for row in _CLOSED_OBJECTS],
)
def test_each_typed_object_rejects_unknown_properties(jsonschema, path, allowed, required, example):
    validator = jsonschema.Draft202012Validator(_fragment(path))
    validator.validate(deepcopy(example))
    unknown = dict(deepcopy(example), unexpected_remote_script="https://example.invalid/forbidden.js")
    with pytest.raises(jsonschema.ValidationError) as rejected:
        validator.validate(unknown)
    assert rejected.value.validator == "additionalProperties"


@pytest.mark.parametrize(
    "node_type", ["FRAME", "COMPONENT", "TEXT", "INSTANCE", "VECTOR", "IMAGE", "RECTANGLE", "ELLIPSE"]
)
def test_node_enum_exposes_all_typed_geometry_without_arbitrary_code(jsonschema, node_type):
    expected = {"FRAME", "COMPONENT", "TEXT", "INSTANCE", "VECTOR", "IMAGE", "RECTANGLE", "ELLIPSE"}
    assert set(BLUEPRINT_SCHEMA["$defs"]["node"]["properties"]["type"]["enum"]) == expected
    wire = deepcopy(_WIRE)
    wire["node_trees"] = [_node(node_type)]
    validator = jsonschema.Draft202012Validator(BLUEPRINT_SCHEMA)
    validator.validate(wire)
    wire["node_trees"][0]["type"] = "SCRIPT"
    with pytest.raises(jsonschema.ValidationError) as rejected:
        validator.validate(wire)
    assert rejected.value.validator == "enum"


_ARRAYS = [
    (("properties", "assets"), 0, 16, _ASSET),
    (
        ("properties", "variables", "properties", "items"),
        0,
        64,
        {"key": "variable/height", "name": "Height", "type": "FLOAT", "value": 56},
    ),
    (("properties", "component_sets"), 0, 32, _COMPONENT_SET),
    (("properties", "node_trees"), 1, 2048, _node()),
    (("$defs", "node", "properties", "children"), 0, 2048, _node()),
    (("$defs", "node", "properties", "overrides"), 0, 64, {"target_key": "button/label"}),
    (("$defs", "node", "properties", "paths"), 1, 128, {"windingRule": "NONZERO", "data": "M 0 0"}),
    (("$defs", "layout", "properties", "padding"), 4, 4, 0),
    (("$defs", "component_set", "properties", "component_keys"), 2, 2048, "button/default"),
    (
        ("$defs", "component_set", "properties", "variant_properties", "additionalProperties"),
        1,
        64,
        "Default",
    ),
]


@pytest.mark.parametrize("path,minimum,maximum,item", _ARRAYS, ids=["/".join(row[0]) for row in _ARRAYS])
def test_arrays_have_explicit_resource_caps_and_enforce_them(jsonschema, path, minimum, maximum, item):
    schema = _at(path)
    assert schema["type"] == "array"
    assert (schema["minItems"], schema["maxItems"]) == (minimum, maximum)
    validator = jsonschema.Draft202012Validator(_fragment(path))
    validator.validate([deepcopy(item) for _ in range(minimum)])
    validator.validate([deepcopy(item) for _ in range(maximum)])
    with pytest.raises(jsonschema.ValidationError) as rejected:
        validator.validate([deepcopy(item) for _ in range(maximum + 1)])
    assert rejected.value.validator == "maxItems"
    if minimum:
        with pytest.raises(jsonschema.ValidationError) as rejected:
            validator.validate([deepcopy(item) for _ in range(minimum - 1)])
        assert rejected.value.validator == "minItems"


@pytest.mark.parametrize(
    "path,value",
    [
        (("$defs", "component_set", "properties", "variant_properties"), ["Default"]),
        (("$defs", "node", "properties", "variant_properties"), "Default"),
    ],
)
def test_variant_maps_are_explicitly_bounded_dynamic_objects(jsonschema, path, value):
    schema = _at(path)
    assert schema["type"] == "object"
    assert schema["maxProperties"] == 8
    assert schema["propertyNames"] == {"type": "string", "minLength": 1, "maxLength": 40}
    assert isinstance(schema["additionalProperties"], dict)
    validator = jsonschema.Draft202012Validator(_fragment(path))
    validator.validate({"Property" + str(i): deepcopy(value) for i in range(8)})
    with pytest.raises(jsonschema.ValidationError) as rejected:
        validator.validate({"Property" + str(i): deepcopy(value) for i in range(9)})
    assert rejected.value.validator == "maxProperties"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({"P" * 41: deepcopy(value)})


@pytest.mark.parametrize(
    "path,maximum,valid_prefix",
    [
        (("$defs", "asset", "properties", "data_base64"), 1398104, "A"),
        (("$defs", "path", "properties", "data"), 131072, "M"),
        (("$defs", "node", "properties", "characters"), 8192, "x"),
    ],
)
def test_large_string_resources_are_bounded(jsonschema, path, maximum, valid_prefix):
    assert _at(path)["maxLength"] == maximum
    validator = jsonschema.Draft202012Validator(_fragment(path))
    validator.validate(valid_prefix * maximum)
    with pytest.raises(jsonschema.ValidationError) as rejected:
        validator.validate(valid_prefix * (maximum + 1))
    assert rejected.value.validator == "maxLength"


@pytest.mark.parametrize("dimension", ["width", "height"])
def test_image_dimensions_have_integer_resource_caps(jsonschema, dimension):
    path = ("$defs", "asset", "properties", dimension)
    assert _at(path) == {"type": "integer", "minimum": 1, "maximum": 4096}
    validator = jsonschema.Draft202012Validator(_fragment(path))
    validator.validate(1)
    validator.validate(4096)
    for value in (0, 4097, 1.5, True):
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(value)


def test_production_mcp_schema_lifts_copied_definitions_without_mutating_standalone(jsonschema):
    from dcc_mcp_figma.tools import _blueprint_schema

    original = deepcopy(BLUEPRINT_SCHEMA)
    nested = _blueprint_schema()
    assert nested["$defs"] == original["$defs"]
    assert "$defs" not in nested["properties"]["blueprint"]
    assert nested["properties"]["blueprint"] == {
        key: value for key, value in original.items() if key != "$defs"
    }
    jsonschema.Draft202012Validator.check_schema(nested)
    jsonschema.Draft202012Validator(nested).validate(
        {
            "connection_id": "synthetic-connection",
            "operation_id": "schema-contract",
            "blueprint": deepcopy(_WIRE),
        }
    )
    nested["$defs"]["node"]["properties"]["type"]["enum"].append("FORBIDDEN")
    nested["properties"]["blueprint"]["properties"]["title"]["maxLength"] = 1
    assert BLUEPRINT_SCHEMA == original
    assert _blueprint_schema()["$defs"] == original["$defs"]
