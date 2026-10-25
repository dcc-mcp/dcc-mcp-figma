"""Bounded, request-correlated partial receipts without foreign error details."""

from __future__ import annotations

import re
from copy import deepcopy

_IDENTIFIER = re.compile(r"[A-Za-z0-9:;_-]{1,128}\Z")
_OPERATION = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_LISTS = {
    "created_node_ids",
    "collection_ids",
    "variable_ids",
    "component_set_ids",
    "root_ids",
}
_FIELDS = _LISTS | {
    "schema_version",
    "operation_id",
    "stage",
    "mutation_attempted",
    "completed_steps",
}
_STAGES = {"preflight", "fonts", "marker", "variables", "nodes", "variants", "complete", "read"}


def partial_receipt(value, operation_id):
    """Validate the complete receipt or discard it; never echo unknown fields.

    IDs are observations from this response, not permission to edit or replay.
    A transport failure without a response has no knowable partial receipt.
    """
    if not isinstance(operation_id, str) or not _OPERATION.fullmatch(operation_id):
        return None
    if not isinstance(value, dict) or set(value) != _FIELDS:
        return None
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        return None
    if (
        value["operation_id"] != operation_id
        or not isinstance(value["stage"], str)
        or value["stage"] not in _STAGES
    ):
        return None
    if type(value["mutation_attempted"]) is not bool:
        return None
    if type(value["completed_steps"]) is not int or not 0 <= value["completed_steps"] <= 100000:
        return None
    count = 0
    for key in _LISTS:
        items = value[key]
        if not isinstance(items, list) or len(items) > 2048:
            return None
        if any(not isinstance(item, str) or not _IDENTIFIER.fullmatch(item) for item in items):
            return None
        if len(set(items)) != len(items):
            return None
        count += len(items)
    if count > 4256:
        return None
    return deepcopy(value)
