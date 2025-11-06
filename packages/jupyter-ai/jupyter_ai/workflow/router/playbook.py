from __future__ import annotations

import logging
from typing import Any

from jupyter_ai.workflow.planning_flow.nodes.root_node import (
    maybe_run_planning_playbook as planning_maybe_run_playbook,
)


async def maybe_run_playbook(
    params: dict[str, Any],
    context,
    simple_snapshot: dict[str, Any] | None,
    *,
    logger: logging.Logger | None = None,
) -> bool:
    if not context:
        return False

    params["_knowledge_context"] = context
    result = await planning_maybe_run_playbook(params, logger or logging.getLogger("jupyter_ai.router"))
    return result
