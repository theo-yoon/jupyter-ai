"""
Domain objects shared across workflow implementations.
"""

from .progress import PlanProgressSnapshot, FlowPhase

__all__ = [
    "PlanProgressSnapshot",
    "FlowPhase",
]
