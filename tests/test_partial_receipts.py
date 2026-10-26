"""Synthetic response evidence is preserved only for its exact dispatched apply."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest
from dcc_mcp_core import ReverseBridgeSession

from dcc_mcp_figma.binding import BindingError, FigmaBinding
from dcc_mcp_figma.receipts import partial_receipt


def receipt():
    return {
        "schema_version": 1,
        "operation_id": "synthetic_apply_001",
        "stage": "nodes",
        "mutation_attempted": True,
        "completed_steps": 7,
        "created_node_ids": ["3:4"],
        "collection_ids": ["VariableCollectionId:3:1"],
        "variable_ids": ["VariableID:3:2"],
        "component_set_ids": [],
        "root_ids": ["3:4"],
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"operation_id": "foreign_operation"},
        {"stage": []},
        {"stage": "secret-error-details"},
        {"schema_version": True},
        {"mutation_attempted": 1},
        {"completed_steps": True},
        {"created_node_ids": ["3:4", "3:4"]},
        {"created_node_ids": ["../private/path"]},
        {"created_node_ids": [str(i) for i in range(2049)]},
        {"token": "synthetic-private-token"},
    ],
)
def test_malformed_receipts_are_discarded_whole(changes):
    value = {**receipt(), **changes}
    assert partial_receipt(value, "synthetic_apply_001") is None


def test_receipt_is_a_copy_and_never_grants_replay_or_persistence():
    value = receipt()
    observed = partial_receipt(value, "synthetic_apply_001")
    assert observed == value
    observed["created_node_ids"].append("5:6")
    assert value["created_node_ids"] == ["3:4"]
    assert partial_receipt(value, None) is None
    assert partial_receipt(value, []) is None


@pytest.mark.parametrize("reconnect", [False, True])
@pytest.mark.parametrize("matching_operation", [False, True])
def test_correlated_receipt_survives_connection_loss_after_core_response(reconnect, matching_operation):
    document = {"name": "Fixture", "page_id": "1:2", "page_name": "Fixture", "marker": None}
    current = []

    class Session:
        def __init__(self, **options):
            self.core = ReverseBridgeSession(**options)

        def __getattr__(self, name):
            return getattr(self.core, name)

        def call(self, *args, **kwargs):
            result = self.core.call(*args, **kwargs)
            # Deterministic handoff after Core accepted the correlated response,
            # before FigmaBinding can inspect it. This does not call a real host.
            binding.close()
            if reconnect:
                current.append(binding.connect("synthetic_plugin_instance_0002", document)["connection_id"])
            return result

    binding = FigmaBinding("synthetic-pairing-token-0000000000000001", timeout=2, session_factory=Session)
    connection = binding.connect("synthetic_plugin_instance_0001", document)["connection_id"]
    reported = receipt()
    if not matching_operation:
        reported["operation_id"] = "foreign_operation"
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                binding.call, connection, "design.blueprint.apply", {"operation_id": "synthetic_apply_001"}
            )
            request = binding.poll(connection, timeout=1)["request"]
            binding.respond(
                connection, request["id"], {"ok": False, "error": "host_error", "receipt": reported}
            )
            with pytest.raises(BindingError) as caught:
                future.result(timeout=1)
        assert caught.value.code == ("stale_connection" if reconnect else "not_paired")
        assert caught.value.dispatched is True
        assert caught.value.receipt == (receipt() if matching_operation else None)
        if reconnect:
            assert binding.status()["state"] == "paired"
            assert binding.status()["connection_id"] == current[0]
    finally:
        binding.close()


def test_actual_core_failure_closes_binding_and_keeps_correlated_known_ids():
    binding = FigmaBinding("synthetic-pairing-token-0000000000000001", timeout=2)
    document = {"name": "Fixture", "page_id": "1:2", "page_name": "Fixture", "marker": None}
    connection = binding.connect("synthetic_plugin_instance_0001", document)["connection_id"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            future = pool.submit(
                binding.call,
                connection,
                "design.blueprint.apply",
                {"operation_id": "synthetic_apply_001", "blueprint": {}},
            )
            request = binding.poll(connection, timeout=1)["request"]
            failure = {"ok": False, "error": "host_error", "receipt": receipt()}
            binding.respond(connection, request["id"], failure)
            with pytest.raises(BindingError) as caught:
                future.result(timeout=1)
            assert caught.value.dispatched is True
            assert caught.value.receipt == receipt()
            assert binding.status()["state"] == "unavailable"
            assert binding.status()["document"] is None
            with pytest.raises(BindingError, match="not_paired"):
                binding.call(connection, "design.blueprint.apply", {})
            assert "token" not in json.dumps(caught.value.receipt)
        finally:
            binding.close()


def test_foreign_error_data_is_not_a_partial_receipt():
    value = deepcopy(receipt())
    value["operation_id"] = "foreign"
    assert partial_receipt(value, "synthetic_apply_001") is None


@pytest.mark.parametrize("failure", ["marker", "page", "document"])
def test_reported_ids_survive_a_later_document_scope_response_failure(failure):
    binding = FigmaBinding("synthetic-pairing-token-0000000000000001", timeout=2)
    document = {"name": "Fixture", "page_id": "1:2", "page_name": "Fixture", "marker": None}
    connection = binding.connect("synthetic_plugin_instance_0001", document)["connection_id"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            future = pool.submit(
                binding.call, connection, "design.blueprint.apply", {"operation_id": "synthetic_apply_001"}
            )
            request = binding.poll(connection, timeout=1)["request"]
            result = {"ok": True, "document": deepcopy(document), "data": {"receipt": receipt()}}
            if failure == "page":
                result["document"]["page_id"] = "9:9"
            elif failure == "document":
                result["document"] = None
            binding.respond(connection, request["id"], result)
            with pytest.raises(BindingError) as caught:
                future.result(timeout=1)
            assert caught.value.receipt == receipt()
            assert binding.status()["state"] == "unavailable"
            assert binding.invalidate_response(connection) is False
        finally:
            binding.close()


def test_response_invalidation_never_closes_a_new_connection():
    binding = FigmaBinding("synthetic-pairing-token-0000000000000001")
    document = {"name": "Fixture", "page_id": "1:2", "page_name": "Fixture", "marker": None}
    previous = binding.connect("synthetic_plugin_instance_0001", document)["connection_id"]
    binding.disconnect(previous)
    current = binding.connect("synthetic_plugin_instance_0001", document)["connection_id"]
    try:
        assert binding.invalidate_response(previous) is False
        assert binding.status()["connection_id"] == current
        assert binding.invalidate_response(current) is True
        assert binding.status()["state"] == "unavailable"
    finally:
        binding.close()


def test_malformed_success_keeps_reported_receipt_and_stops_the_exact_binding():
    from dcc_mcp_figma.tools import FigmaTools

    wire = json.loads(
        (Path(__file__).parent / "support" / "blueprint_fixture.json").read_text(encoding="utf-8")
    )
    binding = FigmaBinding("synthetic-pairing-token-0000000000000001", timeout=2)
    document = {"name": "Fixture", "page_id": "1:2", "page_name": "Fixture", "marker": None}
    connection = binding.connect("synthetic_plugin_instance_0001", document)["connection_id"]
    progress = receipt()
    progress.update(stage="complete", collection_ids=[], variable_ids=[])
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            future = pool.submit(
                FigmaTools(binding).invoke,
                "figma_design__apply_blueprint",
                {
                    "connection_id": connection,
                    "operation_id": "synthetic_apply_001",
                    "blueprint": wire,
                },
            )
            request = binding.poll(connection, timeout=1)["request"]
            data = {
                "receipt": progress,
                "nodes": {},
                "collections": {},
                "variables": {},
                "component_sets": {},
                "roots": ["3:4"],
                "run_root_id": "3:4",
                "expanded_node_count": 1,
            }
            binding.respond(
                connection,
                request["id"],
                {
                    "ok": True,
                    "document": {**document, "marker": "synthetic_marker_001"},
                    "data": data,
                },
            )
            result = future.result(timeout=1)
            assert result["success"] is False and result["error"] == "invalid_response"
            assert result["context"]["partial_receipt"] == progress
            assert result["context"]["outcome"] == "indeterminate"
            assert binding.status()["state"] == "unavailable"
        finally:
            binding.close()
