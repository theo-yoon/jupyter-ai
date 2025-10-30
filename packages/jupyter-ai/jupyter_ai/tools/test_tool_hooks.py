from __future__ import annotations

import asyncio

import pytest

from .tool_hooks import (
    PreHookContext,
    _ToolCallSpec,
    _auto_resolve_kwargs,
)


def test_auto_resolve_kwargs_prefers_namespaced_state():
    def sample_tool(path: str, index: int, entry_id: str) -> None:
        return None

    ctx = PreHookContext(
        entry_id="entry-1",
        tool_name="parent_tool",
        entry_metadata={},
        arguments={},
        namespace={},
    )
    ctx.state["path"] = "foo.ipynb"
    ctx.state["index"] = 1
    ctx.state["sample_tool.index"] = 42

    kwargs = _auto_resolve_kwargs(ctx, sample_tool, tool_key="sample_tool")

    assert kwargs["path"] == "foo.ipynb"
    assert kwargs["index"] == 42
    assert kwargs["entry_id"] == "entry-1"


def test_tool_call_spec_auto_resolve_stores_result():
    async def sample_tool(path: str, entry_id: str, index: int | None = None) -> dict[str, str | int | None]:
        return {"path": path, "entry_id": entry_id, "index": index}

    namespace = {"sample_tool": sample_tool}
    ctx = PreHookContext(
        entry_id="entry-5",
        tool_name="parent_tool",
        entry_metadata={},
        arguments={},
        namespace=namespace,
    )
    ctx.state["path"] = "bar.ipynb"
    ctx.state["sample_tool.index"] = 7

    spec = _ToolCallSpec("sample_tool", None, auto_resolve=True)
    asyncio.run(spec(ctx))

    stored = ctx.state["sample_tool.result"]
    assert stored["path"] == "bar.ipynb"
    assert stored["entry_id"] == "entry-5"
    assert stored["index"] == 7


def test_auto_resolve_kwargs_missing_required_raises():
    def needs_path(path: str) -> None:
        return None

    ctx = PreHookContext(
        entry_id="entry-9",
        tool_name="parent_tool",
        entry_metadata={},
        arguments={},
        namespace={},
    )

    with pytest.raises(RuntimeError):
        _auto_resolve_kwargs(ctx, needs_path, tool_key="needs_path")
