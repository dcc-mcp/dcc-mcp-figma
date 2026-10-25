"""Automate approved native edits/export and a later reconnect readback.

This script never installs a plugin, obtains credentials, chooses another file,
or interprets reconnect alone as proof of cloud persistence or file reopening.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path

from dcc_mcp_figma.client import TrialError, discover, invoke, local_endpoint

_CREATED_FRAME = {"type": "FRAME", "name": "DCC-MCP Native Trial", "width": 320, "height": 180}
_EDITED_FRAME = {
    "type": "FRAME",
    "name": "DCC-MCP Native Trial Edited",
    "width": 360,
    "height": 180,
    "fill": "#00AA88",
}


def require(condition, message):
    if not condition:
        raise TrialError(message)


def require_node(node, expected):
    require(
        isinstance(node, dict) and all(node.get(key) == value for key, value in expected.items()),
        "The observed frame does not match the requested trial properties.",
    )


async def trial(args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    endpoint = local_endpoint(args.mcp_url)
    previous = None
    if args.phase == "reconnect-readback":
        require(args.evidence is not None, "Reconnect readback requires the previous native trial receipt.")
        previous = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
        require(
            previous.get("phase") == "write" and previous.get("native_effects") == "observed",
            "The previous receipt does not contain an observed native write phase.",
        )
        require_node(previous.get("node"), _EDITED_FRAME)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"phase": args.phase, "native_effects": "not_completed", "persistence": "unverified"}
    try:
        async with streamable_http_client(endpoint) as (read, write, _):  # noqa: SIM117 - Py3.7 source.
            async with ClientSession(read, write) as session:
                await session.initialize()
                catalogue = await discover(session)
                receipt["stage"] = "read_status"
                status = await invoke(session, catalogue, "figma_session__status", {})
                require(
                    status.get("state") == "paired",
                    "Pair the approved plugin in the selected test file first.",
                )
                connection = status["connection_id"]
                receipt["connection_id"] = connection
                receipt["stage"] = "read_page"
                page = await invoke(session, catalogue, "figma_document__read", {"connection_id": connection})
                receipt["document"] = page["document"]
                if previous is not None:
                    require(
                        connection != previous["connection_id"], "Readback requires a new plugin connection."
                    )
                    for field in ("name", "page_id", "marker"):
                        require(
                            page["document"][field] == previous["document"][field],
                            "The selected document/page marker does not match the previous trial.",
                        )
                    node_id = previous["node"]["id"]
                    expected_node = {"id": node_id, **_EDITED_FRAME}
                    receipt["expected_node"] = expected_node
                    receipt["stage"] = "reconnect_node_readback"
                    observed = await invoke(
                        session,
                        catalogue,
                        "figma_nodes__read",
                        {
                            "connection_id": connection,
                            "node_id": node_id,
                        },
                    )
                    require_node(observed["data"], expected_node)
                    require(
                        observed["data"] == previous["node"],
                        "The same node did not retain the expected state.",
                    )
                    receipt.update(node=observed["data"], reconnect_readback="passed")
                    receipt["persistence_note"] = (
                        "Marker and node state survived plugin reconnection. Same-file close/reopen and cloud-save "
                        "provenance still require the trusted host's independent evidence."
                    )
                else:
                    require(
                        page["data"].get("truncated") is False and page["data"].get("nodes") == [],
                        "Select an empty disposable page before the explicit write phase.",
                    )
                    receipt["stage"] = "create_frame"
                    created = await invoke(
                        session,
                        catalogue,
                        "figma_nodes__create_frame",
                        {
                            "connection_id": connection,
                            "name": "DCC-MCP Native Trial",
                            "width": 320,
                            "height": 180,
                        },
                    )
                    node_id = created["data"]["id"]
                    receipt.update(created_node=created["data"], document=created["document"])
                    receipt["stage"] = "verify_created_frame"
                    require_node(created["data"], _CREATED_FRAME)
                    expected_node = {"id": node_id, **_EDITED_FRAME}
                    receipt["expected_node"] = expected_node
                    receipt["stage"] = "update_frame"
                    edited = await invoke(
                        session,
                        catalogue,
                        "figma_nodes__update_frame",
                        {
                            "connection_id": connection,
                            "node_id": node_id,
                            "name": "DCC-MCP Native Trial Edited",
                            "width": 360,
                            "fill": "#00AA88",
                        },
                    )
                    receipt["edited_node"] = edited["data"]
                    receipt["stage"] = "verify_edited_frame"
                    require_node(edited["data"], expected_node)
                    receipt["stage"] = "read_edited_node"
                    observed = await invoke(
                        session,
                        catalogue,
                        "figma_nodes__read",
                        {
                            "connection_id": connection,
                            "node_id": node_id,
                        },
                    )
                    require_node(observed["data"], expected_node)
                    require(observed["data"] == edited["data"], "Readback did not match the edited node.")
                    receipt.update(document=observed["document"], node=observed["data"], artifacts=[])
                    for format_name in ("PNG", "SVG"):
                        receipt["stage"] = "export_" + format_name.lower()
                        exported = await invoke(
                            session,
                            catalogue,
                            "figma_nodes__export",
                            {
                                "connection_id": connection,
                                "node_id": node_id,
                                "format": format_name,
                            },
                        )
                        artifact = exported["data"]
                        raw = base64.b64decode(artifact["data_base64"], validate=True)
                        digest = hashlib.sha256(raw).hexdigest()
                        require(
                            len(raw) == artifact["byte_length"] and digest == artifact["sha256"],
                            "Export bytes did not match the observed length and hash.",
                        )
                        filename = "native-trial." + format_name.lower()
                        (output / filename).write_bytes(raw)
                        receipt["artifacts"].append({"file": filename, "sha256": digest, "bytes": len(raw)})
                receipt["native_effects"] = "observed"
                receipt["stage"] = "complete"
    except Exception:
        receipt["native_outcome"] = "indeterminate"
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcp-url", required=True)
    parser.add_argument("--phase", choices=("write", "reconnect-readback"), default="write")
    parser.add_argument("--evidence")
    parser.add_argument("--output-dir", required=True, help="A new private evidence directory.")
    args = parser.parse_args()
    try:
        result = asyncio.run(trial(args))
    except Exception:  # noqa: BLE001 - redact foreign SDK/transport exceptions at the CLI boundary.
        print(
            "Native trial stopped. Inspect private local evidence; never replay an uncertain mutation.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print(
        json.dumps(
            {
                "phase": result["phase"],
                "native_effects": result["native_effects"],
                "persistence": result["persistence"],
            }
        )
    )


if __name__ == "__main__":
    main()
