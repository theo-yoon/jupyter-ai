from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, TYPE_CHECKING, Protocol, Any

from .types import LitellmToolCallOutput, JaiToolCallProps


class ToolFunctionLike(Protocol):
    name: str
    arguments: str


class ToolCallLike(Protocol):
    id: str
    index: int
    type: str
    function: ToolFunctionLike


if TYPE_CHECKING:
    from litellm.utils import ChatCompletionDeltaToolCall as ToolCallLike  # type: ignore[no-redef]


class ToolCallRenderer(ABC):
    """
    Contract for objects that serialize resolved tool calls into web-component
    attribute dictionaries. Implementations choose which tool calls they handle
    via `matches`.
    """

    @abstractmethod
    def matches(self, tool_call: ToolCallLike) -> bool:
        """
        Returns True if this renderer should serialize the provided tool call.
        """

    @abstractmethod
    def serialize(
        self,
        tool_call: ToolCallLike,
        output: Optional[LitellmToolCallOutput],
        room_id: Optional[str]
    ) -> Dict[str, Any]:
        """
        Serializes the tool call into stringified attributes suitable for
        injecting into a web component.
        """


class _DefaultToolCallRenderer(ToolCallRenderer):
    """
    Mimics the historical serialization performed by `ToolCallList.render`.
    """

    def matches(self, tool_call: ToolCallLike) -> bool:
        return True

    def serialize(
        self,
        tool_call: ToolCallLike,
        output: Optional[LitellmToolCallOutput],
        room_id: Optional[str]
    ) -> Dict[str, Any]:
        props: Dict[str, Any] = {
            'tool_id': tool_call.id,
            'index': tool_call.index,
            'type': tool_call.type,
            'function_name': tool_call.function.name,
            'function_args': tool_call.function.arguments,
        }

        if output is not None:
            props['output'] = json.dumps(output)
        if room_id:
            props['room_id'] = room_id

        return props


def _normalize_function_name(name: str) -> str:
    return ''.join(ch for ch in name.lower() if ch.isalnum())


class _AdvancedPlanRenderer(ToolCallRenderer):
    """
    Provides additional attributes for advanced plan summary/worklog cards.
    """

    _summary_fn_names = {
        _normalize_function_name('advanced_plan_summary'),
        _normalize_function_name('advanced-plan-summary'),
        _normalize_function_name('advancedPlanSummary'),
    }
    _worklog_fn_names = {
        _normalize_function_name('advanced_plan_worklog'),
        _normalize_function_name('advanced-plan-worklog'),
        _normalize_function_name('advancedPlanWorklog'),
    }
    _final_summary_fn_names = {
        _normalize_function_name('advanced_plan_final_summary'),
        _normalize_function_name('advanced-plan-final-summary'),
        _normalize_function_name('advancedPlanFinalSummary'),
    }

    def matches(self, tool_call: ToolCallLike) -> bool:
        normalized = _normalize_function_name(tool_call.function.name)
        return normalized in (
            self._summary_fn_names
            .union(self._worklog_fn_names)
            .union(self._final_summary_fn_names)
        )

    def serialize(
        self,
        tool_call: ToolCallLike,
        output: Optional[LitellmToolCallOutput],
        room_id: Optional[str]
    ) -> Dict[str, Any]:
        props: Dict[str, Any] = {
            'tool_id': tool_call.id,
            'index': tool_call.index,
            'type': tool_call.type,
            'function_name': tool_call.function.name,
            'function_args': tool_call.function.arguments,
        }

        if output is not None:
            props['output'] = json.dumps(output)
        if room_id:
            props['room_id'] = room_id

        normalized = _normalize_function_name(tool_call.function.name)
        if normalized in self._summary_fn_names:
            props['plan_data'] = tool_call.function.arguments
        if normalized in self._worklog_fn_names:
            props['worklog_data'] = tool_call.function.arguments
        if normalized in self._final_summary_fn_names:
            props['final_summary_data'] = tool_call.function.arguments

        return props


_renderers: List[ToolCallRenderer] = [_DefaultToolCallRenderer()]


def register_tool_call_renderer(renderer: ToolCallRenderer) -> None:
    """
    Registers a renderer. New renderers take precedence over previously
    registered ones.
    """
    _renderers.insert(0, renderer)


def serialize_tool_call(
    tool_call: ToolCallLike,
    output: Optional[LitellmToolCallOutput],
    room_id: Optional[str]
) -> JaiToolCallProps:
    """
    Serializes the tool call using the highest priority renderer that matches.
    """
    for renderer in _renderers:
        if renderer.matches(tool_call):
            serialized = renderer.serialize(tool_call, output, room_id)
            return serialized  # type: ignore[return-value]

    # Fallback: should never happen because default renderer matches all calls
    serialized = _renderers[-1].serialize(tool_call, output, room_id)
    return serialized  # type: ignore[return-value]


# Ensure advanced plan renderer takes priority over the default renderer.
register_tool_call_renderer(_AdvancedPlanRenderer())
