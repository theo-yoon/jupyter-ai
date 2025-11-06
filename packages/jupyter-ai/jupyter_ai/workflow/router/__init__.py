"""Flow routing utilities for orchestrating agent strategies."""

from jupyter_ai.workflow.playbook_flow.helpers import deliver_playbook_result

from .router import (
    run_default_flow as run_router_flow,
    decide_initial_route,
    assess_after_simple,
)
from .playbook import maybe_run_playbook as router_maybe_run_playbook

run_routing_flow = run_router_flow

__all__ = [
    "run_routing_flow",
    "router_maybe_run_playbook",
    "deliver_playbook_result",
    "decide_initial_route",
    "assess_after_simple",
]
