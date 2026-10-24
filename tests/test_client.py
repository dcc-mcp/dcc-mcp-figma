"""Native-trial client contracts; fixtures are not real Figma results."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from dcc_mcp_figma.client import NATIVE_TOOLS, TrialError, invoke, local_endpoint


class SyntheticSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, deepcopy(arguments)))
        return SimpleNamespace(isError=False, structuredContent=next(self.responses))


def pending():
    return {
        "job_id": "synthetic-job",
        "status": "pending",
        "core_poll": {
            "owner": "core",
            "tool": "jobs_get_status",
            "arguments": {"job_id": "synthetic-job", "include_result": True},
        },
    }


@pytest.mark.parametrize("status,success", [("completed", False), ("failed", True), ("cancelled", True)])
def test_terminal_state_alone_does_not_certify_an_operation(status, success):
    session = SyntheticSession([pending(), {"status": status, "result": {"success": success, "context": {}}}])
    with pytest.raises(TrialError):
        asyncio.run(invoke(session, NATIVE_TOOLS | {"jobs_get_status"}, "figma_nodes__export", {}))
    assert [name for name, _ in session.calls] == ["figma_nodes__export", "jobs_get_status"]


def test_successful_core_job_returns_inner_result_without_replaying_native_call():
    session = SyntheticSession(
        [
            pending(),
            {
                "status": "completed",
                "result": {
                    "success": True,
                    "context": {"synthetic": True, "persistence": "unverified"},
                },
            },
        ]
    )
    result = asyncio.run(invoke(session, NATIVE_TOOLS | {"jobs_get_status"}, "figma_nodes__export", {}))
    assert result == {"synthetic": True, "persistence": "unverified"}
    assert len(session.calls) == 2


def test_unexpected_polling_tool_is_not_called():
    value = pending()
    value["core_poll"]["tool"] = "register_tool"
    session = SyntheticSession([value])
    with pytest.raises(TrialError):
        asyncio.run(invoke(session, NATIVE_TOOLS | {"register_tool"}, "figma_nodes__export", {}))
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:1/mcp",
        "http://example.com/mcp",
        "http://127.0.0.1/mcp",
        "http://secret@127.0.0.1:9/mcp",
        "http://127.0.0.1:9/mcp?token=secret",
        "http://127.0.0.1:bad/mcp",
    ],
)
def test_trial_does_not_create_remote_or_credential_bearing_connections(url):
    with pytest.raises(TrialError) as error:
        local_endpoint(url)
    assert "secret" not in str(error.value)
