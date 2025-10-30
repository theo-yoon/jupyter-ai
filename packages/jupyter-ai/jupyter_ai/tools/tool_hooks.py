from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Optional, Sequence

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


@dataclass
class PreHookContext:
    entry_id: str
    tool_name: str
    entry_metadata: dict[str, Any]
    arguments: dict[str, Any]
    namespace: dict[str, Any]
    state: dict[str, Any] = field(default_factory=dict)


@dataclass
class PostSuccessHookContext:
    entry_id: str
    tool_name: str
    entry_metadata: dict[str, Any]
    node_metadata: dict[str, Any]
    result: Any
    namespace: dict[str, Any]
    state: dict[str, Any] = field(default_factory=dict)


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
    pre_hooks: list[WorklogPreHook] = getattr(func, _PRE_META_KEY, []) or []
    post_hooks: list[WorklogSuccessHook] = getattr(func, _POST_META_KEY, []) or []
    if pre_hooks:
        setattr(func, _PRE_META_KEY, [])
    if post_hooks:
        setattr(func, _POST_META_KEY, [])
    return pre_hooks.copy(), post_hooks.copy()


class _BaseSpec:
    async def __call__(self, ctx):  # pragma: no cover - overridden
        raise NotImplementedError


class _CallableSpec(_BaseSpec):
    def __init__(self, func: Callable[[Any], Any]):
        self.func = func

    async def __call__(self, ctx):
        result = self.func(ctx)
        if inspect.isawaitable(result):
            await result


class _ToolCallSpec(_BaseSpec):
    def __init__(
        self,
        tool_ref: Callable[..., Any] | str,
        kwargs_builder: Callable[[Any], dict[str, Any]],
        store_as: Optional[str] = None,
    ) -> None:
        self.tool_ref = tool_ref
        self.kwargs_builder = kwargs_builder
        self.store_as = store_as

    async def __call__(self, ctx):
        kwargs = self.kwargs_builder(ctx)
        target = self.tool_ref
        if isinstance(target, str):
            try:
                target = ctx.namespace[target]
            except KeyError as exc:
                raise RuntimeError(f"Unable to resolve tool '{self.tool_ref}' in hook sequence") from exc
        result = target(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        if self.store_as is not None:
            ctx.state[self.store_as] = result


def call_hook(func: Callable[[Any], Any]) -> _CallableSpec:
    return _CallableSpec(func)


def _build_kwargs_builder(kw_sources: dict[str, Any]) -> Callable[[Any], dict[str, Any]]:
    def builder(ctx: Any) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        for key, source in kw_sources.items():
            value = source(ctx) if callable(source) else source
            if value is not None:
                kwargs[key] = value
        return kwargs

    return builder


def call_tool(
    tool: Callable[..., Any] | str,
    *,
    store_as: Optional[str] = None,
    **kw_sources: Any,
) -> _ToolCallSpec:
    return _ToolCallSpec(tool, _build_kwargs_builder(kw_sources), store_as=store_as)


def _normalize_specs(specs: Sequence[Any]) -> list[_BaseSpec]:
    normalized: list[_BaseSpec] = []
    for spec in specs:
        if isinstance(spec, _BaseSpec):
            normalized.append(spec)
        elif callable(spec):
            normalized.append(_CallableSpec(spec))
        elif isinstance(spec, str):
            normalized.append(_ToolCallSpec(spec, _build_kwargs_builder({})))
        else:  # pragma: no cover - defensive programming
            raise TypeError("Unsupported hook specification")
    return normalized


def tool_pre_call_sequence(*specs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    normalized = _normalize_specs(specs)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        namespace = func.__globals__

        async def hook(entry_id: str, tool_name: str, entry_metadata: dict[str, Any], arguments: dict[str, Any]):
            ctx = PreHookContext(entry_id, tool_name, entry_metadata, arguments, namespace=namespace)
            for spec in normalized:
                await spec(ctx)

        return tool_pre_hooks(hook)(func)

    return decorator


def tool_post_success_call_sequence(*specs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    normalized = _normalize_specs(specs)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        namespace = func.__globals__

        async def hook(
            entry_id: str,
            tool_name: str,
            entry_metadata: dict[str, Any],
            node_metadata: dict[str, Any],
            result: Any,
        ):
            ctx = PostSuccessHookContext(
                entry_id, tool_name, entry_metadata, node_metadata, result, namespace=namespace
            )
            for spec in normalized:
                await spec(ctx)

        return tool_post_success_hooks(hook)(func)

    return decorator


__all__ = [
    "WorklogPreHook",
    "WorklogSuccessHook",
    "tool_pre_hooks",
    "tool_post_success_hooks",
    "collect_tool_hooks",
    "PreHookContext",
    "PostSuccessHookContext",
    "tool_pre_call_sequence",
    "tool_post_success_call_sequence",
    "call_tool",
    "call_hook",
]
