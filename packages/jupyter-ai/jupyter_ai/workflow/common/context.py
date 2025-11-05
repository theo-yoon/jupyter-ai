from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, MutableMapping

from jinja2 import Template
from jupyterlab_chat.ychat import YChat

from jupyter_ai.tools import Toolkit, WorklogTracker


Publisher = Callable[[Any, Any], None]


@dataclass
class FlowDependencies:
    """
    Immutable configuration shared across workflow nodes.

    This collects collaborators such as chat providers, toolkits, and templates
    so they can be injected without hard-coding global module state.
    """

    model_id: str
    ychat: YChat
    toolkit: Toolkit | None = None
    response_template: Template | None = None


@dataclass
class FlowRuntime:
    """
    Mutable runtime state passed between nodes.

    The goal is to gradually replace bare dictionaries with this typed access
    layer so invariants are easier to maintain and reason about.
    """

    data: MutableMapping[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def ensure_tracker(self, factory: Callable[[], WorklogTracker]) -> WorklogTracker:
        tracker = self.data.get("_worklog_tracker")
        if isinstance(tracker, WorklogTracker):
            return tracker
        tracker = factory()
        self.data["_worklog_tracker"] = tracker
        return tracker

    def export_shared(self) -> MutableMapping[str, Any]:
        """Expose legacy shared dict for compatibility during migration."""
        return self.data

    def metadata(self) -> Mapping[str, Any]:
        raw = self.data.get("metadata", {})
        return raw if isinstance(raw, Mapping) else {}
