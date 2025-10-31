"""
Extended toolkit that augments the default tools with worklog-aware helpers.

The heavy lifting now lives in dedicated modules:

- ``worklog_tracking`` wraps toolkit calls with status updates and metadata.
- ``frontend_commands`` waits on JupyterLab frontend commands.
- ``summary_builders`` generates human-readable plan node summaries.

This module focuses on assembling the public ``PLAN_AWARE_TOOLKIT`` and
re-exporting the tracked helpers for backwards compatibility.
"""

from .data_analysis_toolkit import DATA_ANALYSIS_TOOLKIT
from .frontend_commands import (
    DOCMANAGER_OPEN_COMMAND,
    RUN_ACTIVE_NOTEBOOK_CELL_COMMAND,
    SELECT_NOTEBOOK_CELL_COMMAND,
    WAIT_KERNEL_IDLE_COMMAND,
    await_frontend_command,
)
from .models import Tool, Toolkit
from .notebook_toolkit import NOTEBOOK_TOOLKIT
from .worklog_tracking import (
    emit_failure_tool,
    emit_status_transition_tool,
    execute_with_worklog,
    make_tracked_callable,
    push_worklog_update_tool,
    register_callable_hooks,
    _resolve_entry_context,
    tracked_bash,
    tracked_edit,
    tracked_read,
    tracked_search_grep,
    tracked_write,
)


PLAN_AWARE_TOOLKIT = Toolkit(name="jupyter-ai-plan-toolkit")


def _add_plan_tool(tool: Tool) -> None:
    tool_name = tool.name or getattr(tool.callable, "__name__", "tool")
    register_callable_hooks(tool.callable, tool_name)
    PLAN_AWARE_TOOLKIT.add_tool(tool)


def _extend_plan_toolkit_with(source: Toolkit) -> None:
    for tool in source.tools:
        tracked_callable = make_tracked_callable(tool)
        _add_plan_tool(
            Tool(
                callable=tracked_callable,
                name=tool.name,
                description=tool.description,
                read=tool.read,
                write=tool.write,
                execute=tool.execute,
                delete=tool.delete,
            )
        )


_add_plan_tool(Tool(callable=tracked_bash, execute=True))
# Frontend-facing helpers like `await_frontend_command` stay out of the public toolkit
# so only higher-level notebook tools invoke them.
_add_plan_tool(Tool(callable=tracked_search_grep, read=True))
_add_plan_tool(Tool(callable=tracked_read, read=True))
_add_plan_tool(Tool(callable=tracked_edit, write=True))
_add_plan_tool(Tool(callable=tracked_write, write=True))
_add_plan_tool(Tool(callable=push_worklog_update_tool))
_add_plan_tool(Tool(callable=emit_status_transition_tool))
_add_plan_tool(Tool(callable=emit_failure_tool))

_extend_plan_toolkit_with(NOTEBOOK_TOOLKIT)
_extend_plan_toolkit_with(DATA_ANALYSIS_TOOLKIT)


__all__ = [
    "PLAN_AWARE_TOOLKIT",
    "tracked_bash",
    "tracked_search_grep",
    "tracked_read",
    "tracked_edit",
    "tracked_write",
    "await_frontend_command",
    "execute_with_worklog",
    "push_worklog_update_tool",
    "emit_status_transition_tool",
    "emit_failure_tool",
    "_resolve_entry_context",
    "DOCMANAGER_OPEN_COMMAND",
    "WAIT_KERNEL_IDLE_COMMAND",
    "SELECT_NOTEBOOK_CELL_COMMAND",
    "RUN_ACTIVE_NOTEBOOK_CELL_COMMAND",
]
