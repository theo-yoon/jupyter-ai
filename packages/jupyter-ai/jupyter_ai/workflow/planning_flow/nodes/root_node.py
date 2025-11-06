from __future__ import annotations

import logging
import sys
from typing import Any, Mapping, Optional, Sequence, Tuple, TypedDict, Literal

from jinja2 import Template
from litellm import acompletion
from pocketflow import AsyncNode
from typing_extensions import NotRequired

from jupyterlab_chat.ychat import YChat

from jupyter_ai.personas import SYSTEM_USERNAME, PersonaAwareness
from jupyter_ai.tools import Toolkit, WorklogTracker
from jupyter_ai.litellm_lib import ToolCallList
from jupyter_ai.workflow.common.knowledge import KnowledgeCoordinator

from ...common.utils import strip_token, strip_sentinel
from ..runtime import (
    _plan_state,
    _worklog_service,
    _capture_plan_progress,
    _ensure_active_step,
)
from jupyter_ai.workflow.playbook_flow.helpers import deliver_playbook_result as default_deliver_playbook_result
from .components import prepare_context, run_stream, process_response, ResponseSignals

async def maybe_run_planning_playbook(
    params: dict[str, Any],
    logger: logging.Logger,
) -> bool:
    context = params.get("_knowledge_context")
    if not context:
        return False
    match = getattr(context, "match", None)
    if not match:
        return False
    metadata = match.metadata or {}
    playbook_meta = metadata.get("playbook")
    if not isinstance(playbook_meta, Mapping):
        return False

    from jupyter_ai.workflow.playbook_flow.flow import PlaybookFlowError, run_playbook_flow

    try:
        result = await run_playbook_flow(params, match=match, context=context)
    except PlaybookFlowError as exc:
        logger.warning("[planning_flow] Playbook flow rejected: %s", exc)
        return False
    except Exception as exc:  # pragma: no cover
        logger.exception("[planning_flow] Playbook flow crashed: %s", exc)
        return False

    deliver = _resolve_deliver_playbook_result()
    deliver(params, result, logger=logger)
    return True

LOG = logging.getLogger("jupyter_ai.workflow.planning_flow")
if not LOG.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("[default_flow] %(levelname)s %(message)s"))
    LOG.addHandler(handler)
    LOG.propagate = False

DEFAULT_RESPONSE_TEMPLATE = """
{{ worklog_ui_elements }}
{% if answer_ui_elements %}
{{ answer_ui_elements }}
{% else %}
{{ content }}
{% endif %}
{{ tool_call_ui_elements }}
""".strip()

STEP_COMPLETED_TOKEN = "<STEP_COMPLETED>"

FLOW_SIGNAL_EXECUTE_TOOLS = "execute-tools"
FLOW_SIGNAL_CONTINUE = "continue"
FLOW_SIGNAL_COMPLETE = "complete"

PLAYBOOK_SENTINEL = "<<playbook_required>>"

_STEP_COMPLETION_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "report_step_completion",
        "description": (
            "Call this when the current plan step has been fully addressed. "
            "Provide optional notes or follow-up actions for the next steps."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "step_id": {
                    "type": "string",
                    "description": "Identifier of the step being completed. Optional; defaults to the active step.",
                },
                "notes": {
                    "type": "string",
                    "description": "Additional context or reasoning about the completion.",
                },
                "next_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Recommended follow-up tasks for subsequent steps.",
                },
            },
            "additionalProperties": False,
        },
    },
}

_LEGACY_STEP_COMPLETION_TOOL_SPEC = {
    **_STEP_COMPLETION_TOOL_SPEC,
    "function": {
        **_STEP_COMPLETION_TOOL_SPEC["function"],
        "name": "complete_plan_step",
    },
}

STEP_COMPLETION_TOOL_NAMES = {"report_step_completion", "complete_plan_step"}


def _with_step_completion_tools(toolkit: Toolkit | None) -> list[dict[str, Any]]:
    descriptions = toolkit.to_json() if toolkit else []
    existing_tool_names = {
        tool.get("function", {}).get("name")
        for tool in descriptions
        if isinstance(tool, dict)
    }
    for spec in (_STEP_COMPLETION_TOOL_SPEC, _LEGACY_STEP_COMPLETION_TOOL_SPEC):
        name = spec.get("function", {}).get("name")
        if name not in existing_tool_names:
            descriptions.append(spec)
            existing_tool_names.add(name)
    LOG.info(
        "[_with_step_completion_tools] returning tools=%s",
        [tool.get("function", {}).get("name") for tool in descriptions if isinstance(tool, dict)],
    )
    return descriptions


def _strip_step_completion_markers(text: str) -> tuple[str, bool]:
    return strip_token(text, STEP_COMPLETED_TOKEN)


def _strip_playbook_signal(text: str) -> tuple[str, bool]:
    return strip_sentinel(text, PLAYBOOK_SENTINEL)


class DefaultFlowParams(TypedDict):
    model_id: str
    ychat: YChat
    awareness: PersonaAwareness
    persona_id: str
    logger: logging.Logger
    model_args: dict[str, Any] | None
    system_prompt: Optional[str]
    response_template: Template | None
    toolkit: Toolkit | None
    history_size: int | None
    room_id: str | None
    plan_mode: Literal["auto", "always", "never"] | None
    knowledge_coordinator: NotRequired[KnowledgeCoordinator | None]


class JaiAsyncNode(AsyncNode):
    @property
    def model_id(self) -> str:
        return self.params["model_id"]

    @property
    def ychat(self) -> YChat:
        return self.params["ychat"]

    @property
    def awareness(self) -> PersonaAwareness:
        return self.params["awareness"]

    @property
    def persona_id(self) -> str:
        return self.params["persona_id"]

    @property
    def model_args(self) -> dict[str, Any]:
        return self.params.get("model_args", {})

    @property
    def system_prompt(self) -> Optional[str]:
        return self.params.get("system_prompt")

    @property
    def response_template(self) -> Template:
        template = self.params.get("response_template")
        if not template:
            template = Template(DEFAULT_RESPONSE_TEMPLATE)
        return template

    @property
    def toolkit(self) -> Optional[Toolkit]:
        return self.params.get("toolkit")

    @property
    def history_size(self) -> int:
        return self.params.get("history_size", 2)

    @property
    def log(self) -> logging.Logger:
        return self.params.get("logger", LOG)

    @property
    def room_id(self) -> str | None:
        return self.params.get("room_id")

    @property
    def knowledge_coordinator(self) -> KnowledgeCoordinator | None:
        return self.params.get("knowledge_coordinator")


class RootNode(JaiAsyncNode):
    FLOW_SIGNAL_EXECUTE_TOOLS = FLOW_SIGNAL_EXECUTE_TOOLS
    FLOW_SIGNAL_CONTINUE = FLOW_SIGNAL_CONTINUE
    FLOW_SIGNAL_COMPLETE = FLOW_SIGNAL_COMPLETE

    async def prep_async(self, shared):
        prep = await prepare_context(self, shared, system_username=SYSTEM_USERNAME)
        return prep.as_dict()

    async def exec_async(self, prep_res: dict[str, Any]):
        self.log.info(
            "Running RootNode.exec_async() model_args=%s",
            getattr(self, "model_args", {}),
        )
        try:
            outcome = await run_stream(
                self,
                prep_res,
                tool_factory=_with_step_completion_tools,
                resolve_acompletion=_resolve_acompletion,
            )
        except Exception as exc:
            self.log.exception("run_stream raised: %s", exc)
            raise
        return outcome.stream_id, outcome.content, outcome.tool_calls

    async def post_async(self, shared, prep_res, exec_res: Tuple[str, str, ToolCallList]):
        response = await process_response(
            node=self,
            shared=shared,
            prep_res=prep_res,
            exec_res=exec_res,
            strip_completion=_strip_step_completion_markers,
            strip_playbook=_strip_playbook_signal,
            maybe_run_playbook=maybe_run_planning_playbook,
            signals=ResponseSignals(
                execute=FLOW_SIGNAL_EXECUTE_TOOLS,
                continue_=FLOW_SIGNAL_CONTINUE,
                complete=FLOW_SIGNAL_COMPLETE,
            ),
        )
        return response.signal


__all__ = [
    "DEFAULT_RESPONSE_TEMPLATE",
    "STEP_COMPLETED_TOKEN",
    "FLOW_SIGNAL_EXECUTE_TOOLS",
    "FLOW_SIGNAL_CONTINUE",
    "FLOW_SIGNAL_COMPLETE",
    "PLAYBOOK_SENTINEL",
    "STEP_COMPLETION_TOOL_NAMES",
    "_STEP_COMPLETION_TOOL_SPEC",
    "_LEGACY_STEP_COMPLETION_TOOL_SPEC",
    "DefaultFlowParams",
    "JaiAsyncNode",
    "RootNode",
    "_with_step_completion_tools",
    "_strip_step_completion_markers",
    "_strip_playbook_signal",
]


def _resolve_acompletion():
    planning_module = sys.modules.get("jupyter_ai.workflow.planning_flow")
    override = getattr(planning_module, "acompletion", None)
    if callable(override):
        return override
    return acompletion


def _resolve_deliver_playbook_result():
    planning_module = sys.modules.get("jupyter_ai.workflow.planning_flow")
    override = getattr(planning_module, "deliver_playbook_result", None)
    if callable(override) and override is not default_deliver_playbook_result:
        return override
    playbook_helpers = sys.modules.get("jupyter_ai.workflow.playbook_flow.helpers")
    if playbook_helpers is None:
        import jupyter_ai.workflow.playbook_flow.helpers as playbook_helpers  # type: ignore

    deliver = getattr(playbook_helpers, "deliver_playbook_result", default_deliver_playbook_result)
    return deliver
