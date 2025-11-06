"""Flow routing utilities for orchestrating agent strategies."""

from .router import (
    run_default_flow as run_router_flow,
    decide_initial_route,
    assess_after_simple,
)

run_routing_flow = run_router_flow

__all__ = [
    "run_routing_flow",
    "decide_initial_route",
    "assess_after_simple",
]
