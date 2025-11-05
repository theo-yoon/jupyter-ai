"""
New modular version of the planning flow.

Modules here wrap the legacy implementation while exposing a structured API
that other packages can gradually adopt.

Importing this package no longer eagerly pulls in the legacy nodes; use
`run_default_flow()` which resolves the implementation lazily.
"""

from typing import Any, Mapping, MutableMapping

__all__ = ["run_default_flow"]


async def run_default_flow(
    params: Mapping[str, Any],
    *,
    shared_state: MutableMapping[str, Any] | None = None,
) -> MutableMapping[str, Any]:
    from .flow import run_default_flow as _run_default_flow

    return await _run_default_flow(params, shared_state=shared_state)
