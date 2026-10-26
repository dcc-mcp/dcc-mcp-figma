"""Pure compiler/graph/asset contracts; all designs and IDs are synthetic."""

import base64
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

import dcc_mcp_figma.blueprint as module
from dcc_mcp_figma.blueprint import (
    BlueprintError,
    blueprint_digest,
    blueprint_stats,
    compilation_report,
    compile_blueprint,
    normalize_path,
    validate_blueprint,
)


def source_design():
    face = {"family": "Noto Sans SC", "style": "Regular", "weight": 400}
    label = {
        "id": "component/field/label",
        "type": "TEXT",
        "bounds": {"x": 8, "y": 8, "width": 84, "height": 24},
        "text": "Synthetic field",
        "font": face,
        "font_size": 14,
        "line_height": 24,
        "align": "left",
        "text_style": "label",
        "text_style_ref": "text-style/label",
        "fill": "ink",
        "slot": "label",
    }
    background = {
        "id": "component/field/background",
        "type": "VECTOR",
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 40},
        "geometry": {"kind": "rect", "radius": 8},
        "fill": "ink",
        "variable_bindings": {"fill": "variable/ink", "cornerRadius": "variable/radius"},
    }
    component = {
        "id": "component/field",
        "type": "COMPONENT",
        "bounds": {"x": 0, "y": 0, "width": 100, "height": 40},
        "component_set_id": None,
        "variant_properties": {},
        "children": [background, label],
    }
    instance = {
        "id": "screen/field",
        "type": "INSTANCE",
        "bounds": {"x": 20, "y": 20, "width": 100, "height": 40},
        "component_ref": "component/field",
        "overrides": {"label": {"text": "Synthetic override"}},
        "auto_layout": "INHERIT_COMPONENT",
    }
    screen = {
        "id": "screen/default",
        "type": "FRAME",
        "bounds": {"x": 0, "y": 0, "width": 200, "height": 100},
        "children": [instance],
    }
    return {
        "schema_version": 1,
        "title": "Synthetic compiler contract",
        "node_trees": [component, screen],
        "assets": [],
        "component_sets": [],
        "text_styles": [
            {
                "id": "text-style/label",
                "family": "Noto Sans SC",
                "style": "Regular",
                "font_size": 14,
                "line_height": 24,
            }
        ],
        "variables": {
            "collection": {
                "id": "variables/synthetic",
                "default_mode_ref": "mode/default",
                "modes": [{"id": "mode/default", "name": "Default"}],
            },
            "items": [
                {
                    "id": "variable/ink",
                    "name": "ink",
                    "resolved_type": "COLOR",
                    "collection_ref": "variables/synthetic",
                    "values_by_mode": {"mode/default": {"r": 0.1, "g": 0.2, "b": 0.3, "a": 1}},
                },
                {
                    "id": "variable/radius",
                    "name": "radius",
                    "resolved_type": "FLOAT",
                    "collection_ref": "variables/synthetic",
                    "values_by_mode": {"mode/default": 8},
                },
            ],
        },
    }


def wire_design():
    return compile_blueprint(source_design())


def test_compiler_projects_whole_graph_and_inlines_typography_without_authority():
    source = source_design()
    source["security"] = {"approved": True, "token": "synthetic-private-not-authority"}
    source["native_execution"] = "synthetic-untrusted-claim"
    original = deepcopy(source)
    wire = compile_blueprint(source)
    assert source == original
    assert set(wire) == {"schema_version", "title", "assets", "variables", "component_sets", "node_trees"}
    assert wire["node_trees"][0]["children"][0]["type"] == "RECTANGLE"
    label = wire["node_trees"][0]["children"][1]
    assert label["characters"] == "Synthetic field" and label["font"] == {
        "family": "Noto Sans SC",
        "style": "Regular",
    }
    instance = wire["node_trees"][1]["children"][0]
    assert instance["overrides"] == [
        {"target_key": "component/field/label", "characters": "Synthetic override"}
    ]
    report = compilation_report(source, wire)
    assert report["projections"]["text_styles_inlined"] == 1
    assert report["projections"]["native_text_style_assets_created"] is False
    assert "synthetic-private" not in json.dumps(wire) + json.dumps(report)
    copied = validate_blueprint(wire)
    copied["node_trees"][0]["name"] = "Changed copy"
    assert wire["node_trees"][0]["name"] != "Changed copy"
    assert blueprint_digest(wire) == blueprint_digest(json.loads(json.dumps(wire)))


def test_standalone_component_annotation_projection_is_explicit():
    source = source_design()
    source["node_trees"][0]["variant_properties"] = {"viewport": "desktop"}
    wire = compile_blueprint(source)
    assert wire["node_trees"][0]["variant_properties"] == {}
    assert compilation_report(source, wire)["projections"]["standalone_component_annotations_removed"] == [
        "component/field"
    ]


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -1, 0, 0.001, 0.009])
def test_invalid_numeric_dimensions_reject_before_host_dispatch(value):
    wire = wire_design()
    wire["node_trees"][1]["bounds"]["width"] = value
    with pytest.raises(BlueprintError):
        validate_blueprint(wire)


def test_figma_minimum_resize_dimension_is_accepted():
    wire = wire_design()
    wire["node_trees"][1]["bounds"]["width"] = 0.01
    assert validate_blueprint(wire)["node_trees"][1]["bounds"]["width"] == 0.01


@pytest.mark.parametrize("paint", ["fill", "stroke"])
@pytest.mark.parametrize("missing", [False, True])
def test_bound_paint_requires_a_present_solid_paint(paint, missing):
    wire = wire_design()
    node = wire["node_trees"][0]["children"][0]
    node["variable_bindings"][paint] = "variable/ink"
    node[paint] = None
    if missing:
        node.pop(paint)
    with pytest.raises(BlueprintError):
        validate_blueprint(wire)


def test_text_cannot_bind_a_rectangle_corner_radius():
    wire = wire_design()
    wire["node_trees"][0]["children"][1]["variable_bindings"] = {"cornerRadius": "variable/radius"}
    with pytest.raises(BlueprintError):
        validate_blueprint(wire)


@pytest.mark.parametrize("field", ["key", "mode_key"])
def test_collection_and_mode_keys_cannot_collide_with_node_keys(field):
    wire = wire_design()
    wire["variables"]["collection"][field] = wire["node_trees"][0]["key"]
    with pytest.raises(BlueprintError):
        validate_blueprint(wire)


@pytest.mark.parametrize("width,height", [(64, 8), (16, 16)])
def test_vector_intrinsic_curve_extrema_must_match_declared_bounds(width, height):
    wire = wire_design()
    wire["node_trees"][1]["children"].append(
        {
            "key": "vector/curve",
            "type": "VECTOR",
            "name": "Curve",
            "visible": True,
            "opacity": 1,
            "bounds": {"x": 0, "y": 0, "width": width, "height": height},
            "paths": [{"windingRule": "NONZERO", "data": "M 0 0 Q 8 16 16 0"}],
        }
    )
    with pytest.raises(BlueprintError):
        validate_blueprint(wire)


@pytest.mark.parametrize("axis", ["layoutSizingHorizontal", "layoutSizingVertical"])
def test_intrinsic_vector_rejects_fill_even_with_valid_auto_layout_parent(axis):
    wire = wire_design()
    frame = wire["node_trees"][1]
    frame["auto_layout"] = {
        "mode": "HORIZONTAL",
        "item_spacing": 0,
        "padding": [0, 0, 0, 0],
        "primary_axis_sizing": "FIXED",
        "counter_axis_sizing": "FIXED",
        "primary_axis_align": "MIN",
        "counter_axis_align": "MIN",
    }
    vector = {
        "key": "vector/curve",
        "type": "VECTOR",
        "name": "Curve",
        "visible": True,
        "opacity": 1,
        "bounds": {"x": 0, "y": 0, "width": 16, "height": 8},
        "paths": [{"windingRule": "NONZERO", "data": "M 0 0 Q 8 16 16 0"}],
    }
    frame["children"].append(vector)
    validate_blueprint(wire)
    vector[axis] = "FILL"
    with pytest.raises(BlueprintError):
        validate_blueprint(wire)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda w: w.update(security={"approved": True}),
        lambda w: w["node_trees"][0].update(script="synthetic code is never evaluated"),
        lambda w: w["node_trees"][0]["children"][1].update(paths=[]),
        lambda w: w["node_trees"][0]["children"][0]["variable_bindings"].update(fill="variable/radius"),
        lambda w: w["variables"]["collection"].update(mode_name="Second"),
        lambda w: w["variables"]["items"][1].update(value=True),
        lambda w: w["node_trees"][1]["children"][0].update(component_ref="component/missing"),
        lambda w: w["node_trees"][1]["children"][0]["overrides"][0].update(target_key="outside/template"),
        lambda w: w["node_trees"][0]["children"][1].update(layoutSizingHorizontal="FILL"),
    ],
)
def test_closed_fields_refs_types_and_fill_parent_are_enforced(mutation):
    wire = wire_design()
    mutation(wire)
    with pytest.raises(BlueprintError):
        validate_blueprint(wire)


def test_duplicate_keys_and_recursive_components_fail_closed():
    wire = wire_design()
    wire["node_trees"][1]["key"] = wire["node_trees"][0]["key"]
    with pytest.raises(BlueprintError):
        validate_blueprint(wire)
    wire = wire_design()
    instance = deepcopy(wire["node_trees"][1]["children"][0])
    instance["key"] = "component/field/cycle"
    instance["overrides"] = []
    wire["node_trees"][0]["children"].append(instance)
    with pytest.raises(BlueprintError):
        validate_blueprint(wire)


def test_instance_expansion_counts_clone_children_and_stops_at_global_budget():
    wire = wire_design()
    component = wire["node_trees"][0]
    component["children"] = [
        {**deepcopy(component["children"][0]), "key": "component/field/shape" + str(i)} for i in range(100)
    ]
    template = wire["node_trees"][1]["children"][0]
    template["overrides"] = []
    wire["node_trees"][1]["children"] = [
        {**deepcopy(template), "key": "screen/instance" + str(i)} for i in range(40)
    ]
    with pytest.raises(BlueprintError, match="^node_budget_exceeded$"):
        validate_blueprint(wire)


def test_outer_run_is_included_in_depth_limit():
    wire = wire_design()
    leaf = wire["node_trees"][1]
    leaf["children"] = []
    for index in range(24):
        leaf = {**deepcopy(leaf), "key": "depth/" + str(index), "children": [leaf]}
    wire["node_trees"] = [leaf]
    with pytest.raises(BlueprintError, match="^depth_exceeded$"):
        validate_blueprint(wire)


@pytest.mark.parametrize("raw", ["m1 2 h3 v4 l-1 -2z", "M 2 12 a 10 10 0 0 1 20 0", "M0 0 q2 3 4 0 t4 0"])
def test_paths_are_canonical_absolute_and_idempotent(raw):
    normalized = normalize_path(raw)
    assert normalize_path(normalized) == normalized
    assert not any(command in normalized for command in "mlhvcsqtazAHVST")
    assert normalized.startswith("M ")


@pytest.mark.parametrize(
    "raw", ["javascript:synthetic", "M0 0 Lnan 1", "M0 0 A1 1 0 2 0 2 2", "M0 0 L1e999 1", "L 1 1"]
)
def test_invalid_vector_payloads_are_not_interpreted(raw):
    with pytest.raises(BlueprintError):
        normalize_path(raw)


def test_lucide_paths_keep_viewbox_wrapper_round_strokes_and_resolved_override_key():
    source = source_design()
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m2 12 h20 a10 10 0 0 1 -20 0"/></svg>'
    source["assets"] = [
        {
            "id": "icon/synthetic",
            "kind": "VECTOR_SVG",
            "svg": svg,
            "sha256": hashlib.sha256(svg.encode()).hexdigest(),
        }
    ]
    icon = {
        "id": "component/field/icon",
        "type": "VECTOR",
        "bounds": {"x": 70, "y": 8, "width": 24, "height": 24},
        "geometry": {"kind": "lucide", "asset_ref": "icon/synthetic", "asset": "synthetic"},
        "stroke": "ink",
        "stroke_width": 2,
        "fill": None,
        "slot": "eye",
    }
    source["node_trees"][0]["children"].append(icon)
    source["node_trees"][1]["children"][0]["overrides"]["eye"] = {"visible": False}
    wire = compile_blueprint(source)
    wrapper = wire["node_trees"][0]["children"][-1]
    assert wrapper["type"] == "FRAME" and wrapper["bounds"] == icon["bounds"]
    vector = wrapper["children"][0]
    assert vector["type"] == "VECTOR" and vector["stroke_cap"] == vector["stroke_join"] == "ROUND"
    assert "C " in vector["paths"][0]["data"] and "A " not in vector["paths"][0]["data"]
    assert wire["assets"] == []
    assert wire["node_trees"][1]["children"][0]["overrides"][-1] == {
        "target_key": icon["id"],
        "visible": False,
    }


@pytest.mark.parametrize(
    "svg",
    [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><script>synthetic</script></svg>',
        '<!DOCTYPE svg [<!ENTITY x "synthetic">]><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"/>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><image href="https://untrusted.invalid/image"/></svg>',
    ],
)
def test_svg_executable_and_remote_surfaces_are_rejected(svg):
    source = source_design()
    source["assets"] = [
        {
            "id": "icon/synthetic",
            "kind": "VECTOR_SVG",
            "svg": svg,
            "sha256": hashlib.sha256(svg.encode()).hexdigest(),
        }
    ]
    with pytest.raises(BlueprintError):
        compile_blueprint(source)


def test_png_asset_hash_dimensions_and_aggregate_bytes_are_checked(monkeypatch):
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j2P0AAAAASUVORK5CYII="
    )
    asset = {
        "key": "asset/synthetic",
        "mime_type": "image/png",
        "data_base64": base64.b64encode(raw).decode(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "width": 1,
        "height": 1,
    }
    wire = wire_design()
    wire["assets"] = [asset]
    assert validate_blueprint(wire)["assets"][0] == asset
    broken = deepcopy(wire)
    broken["assets"][0]["sha256"] = "0" * 64
    with pytest.raises(BlueprintError):
        validate_blueprint(broken)
    broken = deepcopy(wire)
    broken["assets"][0]["width"] = 2
    with pytest.raises(BlueprintError):
        validate_blueprint(broken)
    monkeypatch.setattr(module, "MAX_DECODED_IMAGE_BYTES", 1)
    with pytest.raises(BlueprintError, match="^blueprint_too_large$"):
        validate_blueprint(wire)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("width", -1),
        ("width", 0),
        ("width", 0.009),
        ("width", 8192.01),
        ("height", -1),
        ("height", 0),
        ("height", 0.009),
        ("height", 8192.01),
        ("strokeWeight", -0.01),
        ("strokeWeight", 128.01),
        ("cornerRadius", -0.01),
        ("cornerRadius", 4096.01),
    ],
)
def test_bound_numeric_variables_are_rejected_outside_the_target_field_range(field, value):
    wire = wire_design()
    wire["variables"]["items"][1]["value"] = value
    rectangle = wire["node_trees"][0]["children"][0]
    rectangle["variable_bindings"] = {field: "variable/radius"}
    original = deepcopy(wire)
    with pytest.raises(BlueprintError, match="^invalid_blueprint$"):
        validate_blueprint(wire)
    assert wire == original


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("width", 0.01),
        ("width", 8192),
        ("height", 0.01),
        ("height", 8192),
        ("strokeWeight", 0),
        ("strokeWeight", 128),
        ("cornerRadius", 0),
        ("cornerRadius", 4096),
    ],
)
def test_bound_numeric_variables_accept_the_exact_field_boundaries(field, value):
    wire = wire_design()
    wire["variables"]["items"][1]["value"] = value
    wire["node_trees"][0]["children"][0]["variable_bindings"] = {field: "variable/radius"}
    assert validate_blueprint(wire) == wire


def test_unused_negative_float_remains_valid_without_becoming_a_size_or_stroke():
    wire = wire_design()
    wire["variables"]["items"][1]["value"] = -100
    wire["node_trees"][0]["children"][0]["variable_bindings"] = {"fill": "variable/ink"}
    assert validate_blueprint(wire) == wire


def test_zero_extent_vector_cannot_gain_a_dimension_binding():
    wire = wire_design()
    wire["node_trees"][0]["children"].append(
        {
            "key": "component/vertical",
            "type": "VECTOR",
            "name": "Synthetic vertical line",
            "bounds": {"x": 0, "y": 0, "width": 0, "height": 10},
            "visible": True,
            "opacity": 1,
            "paths": [{"windingRule": "NONZERO", "data": "M 0 0 L 0 10"}],
            "variable_bindings": {"width": "variable/radius"},
        }
    )
    with pytest.raises(BlueprintError, match="^invalid_blueprint$"):
        validate_blueprint(wire)


def test_compiler_cli_writes_only_fresh_artifacts_and_keeps_input_unchanged(tmp_path, capsys):
    path = Path(__file__).resolve().parents[1] / "scripts/compile_login_blueprint.py"
    spec = importlib.util.spec_from_file_location("blueprint_compile_cli", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    source = tmp_path / "synthetic-source.json"
    original = json.dumps(source_design()).encode()
    source.write_bytes(original)
    output = tmp_path / "compiled"
    assert cli.main(["--source", str(source), "--output-dir", str(output)]) == 0
    summary = json.loads(capsys.readouterr().out)
    wire = json.loads((output / "wire.json").read_text(encoding="utf-8"))
    assert (
        hashlib.sha256((output / "wire.json").read_bytes()).hexdigest()
        == summary["wire_sha256"]
        == blueprint_digest(wire)
    )
    assert json.loads((output / "compiler-report.json").read_text())["native_execution"] == "NOT_RUN"
    assert blueprint_stats(wire)["screen_roots"] == 1
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    assert cli.main(["--source", str(source), "--output-dir", str(output)]) == 2
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}
    assert source.read_bytes() == original
