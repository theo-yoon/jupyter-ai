from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Optional, Sequence, Mapping

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


def _attach_pre_hooks(
    *hooks: WorklogPreHook | Iterable[WorklogPreHook],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    normalized = _flatten_hooks(hooks)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        existing: list[WorklogPreHook] = getattr(func, _PRE_META_KEY, [])
        existing.extend(normalized)
        setattr(func, _PRE_META_KEY, existing)
        return func

    return decorator


def _attach_post_success_hooks(
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


class _AutoToolSpec(_BaseSpec):
    def __init__(self, name: str):
        self.name = name

    async def __call__(self, ctx):
        try:
            target = ctx.namespace[self.name]
        except KeyError as exc:  # pragma: no cover - defensive programming
            raise RuntimeError(f"Unable to resolve tool '{self.name}' in hook sequence") from exc

        kwargs = _auto_resolve_kwargs(ctx, target, tool_key=self.name)
        result = target(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        ctx.state[f"{self.name}.result"] = result


_ALIAS_KEYS: dict[str, tuple[str, ...]] = {
    "path": ("notebook_path",),
    "cell_id": ("cellId", "id"),
    "index": ("cellIndex", "cell_index"),
}
"""
Known parameter aliases to help auto-resolve hook arguments.

Add entries here when another tool needs the same logical value under a
different key (for example a frontend payload that uses ``cellId`` instead
of ``cell_id``). Prefer extending this mapping over hard-coding special cases
in individual tool modules so new aliases automatically apply everywhere.
"""

_CONTEXT_PROVIDERS: list[Callable[[Any, str], tuple[bool, Any]]] = []


def register_tool_alias(primary: str, *aliases: str) -> None:
    """
    Register additional aliases for ``primary`` so auto-resolved tool arguments
    can match alternate key names.
    """

    if not primary:
        raise ValueError("primary alias key must be provided")
    new_aliases = tuple(alias for alias in aliases if alias)
    if not new_aliases:
        return
    existing = tuple({*(_ALIAS_KEYS.get(primary, ())), *new_aliases})
    _ALIAS_KEYS[primary] = existing


def register_context_provider(provider: Callable[[Any, str], tuple[bool, Any]], *, prepend: bool = False) -> Callable[[], None]:
    """
    Register a callable that can supply values during hook argument resolution.

    Providers receive the hook context and the candidate key. Return ``(True, value)``
    to short-circuit the lookup or ``(False, None)`` to continue to the next provider.
    The function returns a cleanup callable that removes the provider when invoked.
    """

    if prepend:
        _CONTEXT_PROVIDERS.insert(0, provider)
    else:
        _CONTEXT_PROVIDERS.append(provider)

    def _cleanup() -> None:
        try:
            _CONTEXT_PROVIDERS.remove(provider)
        except ValueError:
            pass

    return _cleanup


def tool_argument_hints(**aliases: Iterable[str] | str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator attaching tool-specific alias hints for auto-resolved arguments.

    Example::

        @tool_argument_hints(path=("workspace_path",))
        async def ensure_doc(path: str) -> None:
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        existing: dict[str, set[str]] = {
            name: set(values)
            for name, values in getattr(func, "__tool_arg_aliases__", {}).items()
            if isinstance(values, Iterable)
        }
        for key, raw in aliases.items():
            values = {raw} if isinstance(raw, str) else {item for item in raw if item}
            if not values:
                continue
            existing.setdefault(key, set()).update(values)
        setattr(func, "__tool_arg_aliases__", {k: tuple(sorted(v)) for k, v in existing.items()})
        return func

    return decorator


def _iter_candidate_names(
    key: str,
    *,
    tool_key: Optional[str],
    func: Optional[Callable[..., Any]],
) -> Iterable[str]:
    seen: set[str] = set()
    aliases = [key, *_ALIAS_KEYS.get(key, ())]
    if func is not None:
        hints = getattr(func, "__tool_arg_aliases__", {})
        if isinstance(hints, Mapping):
            aliases.extend(hints.get(key, ()))

    for alias in aliases:
        if tool_key:
            scoped = f"{tool_key}.{alias}"
            if scoped not in seen:
                seen.add(scoped)
                yield scoped
        if alias not in seen:
            seen.add(alias)
            yield alias


def _lookup_mapping_value(mapping: Optional[Mapping[str, Any]], key: str) -> tuple[bool, Any]:
    if isinstance(mapping, Mapping) and key in mapping:
        return True, mapping[key]
    return False, None


def _lookup_context_value(
    ctx: Any,
    key: str,
    *,
    tool_key: Optional[str] = None,
    func: Optional[Callable[..., Any]] = None,
) -> tuple[bool, Any]:
    candidates = list(_iter_candidate_names(key, tool_key=tool_key, func=func))
    for candidate in candidates:
        for provider in _CONTEXT_PROVIDERS:
            found, value = provider(ctx, candidate)
            if found:
                return True, value
    return False, None


def _ensure_result_mapping(ctx: Any) -> Optional[Mapping[str, Any]]:
    state = getattr(ctx, "state", None)
    cache_key = "__auto_parsed_result__"
    if isinstance(state, dict) and cache_key in state:
        return state[cache_key]
    raw = getattr(ctx, "result", None)
    mapping: Optional[Mapping[str, Any]] = None
    if isinstance(raw, Mapping):
        mapping = raw
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None
        if isinstance(parsed, Mapping):
            mapping = parsed
    if isinstance(state, dict):
        state[cache_key] = mapping
    return mapping


def _auto_resolve_kwargs(ctx: Any, func: Callable[..., Any], *, tool_key: Optional[str] = None) -> dict[str, Any]:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):  # pragma: no cover - fallback when signature unavailable
        return {}

    resolved: dict[str, Any] = {}
    for name, parameter in signature.parameters.items():
        if parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
            inspect.Parameter.POSITIONAL_ONLY,
        ):
            continue

        found, value = _lookup_context_value(ctx, name, tool_key=tool_key, func=func)
        if found:
            if value is not None or parameter.default is inspect._empty:
                resolved[name] = value
            continue

        if parameter.default is inspect._empty:
            func_name = getattr(func, "__name__", repr(func))
            raise RuntimeError(f"Unable to auto-resolve required argument '{name}' for tool '{func_name}'")

    return resolved
def _state_provider(ctx: Any, key: str) -> tuple[bool, Any]:
    return _lookup_mapping_value(getattr(ctx, "state", None), key)


def _arguments_provider(ctx: Any, key: str) -> tuple[bool, Any]:
    return _lookup_mapping_value(getattr(ctx, "arguments", None), key)


def _entry_metadata_provider(ctx: Any, key: str) -> tuple[bool, Any]:
    return _lookup_mapping_value(getattr(ctx, "entry_metadata", None), key)


def _node_metadata_provider(ctx: Any, key: str) -> tuple[bool, Any]:
    return _lookup_mapping_value(getattr(ctx, "node_metadata", None), key)


def _tool_arguments_provider(ctx: Any, key: str) -> tuple[bool, Any]:
    entry_meta = getattr(ctx, "entry_metadata", None)
    node_meta = getattr(ctx, "node_metadata", None)
    sources = []
    if isinstance(entry_meta, Mapping):
        sources.append(entry_meta.get("tool_arguments"))
    if isinstance(node_meta, Mapping):
        sources.append(node_meta.get("tool_arguments"))
    for source in sources:
        found, value = _lookup_mapping_value(source, key)
        if found:
            return found, value
    return False, None


def _result_provider(ctx: Any, key: str) -> tuple[bool, Any]:
    mapping = _ensure_result_mapping(ctx)
    if isinstance(mapping, Mapping):
        found, value = _lookup_mapping_value(mapping, key)
        if found:
            return found, value
        nested_candidates = []
        nested = mapping.get("result")
        if isinstance(nested, Mapping):
            nested_candidates.append(nested)
        raw = mapping.get("raw")
        if isinstance(raw, Mapping):
            nested_candidates.append(raw)
        for candidate in nested_candidates:
            found, value = _lookup_mapping_value(candidate, key)
            if found:
                return found, value
    return False, None


def _attribute_provider(ctx: Any, key: str) -> tuple[bool, Any]:
    if key == "entry_id":
        return True, getattr(ctx, "entry_id", None)
    if key == "tool_name":
        return True, getattr(ctx, "tool_name", None)
    return False, None


if not _CONTEXT_PROVIDERS:
    _CONTEXT_PROVIDERS.extend(
        [
            _state_provider,
            _arguments_provider,
            _entry_metadata_provider,
            _node_metadata_provider,
            _tool_arguments_provider,
            _result_provider,
            _attribute_provider,
        ]
    )


def _normalize_specs(specs: Sequence[Any]) -> list[_BaseSpec]:
    normalized: list[_BaseSpec] = []
    for spec in specs:
        if isinstance(spec, _BaseSpec):
            normalized.append(spec)
        elif callable(spec):
            normalized.append(_CallableSpec(spec))
        elif isinstance(spec, str):
            normalized.append(_AutoToolSpec(spec))
        else:  # pragma: no cover - defensive programming
            raise TypeError("Unsupported hook specification")
    return normalized


def tool_pre_hooks(*specs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    normalized = _normalize_specs(specs)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        namespace = func.__globals__

        async def hook(entry_id: str, tool_name: str, entry_metadata: dict[str, Any], arguments: dict[str, Any]):
            ctx = PreHookContext(entry_id, tool_name, entry_metadata, arguments, namespace=namespace)
            for spec in normalized:
                await spec(ctx)

        return _attach_pre_hooks(hook)(func)

    return decorator


def tool_post_hooks(*specs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
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

        return _attach_post_success_hooks(hook)(func)

    return decorator


__all__ = [
    "WorklogPreHook",
    "WorklogSuccessHook",
    "collect_tool_hooks",
    "PreHookContext",
    "PostSuccessHookContext",
    "tool_pre_hooks",
    "tool_post_hooks",
    "register_tool_alias",
    "register_context_provider",
    "tool_argument_hints",
]
