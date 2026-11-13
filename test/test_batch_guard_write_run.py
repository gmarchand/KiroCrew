"""The batch guard's write-then-run rule: on KAS, a shell command sent in the same
batch as a file write announced before it is refused while that write is open.

KAS starts a batch's calls in no fixed order, so the command can run before the
file it runs exists. It also asks one permission at a time, so the command
cannot be held until the write lands: the write's own request only comes once
the command's is answered. The frames below are KAS's real shapes (kiro-cli
3.3.0, ``kiro-cli acp --agent-engine v3``): the write's ``tool_call`` names no
tool, only ``kind: edit``; the command's permission names ``run_command``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from kiro_crew.acp import batch_guard
from kiro_crew.acp.types import JsonRpcMessage
from kiro_crew.constants import DENY_CAUSE_BATCH_WRITE_RUN

_SID = "s1"
_WRITE_ID = "toolu_write"
_RUN_ID = "run_command_toolu_run"
_COMMAND = "cd /tmp/w && python3 hello.py | tail -1"
_OPTIONS = [
    {"optionId": "accept", "name": "Allow", "kind": "allow_once"},
    {"optionId": "always-accept", "name": "Always allow", "kind": "allow_always"},
    {"optionId": "reject", "name": "Deny", "kind": "reject_once"},
    {"optionId": "always-reject", "name": "Always deny", "kind": "reject_always"},
]


def _update(update: dict) -> JsonRpcMessage:
    return JsonRpcMessage(method="session/update", params={"sessionId": _SID, "update": update})


def _write_call() -> JsonRpcMessage:
    return _update(
        {
            "sessionUpdate": "tool_call",
            "toolCallId": _WRITE_ID,
            "title": "Write File",
            "kind": "edit",
            "status": "in_progress",
            "rawInput": {"path": "/tmp/w/hello.py", "text": "print('ok')\n"},
            "locations": [{"path": "/tmp/w/hello.py"}],
            "_meta": {"kiro": {"toolOrigin": "default"}},
        }
    )


def _run_call() -> JsonRpcMessage:
    return _update(
        {
            "sessionUpdate": "tool_call",
            "toolCallId": _RUN_ID,
            "title": "Run hello.py",
            "kind": "execute",
            "status": "pending",
            "rawInput": {"command": _COMMAND, "description": "Run hello.py"},
            "_meta": {"kiro": {"toolOrigin": "default"}},
        }
    )


def _write_done() -> JsonRpcMessage:
    return _update(
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": _WRITE_ID,
            "status": "completed",
            "title": "Write File",
        }
    )


def _run_permission(request_id: int) -> JsonRpcMessage:
    return JsonRpcMessage(
        id=request_id,
        method="session/request_permission",
        params={
            "sessionId": _SID,
            "toolCall": {"toolCallId": _RUN_ID, "status": "pending", "title": _COMMAND},
            "options": _OPTIONS,
            "_meta": {"kiro": {"toolId": "run_command", "command": _COMMAND}},
        },
    )


def _handle(backend: str, monkeypatch):
    from kiro_crew.acp.session_handle import AcpSessionHandle

    monkeypatch.setattr(batch_guard, "guard_settings", lambda: (True, ()))
    runtime = MagicMock()
    runtime.acp_backend = backend
    runtime.send_response = AsyncMock()
    runtime.send_error = AsyncMock()
    handle = AcpSessionHandle(_SID, asyncio.Queue(), runtime)
    handle._batch_window.set_feeding(True)
    steered: list[str] = []

    async def _steer(text):
        steered.append(text)
        return True

    monkeypatch.setattr(handle, "steer", _steer, raising=False)
    monkeypatch.setattr(type(handle), "supports_refusal_steer", property(lambda self: True))
    return handle, steered


async def _approve_run(handle, frames) -> tuple[bool, str]:
    for frame in frames:
        handle._handle_update(frame)
    event = handle._build_permission_event(_run_permission(7))
    assert event is not None and event.is_shell
    approved = await handle.approve_tool(7)
    answer = handle._runtime.send_response.await_args.args[1]["outcome"]
    return approved, answer.get("optionId", "")


@pytest.mark.asyncio
async def test_kas_refuses_a_command_batched_after_an_open_write(monkeypatch):
    handle, steered = _handle("kas", monkeypatch)

    approved, option = await _approve_run(handle, [_write_call(), _run_call()])

    assert approved is False
    assert option == "reject"
    assert steered and "has not finished" in steered[0] and "next step" in steered[0]
    assert batch_guard.cause_for(batch_guard.WRITE_RUN_REFUSAL) == DENY_CAUSE_BATCH_WRITE_RUN


@pytest.mark.asyncio
async def test_kas_runs_the_command_once_the_write_has_finished(monkeypatch):
    handle, steered = _handle("kas", monkeypatch)

    approved, option = await _approve_run(handle, [_write_call(), _run_call(), _write_done()])

    assert (approved, option, steered) == (True, "accept", [])


@pytest.mark.asyncio
async def test_kas_runs_a_command_announced_before_the_write(monkeypatch):
    handle, steered = _handle("kas", monkeypatch)

    approved, option = await _approve_run(handle, [_run_call(), _write_call()])

    assert (approved, option, steered) == (True, "accept", [])


@pytest.mark.asyncio
async def test_a_backend_that_orders_its_calls_is_not_judged(monkeypatch):
    handle, steered = _handle("claude", monkeypatch)

    approved, option = await _approve_run(handle, [_write_call(), _run_call()])

    assert (approved, option, steered) == (True, "accept", [])
