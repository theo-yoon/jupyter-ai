"""Tools package for Jupyter AI."""

from .models import Tool, Toolkit
from .default_toolkit import DEFAULT_TOOLKIT
from .command_registry import CommandExecutionRegistry, command_registry
from .jlab_command_tool import (
    ensure_notebook_open_command,
    wait_for_notebook_idle,
    select_notebook_cell_command,
    run_notebook_cell_command,
    create_notebook,
    edit_notebook_cell,
    list_kernel_activity,
    manage_kernel_activity,
)
from .data_tools import DATA_TOOLS, list_csv, head, inspect_csv
from .worklog_tracking import WorklogTracker

AGENT_TOOLKIT = Toolkit(
    name="jupyter-ai-agent-toolkit",
    description="Combined default toolkit with lightweight data-inspection helpers.",
)
for toolkit in (DEFAULT_TOOLKIT, DATA_TOOLS):
    for tool in toolkit.tools:
        AGENT_TOOLKIT.add_tool(tool)

__all__ = [
    "Tool",
    "Toolkit",
    "DEFAULT_TOOLKIT",
    "AGENT_TOOLKIT",
    "DATA_TOOLS",
    "CommandExecutionRegistry",
    "command_registry",
    "ensure_notebook_open_command",
    "wait_for_notebook_idle",
    "select_notebook_cell_command",
    "run_notebook_cell_command",
    "create_notebook",
    "edit_notebook_cell",
    "list_kernel_activity",
    "manage_kernel_activity",
    "list_csv",
    "head",
    "inspect_csv",
    "WorklogTracker",
]
