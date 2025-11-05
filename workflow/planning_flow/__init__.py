"""
New modular version of the planning flow.

Modules here wrap the legacy implementation while exposing a structured API
that other packages can gradually adopt.

Importing this package no longer eagerly pulls in the legacy nodes; use
`run_default_flow()` which resolves the implementation lazily.
"""

from typing import Any, Mapping

__all__ = ["run_default_flow"]


async def run_default_flow(params: Mapping[str, Any]) -> None:
    from .flow import run_default_flow as _run_default_flow

    await _run_default_flow(params)
