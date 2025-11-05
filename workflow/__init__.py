"""
High-level workflow package that exposes reusable building blocks for agent flows.

This package hosts both planning-specific components and shared workflow services.
Keeping the exports centralized here lets existing import sites transition gradually.
"""

from importlib import import_module

__all__ = ["common"]


def __getattr__(name: str):
    if name == "common":
        module = import_module("workflow.common")
        globals()[name] = module
        return module
    raise AttributeError(f"module 'workflow' has no attribute {name!r}")
