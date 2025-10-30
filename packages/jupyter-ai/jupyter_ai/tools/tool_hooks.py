from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Awaitable, Optional, Sequence

WorklogPreHook = Callable[
    [str, str, dict[str, Any], dict[str, Any]],
    Optional[Awaitable[None]],
]

WorklogSuccessHook = Callable[
    [str, str, dict[str, Any], dict[str, Any], Any],
    Optional[Awaitable[None]],
]

_PRE_META_KEY = "__jai_pre_hooks__"
_POST_META_KEY = "__jai_post_success_hooks__"


def _flatten_hooks(items: Sequence[Any]) -> list[Callable]:
    flattened: list[Callable] = []
    for item in items:
        if isinstance(item, (list, tuple, set)):
            flattened.extend(_flatten_hooks(tuple(item)))
        else:
            flattened.append(item)
    return flattened


def tool_pre_hooks(
    *hooks: WorklogPreHook | Iterable[WorklogPreHook],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Attach one or more pre-execution hooks to a tool callable.
    """
    normalized = _flatten_hooks(hooks)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        existing: list[WorklogPreHook] = getattr(func, _PRE_META_KEY, [])
        existing.extend(normalized)
        setattr(func, _PRE_META_KEY, existing)
        return func

    return decorator


def tool_post_success_hooks(
    *hooks: WorklogSuccessHook | Iterable[WorklogSuccessHook],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Attach one or more post-success hooks to a tool callable.
    """
    normalized = _flatten_hooks(hooks)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        existing: list[WorklogSuccessHook] = getattr(func, _POST_META_KEY, [])
        existing.extend(normalized)
        setattr(func, _POST_META_KEY, existing)
        return func

    return decorator


def collect_tool_hooks(
    func: Callable[..., Any],
) -> tuple[list[WorklogPreHook], list[WorklogSuccessHook]]:
    """
    Retrieve and clear hook metadata attached to a tool callable.
    """
    pre_hooks: list[WorklogPreHook] = getattr(func, _PRE_META_KEY, []) or []
    post_hooks: list[WorklogSuccessHook] = getattr(func, _POST_META_KEY, []) or []
    if pre_hooks:
        setattr(func, _PRE_META_KEY, [])
    if post_hooks:
        setattr(func, _POST_META_KEY, [])
    return pre_hooks.copy(), post_hooks.copy()


__all__ = [
    "WorklogPreHook",
    "WorklogSuccessHook",
    "tool_pre_hooks",
    "tool_post_success_hooks",
    "collect_tool_hooks",
]
