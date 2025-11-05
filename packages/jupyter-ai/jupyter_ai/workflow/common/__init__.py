"""Shared workflow infrastructure used across agent flows."""

from importlib import import_module

__all__ = ["context", "domain", "prompt", "services", "worklog"]


def __getattr__(name: str):
    if name in __all__:
        module = import_module(f"jupyter_ai.workflow.common.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module 'jupyter_ai.workflow.common' has no attribute {name!r}")
