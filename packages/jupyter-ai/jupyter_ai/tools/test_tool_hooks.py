from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from .tool_hooks import (
    PreHookContext,
    PostSuccessHookContext,
    _ToolCallSpec,
    _auto_resolve_kwargs,
    register_context_provider,
    register_tool_alias,
    tool_argument_hints,
)


def test_auto_resolve_kwargs_prefers_namespaced_state():
    def sample_tool(path: str, index: int, entry_id: str) -> None:
        return None

    ctx = PreHookContext(
        entry_id="entry-1",
        tool_name="parent_tool",
        entry_metadata={},
        arguments={},
        namespace={"sample_tool": sample_tool},
    )
    ctx.state["path"] = "foo.ipynb"
    ctx.state["index"] = 1
    ctx.state["sample_tool.index"] = 42

    kwargs = _auto_resolve_kwargs(ctx, sample_tool, tool_key="sample_tool")

    assert kwargs["path"] == "foo.ipynb"
    assert kwargs["index"] == 42
    assert kwargs["entry_id"] == "entry-1"


def test_tool_call_spec_auto_resolve_stores_result():
    def sample_tool(path: str, entry_id: str, index: int | None = None) -> dict[str, str | int | None]:
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


def test_tool_call_spec_uses_result_mapping_from_json():
    captured: dict[str, Any] = {}

    def select_notebook_cell_command(
        *,
        path: str,
        cell_id: str | None = None,
        index: int | None = None,
        entry_id: str | None = None,
    ) -> dict[str, Any]:
        captured.update(path=path, cell_id=cell_id, index=index, entry_id=entry_id)
        return {"status": "ok"}

    namespace = {"select_notebook_cell_command": select_notebook_cell_command}
    result_payload = {"path": "foo.ipynb", "cell_id": "cell-3", "index": 2}
    ctx = PostSuccessHookContext(
        entry_id="entry-7",
        tool_name="update_notebook_cell",
        entry_metadata={},
        node_metadata={},
        result=json.dumps(result_payload),
        namespace=namespace,
    )

    spec = _ToolCallSpec("select_notebook_cell_command", None, auto_resolve=True)
    asyncio.run(spec(ctx))

    assert captured["path"] == "foo.ipynb"
    assert captured["cell_id"] == "cell-3"
    assert captured["index"] == 2
    assert captured["entry_id"] == "entry-7"
    assert ctx.state["select_notebook_cell_command.result"]["status"] == "ok"


def test_auto_resolve_expected_source_alias_from_tool_arguments():
    captured: dict[str, Any] = {}

    def run_notebook_cell_command(
        *,
        path: str,
        expected_source: str | None = None,
        entry_id: str | None = None,
    ) -> dict[str, Any]:
        captured.update(path=path, expected_source=expected_source, entry_id=entry_id)
        return {"status": "run"}

    namespace = {"run_notebook_cell_command": run_notebook_cell_command}
    ctx = PostSuccessHookContext(
        entry_id="entry-11",
        tool_name="update_notebook_cell",
        entry_metadata={"tool_arguments": {"path": "foo.ipynb", "source": "print('hi')"}},
        node_metadata={},
        result={"path": "foo.ipynb"},
        namespace=namespace,
    )

    spec = _ToolCallSpec("run_notebook_cell_command", None, auto_resolve=True)
    asyncio.run(spec(ctx))

    assert captured["path"] == "foo.ipynb"
    assert captured["expected_source"] == "print('hi')"
    assert captured["entry_id"] == "entry-11"


def test_auto_resolve_kwargs_missing_required_raises():
    def needs_path(path: str) -> None:
        return None

    ctx = PreHookContext(
        entry_id="entry-9",
        tool_name="parent_tool",
        entry_metadata={},
        arguments={},
        namespace={"needs_path": needs_path},
    )

    with pytest.raises(RuntimeError):
        _auto_resolve_kwargs(ctx, needs_path, tool_key="needs_path")


def test_register_tool_alias_extends_resolution():
    register_tool_alias("cell_id", "customCellId")
    captured: dict[str, Any] = {}

    def select_cell(*, cell_id: str | None = None) -> dict[str, Any]:
        captured["cell_id"] = cell_id
        return {"status": "ok"}

    namespace = {"select_cell": select_cell}
    ctx = PostSuccessHookContext(
        entry_id="entry-21",
        tool_name="update_notebook_cell",
        entry_metadata={},
        node_metadata={},
        result=json.dumps({"customCellId": "xyz"}),
        namespace=namespace,
    )

    spec = _ToolCallSpec("select_cell", None, auto_resolve=True)
    asyncio.run(spec(ctx))

    assert captured["cell_id"] == "xyz"


def test_register_context_provider_supplies_missing_argument():
    def custom_provider(ctx: Any, key: str) -> tuple[bool, Any]:
        if key.endswith("custom_value"):
            return True, "from-provider"
        return False, None

    cleanup = register_context_provider(custom_provider, prepend=True)
    try:
        def tool_with_custom(custom_value: str) -> str:
            return custom_value

        namespace = {"tool_with_custom": tool_with_custom}
        ctx = PreHookContext(
            entry_id="entry-25",
            tool_name="parent_tool",
            entry_metadata={},
            arguments={},
            namespace=namespace,
        )

        kwargs = _auto_resolve_kwargs(ctx, tool_with_custom, tool_key="tool_with_custom")
        assert kwargs["custom_value"] == "from-provider"
    finally:
        cleanup()


def test_tool_argument_hints_supply_aliases():
    @tool_argument_hints(path=("workspace_path",))
    def hinted_tool(path: str) -> None:
        return None

    namespace = {"hinted_tool": hinted_tool}
    ctx = PreHookContext(
        entry_id="entry-29",
        tool_name="parent_tool",
        entry_metadata={"tool_arguments": {"workspace_path": "foo.ipynb"}},
        arguments={},
        namespace=namespace,
    )

    kwargs = _auto_resolve_kwargs(ctx, hinted_tool, tool_key="hinted_tool")
    assert kwargs["path"] == "foo.ipynb"
