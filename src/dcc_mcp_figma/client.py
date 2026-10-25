"""Bounded official-MCP client helpers for operator-approved native trials."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit

from .receipts import partial_receipt

NATIVE_TOOLS = {
    "figma_session__status",
    "figma_document__read",
    "figma_nodes__read",
    "figma_nodes__create_frame",
    "figma_nodes__update_frame",
    "figma_nodes__export",
    "figma_design__apply_blueprint",
    "figma_design__read_blueprint",
}


class TrialError(Exception):
    """Stable trial failures without private vendor payloads."""

    def __init__(self, message, *, receipt=None):
        super().__init__(message)
        self.receipt = receipt


def local_endpoint(url):
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.port
            and parsed.path == "/mcp"
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        )
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise TrialError("Use the existing loopback adapter MCP URL.")
    return url


async def discover(session):
    tools = {}
    cursor = None
    seen = set()
    for _ in range(10):
        page = await session.list_tools(cursor=cursor)
        for tool in page.tools:
            if tool.name in tools:
                raise TrialError("The live tool catalog contains duplicate names.")
            tools[tool.name] = tool
        cursor = page.nextCursor
        if cursor is None:
            if not NATIVE_TOOLS <= set(tools):
                raise TrialError("The adapter's complete native tool surface is unavailable.")
            return tools
        if cursor in seen:
            break
        seen.add(cursor)
    raise TrialError("The live tool catalog could not be read completely.")


def _observed_receipt(result, operation_id):
    if not isinstance(result, dict) or not isinstance(result.get("context"), dict):
        return None
    return partial_receipt(result["context"].get("partial_receipt"), operation_id)


def _structured(response, operation_id=None):
    if response.isError or not isinstance(response.structuredContent, dict):
        raise TrialError(
            "The adapter returned an error or no structured result; stop without replay.",
            receipt=_observed_receipt(response.structuredContent, operation_id),
        )
    return response.structuredContent


async def invoke(session, catalogue, name, arguments, *, timeout=45):
    """Call once; follow only the Core-owned job polling route, never replay."""
    if name not in NATIVE_TOOLS or name not in catalogue:
        raise TrialError("The requested native tool was not discovered.")
    operation_id = arguments.get("operation_id") if name == "figma_design__apply_blueprint" else None
    result = _structured(await session.call_tool(name, arguments), operation_id)
    if "job_id" in result:
        route = result.get("core_poll")
        if (
            not isinstance(route, dict)
            or route.get("owner") != "core"
            or route.get("tool") != "jobs_get_status"
            or route["tool"] not in catalogue
            or not isinstance(route.get("arguments"), dict)
            or route["arguments"].get("job_id") != result["job_id"]
            or set(route["arguments"]) - {"job_id", "include_result", "include_logs"}
        ):
            raise TrialError("The adapter did not provide a valid Core job polling route.")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = _structured(await session.call_tool(route["tool"], route["arguments"]), operation_id)
            if state.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
                if state["status"] != "completed" or not isinstance(state.get("result"), dict):
                    raise TrialError(
                        "The Core job did not complete successfully; stop without replay.",
                        receipt=_observed_receipt(state.get("result"), operation_id),
                    )
                result = state["result"]
                break
            await asyncio.sleep(0.1)
        else:
            raise TrialError(
                "Core job polling expired; native outcome is indeterminate and must not be replayed."
            )
    if result.get("success") is not True or not isinstance(result.get("context"), dict):
        raise TrialError(
            "The native operation did not return a successful structured envelope.",
            receipt=_observed_receipt(result, operation_id),
        )
    return result["context"]
