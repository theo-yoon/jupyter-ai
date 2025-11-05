"""
Compatibility facade for legacy `jupyter_ai.default_flow` imports.

The planning flow refactor relocated the default flow implementation under
`jupyter_ai.workflow.router.default_flow`.  Downstream callers—including
personas and third-party extensions—still import
`run_default_flow` (and related types) from `jupyter_ai.default_flow`.
This module re-exports the updated implementations to preserve that contract.
"""

from __future__ import annotations

from jupyter_ai.workflow.router import default_flow as _default_flow

DefaultFlowParams = _default_flow.DefaultFlowParams
RootNode = _default_flow.RootNode
ToolExecutorNode = _default_flow.ToolExecutorNode
deliver_playbook_result = _default_flow.deliver_playbook_result
run_default_flow = _default_flow.run_default_flow

__all__ = [
    "run_default_flow",
    "DefaultFlowParams",
    "RootNode",
    "ToolExecutorNode",
    "deliver_playbook_result",
]
