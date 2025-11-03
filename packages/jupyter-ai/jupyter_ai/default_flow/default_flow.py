from __future__ import annotations

import logging
import re
from typing import Literal

from litellm import acompletion

from ..personas import SYSTEM_USERNAME
from .simple_flow import run_default_flow as run_simple_flow, DefaultFlowParams as SimpleFlowParams
from .planning_flow import (
    run_default_flow as run_planning_flow,
    DefaultFlowParams as PlanningFlowParams,
    RootNode as PlanningRootNode,
    ToolExecutorNode as PlanningToolExecutorNode,
)


# Re-export planning flow nodes for existing imports in tests/extensions.
RootNode = PlanningRootNode
ToolExecutorNode = PlanningToolExecutorNode

# Unified TypedDict alias used by callers. Planning params superset simple flow params.
DefaultFlowParams = PlanningFlowParams

_KEYWORDS = {
    "plan",
    "steps",
    "step-by-step",
    "analyze",
    "analyse",
    "investigate",
    "outline",
    "strategy",
    "walkthrough",
    "workflow",
    "approach",
    "multi",
}
_BULLET_PATTERN = re.compile(r"\n\s*[-*•]")
_ENUM_PATTERN = re.compile(r"\n\s*\d+\.\s")


async def run_default_flow(params: DefaultFlowParams):  # pragma: no cover - thin router
    """Route between simple and planning flows based on request complexity."""

    plan_mode: Literal["auto", "always", "never"] | None = params.get("plan_mode")  # type: ignore[attr-defined]
    mode = (plan_mode or "auto").lower()
    logger: logging.Logger | None = params.get("logger")  # type: ignore[arg-type]

    if mode == "always":
        if logger:
            logger.debug("[default_flow] Using planning flow (forced)")
        return await run_planning_flow(params)
    if mode == "never":
        if logger:
            logger.debug("[default_flow] Using simple flow (forced)")
        return await run_simple_flow(params)

    latest_message = _extract_latest_user_message(params)
    use_planning = await _agent_should_use_planning(params, latest_message)
    if use_planning is None:
        use_planning = _should_use_planning(latest_message)
    if logger:
        logger.debug(
            "[default_flow] Routing decision: flow=%s reason=%s",
            "planning" if use_planning else "simple",
            latest_message or "<empty>",
        )

    if use_planning:
        return await run_planning_flow(params)
    return await run_simple_flow(params)


def _extract_latest_user_message(params: DefaultFlowParams) -> str | None:
    try:
        messages = params["ychat"].get_messages()
    except Exception:
        return None

    for msg in reversed(messages):
        sender = getattr(msg, "sender", "") or ""
        if sender == SYSTEM_USERNAME:
            continue
        if sender.startswith("jupyter-ai-personas::"):
            continue
        body = getattr(msg, "body", None)
        if isinstance(body, str):
            stripped = body.strip()
            if stripped:
                return stripped
    return None


def _should_use_planning(message: str | None) -> bool:
    if not message:
        return False

    lower = message.lower()
    if any(keyword in lower for keyword in _KEYWORDS):
        return True

    bullet_hits = len(_BULLET_PATTERN.findall(message))
    enum_hits = len(_ENUM_PATTERN.findall(message))
    if bullet_hits + enum_hits > 0:
        return True

    sequencing_terms = sum(lower.count(term) for term in [" first ", " second ", " third ", " next ", " then ", " after "])
    if sequencing_terms >= 2:
        return True

    and_count = lower.count(" and ")
    if and_count >= 2:
        return True

    if len(message) > 200:
        return True

    return False


async def _agent_should_use_planning(
    params: DefaultFlowParams,
    message: str | None,
) -> bool | None:
    if not message:
        return None

    model_id = params.get("model_id")
    if not model_id:
        return None

    model_args = dict(params.get("model_args") or {})
    model_args.pop("stream", None)

    system_prompt = (
        "You are a routing assistant. Decide if the user's request requires a multi-step plan. "
        "Respond with a single token: PLAN if a structured plan with multiple steps is needed, "
        "or SIMPLE if a direct answer or single action is sufficient."
    )
    user_prompt = (
        "User request:\n" + message.strip() + "\n\nRespond with PLAN or SIMPLE."
    )

    try:
        response = await acompletion(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **model_args,
        )
    except Exception as err:  # pragma: no cover - fallback path only
        logger = params.get("logger")
        if logger:
            logger.warning("[default_flow] plan router failed: %s", err)
        return None

    try:
        choice = response.choices[0].message.get("content", "")  # type: ignore[index]
    except Exception:  # pragma: no cover - unexpected schema
        return None

    normalized = choice.strip().lower()
    if "plan" in normalized:
        return True
    if "simple" in normalized or normalized == "no":
        return False
    return None
