"""
High-level workflow package that exposes reusable building blocks for agent flows.

This package hosts both planning-specific components and shared workflow services.
Keeping the exports centralized here lets existing import sites transition gradually.
"""

from importlib import import_module

__all__ = ["common", "planning_flow"]


def __getattr__(name: str):
    if name in __all__:
        module = import_module(f"jupyter_ai.workflow.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module 'jupyter_ai.workflow' has no attribute {name!r}")
