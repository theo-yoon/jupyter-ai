from importlib import import_module

__all__ = [
    "default_flow",
    "planning_flow",
    "simple_flow",
    "knowledge",
    "playbook_helpers",
]


def __getattr__(name: str):
    if name in __all__:
        module = import_module(f"jupyter_ai.default_flow.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module 'jupyter_ai.default_flow' has no attribute {name!r}")
