from pocketflow import AsyncNode, AsyncFlow
from jupyterlab_chat.models import Message, NewMessage
from jupyterlab_chat.ychat import YChat
from typing import Any, Optional, Sequence, Tuple, TypedDict, Literal
from jinja2 import Template
from litellm import acompletion, ModelResponseStream
import time
import logging
from uuid import uuid4
import json
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from ..litellm_lib import ToolCallList, run_tools, LitellmToolCallOutput
from ..litellm_lib.toolcall_list import ResolvedToolCall
from ..litellm_lib.run_tools import WORK_ITEM_TITLE_ARG
from ..tools import Toolkit, WorklogTracker
from ..personas import SYSTEM_USERNAME, PersonaAwareness
from ..worklog import (
    WorklogStoppedError,
    build_plan_progress_patch,
    build_plan_step,
    build_work_node,
    build_worklog_entry,
    build_worklog_markup,
    build_worklog_patch,
    generate_plan_steps,
    summarize_user_query,
    worklog_controller,
    worklog_repository,
)
from ..worklog.plan_steps import PlanStep
from ..worklog.work_nodes import WorkNode
from .plan_manager import PlanStepManager
from .prompt_builder import PromptBuilder
from .step_manager import StepManager
from .summary_generator import SummaryGenerator
from .work_item_logger import WorkItemLogger

DEFAULT_RESPONSE_TEMPLATE = """
{{ worklog_ui_elements }}
{{ content }}
{{ tool_call_ui_elements }}
""".strip()

STEP_COMPLETED_TOKEN = "<STEP_COMPLETED>"

FLOW_SIGNAL_EXECUTE_TOOLS = "execute-tools"
FLOW_SIGNAL_CONTINUE = "continue"
FLOW_SIGNAL_COMPLETE = "complete"

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

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)
if not LOG.handlers:
    _handler = logging.StreamHandler()
    _handler.setLevel(logging.INFO)
    _handler.setFormatter(
        logging.Formatter("[default_flow] %(levelname)s %(message)s")
    )
    LOG.addHandler(_handler)
    LOG.propagate = False


def _latest_user_message(messages: Sequence[dict[str, Any]]) -> str | None:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
    return None


def _derive_reasoning_title(text: str) -> str:
    snippet = re.sub(r"\s+", " ", text).strip()
    if not snippet:
        return "Agent reasoning"
    words = snippet.split(" ")
    selected = words[:5]
    title = " ".join(selected).strip()
    if not title:
        return "Agent reasoning"
    if len(words) > len(selected):
        title += "…"
    return title[0].upper() + title[1:]


@dataclass(frozen=True)
class PlanProgressSnapshot:
    step_ids: tuple[str, ...]
    statuses: tuple[str, ...]
    active_step_id: str | None

    @property
    def total_steps(self) -> int:
        return len(self.step_ids)

    @property
    def remaining_steps(self) -> int:
        return sum(
            1 for status in self.statuses if status in ("pending", "in_progress")
        )

    @property
    def is_finished(self) -> bool:
        if self.total_steps == 0:
            return True
        if self.remaining_steps > 0:
            return False
        return self.active_step_id is None

    @property
    def has_remaining_work(self) -> bool:
        return not self.is_finished

    def next_pending_index(self) -> int | None:
        for index, status in enumerate(self.statuses):
            if status in ("pending", "in_progress"):
                return index
        return None


def _capture_plan_progress(shared: dict[str, Any]) -> PlanProgressSnapshot:
    plan_manager = _get_plan_manager(shared)
    if isinstance(plan_manager, PlanStepManager):
        steps = plan_manager.steps
        active_step = plan_manager.current_step
    else:
        step_manager = _get_step_manager(shared)
        steps = step_manager.steps if isinstance(step_manager, StepManager) else []
        active_step = (
            step_manager.active_step if isinstance(step_manager, StepManager) else None
        )

    step_ids: tuple[str, ...] = tuple(step.step_id for step in steps)
    statuses: tuple[str, ...] = tuple(step.status for step in steps)
    active_step_id = active_step.step_id if active_step else None
    return PlanProgressSnapshot(step_ids=step_ids, statuses=statuses, active_step_id=active_step_id)


async def _ensure_active_step(
    shared: dict[str, Any],
    tracker: "WorklogTracker | None",
    *,
    phase: str | None = None,
) -> None:
    progress = _capture_plan_progress(shared)
    if progress.active_step_id or not progress.has_remaining_work:
        return
    next_index = progress.next_pending_index()
    if next_index is None:
        return
    await _set_plan_active_index(shared, tracker, next_index, phase=phase)


def _get_plan_manager(shared: dict[str, Any]) -> PlanStepManager | None:
    candidate = shared.get("_plan_manager")
    return candidate if isinstance(candidate, PlanStepManager) else None


def _get_step_manager(shared: dict[str, Any]) -> StepManager | None:
    candidate = shared.get("_step_manager")
    return candidate if isinstance(candidate, StepManager) else None


def _get_work_item_logger(shared: dict[str, Any]) -> WorkItemLogger | None:
    candidate = shared.get("_work_item_logger")
    return candidate if isinstance(candidate, WorkItemLogger) else None


def _get_summary_generator(
    shared: dict[str, Any],
    *,
    model_id: str | None = None,
    model_args: dict[str, Any] | None = None,
) -> SummaryGenerator:
    generator = shared.get("_summary_generator")
    if isinstance(generator, SummaryGenerator):
        return generator
    generator = SummaryGenerator(model_id=model_id, model_args=model_args)
    shared["_summary_generator"] = generator
    return generator


def _get_entry_snapshot(
    tracker: WorklogTracker | None, entry_id: str | None
) -> Any | None:
    if tracker is not None:
        return tracker.get_entry()
    if entry_id:
        return worklog_repository.get(entry_id)
    return None


def _export_plan_state(shared: dict[str, Any]) -> None:
    plan_manager = _get_plan_manager(shared)
    if plan_manager is None:
        return
    work_logger = _get_work_item_logger(shared)
    work_snapshot = work_logger.snapshot() if work_logger else {}
    state = plan_manager.export_state(work_snapshot)
    shared["current_step_id"] = state.get("current_step_id")
    shared["previous_step_id"] = state.get("previous_step_id")
    shared["step_state"] = state.get("step_state", {})
    shared["step_context"] = state.get("step_context", {})


def _refresh_runtime_state_from_entry(
    shared: dict[str, Any], entry: Any | None
) -> None:
    if entry is None:
        _export_plan_state(shared)
        return
    plan_manager = _get_plan_manager(shared)
    work_logger = _get_work_item_logger(shared)
    if isinstance(work_logger, WorkItemLogger):
        work_logger.reset(entry.work_nodes)
    if isinstance(plan_manager, PlanStepManager):
        plan_manager.refresh_from_steps(entry.plan_steps)
    _export_plan_state(shared)


def _ensure_runtime_helpers(
    shared: dict[str, Any],
    *,
    step_manager: StepManager,
    model_id: str | None,
    model_args: dict[str, Any] | None,
) -> tuple[PlanStepManager, WorkItemLogger]:
    plan_manager = _get_plan_manager(shared)
    if not isinstance(plan_manager, PlanStepManager) or plan_manager.step_manager is not step_manager:
        plan_manager = PlanStepManager(step_manager)
        shared["_plan_manager"] = plan_manager

    work_logger = _get_work_item_logger(shared)
    if not isinstance(work_logger, WorkItemLogger):
        work_logger = WorkItemLogger()
        shared["_work_item_logger"] = work_logger

    _get_summary_generator(
        shared,
        model_id=model_id,
        model_args=model_args,
    )
    return plan_manager, work_logger


def _strip_step_completion_markers(text: str) -> tuple[str, bool]:
    if not isinstance(text, str) or not text:
        return text, False
    pattern = re.compile(re.escape(STEP_COMPLETED_TOKEN), re.IGNORECASE)
    if not pattern.search(text):
        return text, False
    cleaned = pattern.sub("", text).strip()
    return cleaned, True


def _parse_review_message(message: str | None) -> tuple[str | None, list[str]]:
    lines = [line.strip() for line in (message or "").splitlines() if line.strip()]
    if not lines:
        return None, []
    summary = lines[0]
    actions: list[str] = []
    for line in lines[1:]:
        stripped = line.lstrip("-*•0123456789.). ").strip()
        if not stripped:
            continue
        if line.startswith(('- ', '* ', '• ', '– ')):
            actions.append(stripped)
            continue
        if re.match(r"^\d+[\.)]\s+", line):
            actions.append(stripped)
            continue
        prefix = stripped.lower()
        if prefix.startswith(('next', 'todo', 'follow', 'after', 'continue')):
            actions.append(stripped)
    return summary, actions


async def _set_plan_active_index(
    shared: dict[str, Any],
    tracker: WorklogTracker | None,
    active_index: int | None,
    *,
    phase: str | None = None,
) -> None:
    plan_manager = _get_plan_manager(shared)
    if plan_manager is not None:
        if not plan_manager.set_active_index(active_index):
            return
        if tracker is not None:
            entry = await tracker.update(
                plan_steps=plan_manager.serialize_for_patch(),
                phase=phase,
            )
            _refresh_runtime_state_from_entry(shared, entry)
        else:
            _export_plan_state(shared)
        return

    step_manager = _get_step_manager(shared)
    if not isinstance(step_manager, StepManager):
        return

    changed = step_manager.set_active_index(active_index)
    if not changed:
        return
    active_step = step_manager.active_step
    shared['current_step_id'] = active_step.step_id if active_step else None

    if tracker is None:
        active_step = step_manager.active_step
        shared['current_step_id'] = active_step.step_id if active_step else None
        return

    entry = await tracker.update(
        plan_steps=step_manager.serialize_for_patch(),
        phase=phase,
    )
    step_manager.sync_with_remote(entry.plan_steps)
    shared['current_step_id'] = None
    active_step = step_manager.active_step
    shared['current_step_id'] = active_step.step_id if active_step else None
    active_step = step_manager.active_step
    shared['current_step_id'] = active_step.step_id if active_step else None


async def _advance_plan(
    shared: dict[str, Any],
    tracker: WorklogTracker | None,
    *,
    phase: str | None = None,
) -> None:
    plan_manager = _get_plan_manager(shared)
    if plan_manager is not None:
        if not plan_manager.advance():
            LOG.info(
                "[Plan] advance() no-op current_step_id=%s total_steps=%d",
                plan_manager.current_step_id,
                len(plan_manager.steps),
            )
            return
        LOG.info(
            "[Plan] advanced to %s",
            plan_manager.current_step.step_id if plan_manager.current_step else None,
        )
        if tracker is not None:
            entry = await tracker.update(
                plan_steps=plan_manager.serialize_for_patch(),
                phase=phase,
            )
            _refresh_runtime_state_from_entry(shared, entry)
        else:
            _export_plan_state(shared)
        return

    step_manager = _get_step_manager(shared)
    if not isinstance(step_manager, StepManager):
        return
    if tracker is None:
        return
    if not step_manager.advance():
        active = step_manager.active_step.step_id if step_manager.active_step else None
        LOG.info(
            "[Plan] legacy StepManager advance() no-op active=%s len=%d",
            active,
            len(step_manager.steps),
        )
        return
    LOG.info(
        "[Plan] legacy StepManager advanced to %s",
        step_manager.active_step.step_id if step_manager.active_step else None,
    )
    entry = await tracker.update(
        plan_steps=step_manager.serialize_for_patch(),
        phase=phase,
    )
    step_manager.sync_with_remote(entry.plan_steps)


async def _complete_plan(
    shared: dict[str, Any],
    tracker: WorklogTracker | None,
    *,
    phase: str | None = None,
) -> None:
    plan_manager = _get_plan_manager(shared)
    if plan_manager is not None:
        if not plan_manager.complete_plan():
            return
        shared['current_step_id'] = None
        if tracker is not None:
            entry = await tracker.update(
                plan_steps=plan_manager.serialize_for_patch(),
                phase=phase,
            )
            _refresh_runtime_state_from_entry(shared, entry)
        else:
            _export_plan_state(shared)
        return

    step_manager = _get_step_manager(shared)
    if not isinstance(step_manager, StepManager):
        return
    if not step_manager.complete_plan():
        return
    shared['current_step_id'] = None
    if tracker is None:
        return
    entry = await tracker.update(
        plan_steps=step_manager.serialize_for_patch(),
        phase=phase,
    )
    step_manager.sync_with_remote(entry.plan_steps)


async def _log_self_reflection_node(
    tracker: WorklogTracker | None,
    entry_id: str | None,
    *,
    node_id: str,
    title: str,
    status: str,
    body: str | None = None,
    step_id: str | None = None,
) -> None:
    work_node = build_work_node(
        node_id=node_id,
        step_id=step_id,
        node_type="self_reflection",
        status=status,
        title=title,
        body=body,
    )
    if tracker is not None:
        await tracker.update(work_nodes=[work_node])
    elif entry_id:
        await worklog_controller.update_entry(
            build_worklog_patch(entry_id, work_nodes=[work_node])
        )


def _build_tool_output(
    call_id: str,
    name: str,
    payload: dict[str, Any],
) -> LitellmToolCallOutput:
    return {
        "tool_call_id": call_id,
        "role": "tool",
        "name": name,
        "content": json.dumps(payload, ensure_ascii=False),
    }


async def _handle_step_completion_call(
    shared: dict[str, Any],
    tracker: WorklogTracker | None,
    entry_id: str | None,
    call: ResolvedToolCall,
    *,
    model_id: str | None,
    model_args: dict[str, Any] | None,
) -> LitellmToolCallOutput:
    result = await _complete_current_step(
        shared,
        tracker,
        entry_id,
        declared_step_id=call.function.arguments.get("step_id") if call.function.arguments else None,
        notes=call.function.arguments.get("notes") if call.function.arguments else None,
        next_actions=call.function.arguments.get("next_actions") if call.function.arguments else None,
        model_id=model_id,
        model_args=model_args,
    )
    return _build_tool_output(call.id, call.function.name, result)


async def _complete_current_step(
    shared: dict[str, Any],
    tracker: WorklogTracker | None,
    entry_id: str | None,
    *,
    declared_step_id: str | None = None,
    notes: str | None = None,
    next_actions: Sequence[str] | None = None,
    model_id: str | None = None,
    model_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan_manager = _get_plan_manager(shared)
    step_manager = (
        plan_manager.step_manager
        if isinstance(plan_manager, PlanStepManager)
        else _get_step_manager(shared)
    )
    if not isinstance(step_manager, StepManager):
        return {
            "status": "ignored",
            "reason": "step_manager_unavailable",
        }

    active_step = (
        plan_manager.current_step
        if isinstance(plan_manager, PlanStepManager)
        else step_manager.active_step
    )
    if active_step is None:
        return {
            "status": "ignored",
            "reason": "no_active_step",
        }

    if declared_step_id and declared_step_id != active_step.step_id:
        return {
            "status": "rejected",
            "reason": "step_id_mismatch",
            "active_step_id": active_step.step_id,
        }

    entry_snapshot = _get_entry_snapshot(tracker, entry_id)
    if entry_snapshot is not None:
        _refresh_runtime_state_from_entry(shared, entry_snapshot)
        # Refresh references after state sync.
        plan_manager = _get_plan_manager(shared)
        step_manager = (
            plan_manager.step_manager
            if isinstance(plan_manager, PlanStepManager)
            else _get_step_manager(shared)
        )
        active_step = (
            plan_manager.current_step
            if isinstance(plan_manager, PlanStepManager)
            else step_manager.active_step
        )
        if active_step is None:
            return {
                "status": "ignored",
                "reason": "no_active_step",
            }

    if entry_snapshot and entry_snapshot.run_state == "awaiting_approval":
        if isinstance(plan_manager, PlanStepManager):
            _export_plan_state(shared)
        return {
            "status": "ignored",
            "reason": "plan_pending_approval",
            "active_step": active_step.step_id,
        }

    work_logger = _get_work_item_logger(shared)
    completed_step_id = active_step.step_id
    work_nodes: list[WorkNode] = []
    if isinstance(work_logger, WorkItemLogger):
        work_nodes = work_logger.nodes_for_step(completed_step_id)
    if not work_nodes and entry_snapshot is not None:
        work_nodes = [
            node
            for node in entry_snapshot.work_nodes
            if node.step_id == completed_step_id
        ]

    generator = _get_summary_generator(
        shared,
        model_id=model_id,
        model_args=model_args,
    )

    metadata = dict(getattr(entry_snapshot, "metadata", {}) or {})
    query_summary = shared.get("query_summary") or metadata.get("query_summary")

    summary_payload: Any | None = None
    summary_text: str | None = None
    if work_nodes:
        summary_payload = await generator.generate(
            work_nodes=work_nodes,
            query_summary=query_summary,
        )
        summary_text = SummaryGenerator.extract_summary_text(summary_payload)

    payload_next_actions = SummaryGenerator.extract_next_actions(summary_payload)
    final_next_actions: list[str] | None = None
    if isinstance(next_actions, Sequence) and not isinstance(next_actions, str):
        final_next_actions = [action for action in next_actions if isinstance(action, str)]
    elif payload_next_actions:
        final_next_actions = payload_next_actions

    summary_body = summary_text or (notes.strip() if isinstance(notes, str) else None)
    if not summary_body:
        summary_body = "Step completed."

    if isinstance(plan_manager, PlanStepManager):
        plan_manager.register_step_completion(
            completed_step_id,
            summary_text=summary_text,
            summary_payload=summary_payload if isinstance(summary_payload, dict) else None,
            notes=notes,
            next_actions=final_next_actions or [],
        )
        _export_plan_state(shared)

    step_index = None
    if isinstance(plan_manager, PlanStepManager):
        step_index = plan_manager.index_of(completed_step_id)
    elif isinstance(step_manager, StepManager):
        step_index = step_manager.index_of(completed_step_id)

    summary_title = (
        f"Summarizing Step {step_index + 1} results"
        if step_index is not None
        else "Summarizing step results"
    )
    await _log_self_reflection_node(
        tracker,
        entry_id,
        node_id=f"summary:{completed_step_id}",
        title=summary_title,
        status="completed",
        body=summary_body,
        step_id=completed_step_id,
    )

    await _advance_plan(shared, tracker, phase="executing")

    plan_manager_after = _get_plan_manager(shared)
    step_manager_after = (
        plan_manager_after.step_manager
        if isinstance(plan_manager_after, PlanStepManager)
        else _get_step_manager(shared)
    )
    active_step_after = None
    if isinstance(plan_manager_after, PlanStepManager):
        next_step = plan_manager_after.current_step
        active_step_after = next_step.step_id if next_step else None
    elif isinstance(step_manager_after, StepManager):
        active_step_obj = step_manager_after.active_step
        active_step_after = active_step_obj.step_id if active_step_obj else None

    if isinstance(plan_manager_after, PlanStepManager):
        _export_plan_state(shared)

    return {
        "status": "completed",
        "step_id": completed_step_id,
        "summary": summary_text,
        "notes": notes,
        "next_actions": final_next_actions,
        "active_step": active_step_after,
    }
class DefaultFlowParams(TypedDict):
    """
    Parameters expected by the default flow provided by Jupyter AI.
    """

    model_id: str

    ychat: YChat

    awareness: PersonaAwareness

    persona_id: str

    logger: logging.Logger

    model_args: dict[str, Any] | None
    """
    Custom keyword arguments forwarded to `litellm.acompletion()`. Defaults to
    `{}` if unset.
    """

    system_prompt: Optional[str]
    """
    System prompt that will be used as the first message in the list of messages
    sent to the language model. Unused if unset.
    """

    response_template: Template | None
    """
    Jinja2 template used to template the response. If one is not given,
    `DEFAULT_RESPONSE_TEMPLATE` is used.

    It should take `content: str` and `tool_call_ui_elements: str` as format arguments.
    """

    toolkit: Toolkit | None
    """
    Toolkit of tools. Unused if unset.
    """

    history_size: int | None
    """
    Number of messages preceding the message triggering this flow to include
    in the prompt as context. Defaults to 2 if unset.
    """

    room_id: str | None
    """
    Chat room identifier used to route realtime worklog updates.
    """

    plan_mode: Literal["auto", "always", "never"] | None
    """
    Optional override for planning router.
    """

class JaiAsyncNode(AsyncNode):
    """
    An AsyncNode with custom properties & helper methods used exclusively in the
    Jupyter AI extension.
    """
    
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
        # If response template was unspecified, use the default response
        # template.
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
        return self.params.get("logger")

    @property
    def room_id(self) -> str | None:
        return self.params.get("room_id")


class RootNode(JaiAsyncNode):
    """
    The root node of the default flow provided by Jupyter AI.
    """

    async def prep_async(self, shared):
        # Initialize `shared.litellm_messages` using the YChat message history
        # if it is unset.
        if not ('litellm_messages' in shared and isinstance(shared['litellm_messages'], list) and len(shared['litellm_messages']) > 0):
            shared['litellm_messages'] = self._init_litellm_messages()

        if 'worklog_entry_id' not in shared:
            entry_id = uuid4().hex
            metadata = {
                "room_id": self.room_id,
                "persona_id": self.persona_id,
            }
            metadata = {key: value for key, value in metadata.items() if value}

            latest_user_message = _latest_user_message(shared['litellm_messages'])
            query_summary = await summarize_user_query(
                latest_user_message,
                model_id=self.model_id,
                model_args=self.model_args,
            )
            if query_summary:
                metadata['query_summary'] = query_summary
                shared['query_summary'] = query_summary

            tracker = WorklogTracker(
                entry_id,
                controller=worklog_controller,
                repository=worklog_repository,
            )

            base_plan_steps = await generate_plan_steps(
                latest_user_message,
                model_id=self.model_id,
                model_args=self.model_args,
            )
            step_manager = StepManager.from_plan_steps(base_plan_steps)
            shared['_step_manager'] = step_manager
            shared['_initial_plan_step_ids'] = step_manager.initial_step_ids
            plan_manager, work_logger = _ensure_runtime_helpers(
                shared,
                step_manager=step_manager,
                model_id=self.model_id,
                model_args=self.model_args,
            )
            active_step = step_manager.active_step
            shared['current_step_id'] = active_step.step_id if active_step else None
            plan_payload = step_manager.serialize_for_patch() or None

            entry = await tracker.ensure_entry(
                summary="Agent worklog",
                plan_steps=plan_payload,
                phase="planning",
                metadata=metadata or None,
            )
            plan_manager.refresh_from_steps(entry.plan_steps)
            work_logger.reset(entry.work_nodes)
            shared['query_summary'] = metadata.get('query_summary')
            _refresh_runtime_state_from_entry(shared, entry)

            if plan_payload:
                approval_metadata = dict(entry.metadata)
                approval_metadata["approval_stage"] = "plan"
                entry = await tracker.update(
                    run_state="awaiting_approval",
                    metadata=approval_metadata or None,
                )
                plan_manager.refresh_from_steps(entry.plan_steps)
                work_logger.reset(entry.work_nodes)
                _refresh_runtime_state_from_entry(shared, entry)
            else:
                entry = tracker.get_entry() or entry

            shared['worklog_entry_id'] = entry_id
            shared['_worklog_tracker'] = tracker
            shared['worklog_markup'] = build_worklog_markup(
                entry_id=entry_id,
                payload=entry,
            )
            async def _publisher(entry_obj, _patch):
                new_markup = build_worklog_markup(entry_id=entry_id, payload=entry_obj)
                shared['worklog_markup'] = new_markup
                message_id = shared.get('prev_message_id')
                if not message_id:
                    return
                message_body = self.response_template.render(
                    {
                        "content": shared.get('latest_content', ""),
                        "tool_call_ui_elements": shared.get('latest_tool_ui', ""),
                        "worklog_ui_elements": new_markup,
                    }
                )
                self.ychat.update_message(
                    Message(
                        id=message_id,
                        body=message_body,
                        time=time.time(),
                        sender=self.persona_id,
                        raw_time=False,
                    )
                )

            worklog_controller.register_publisher(entry_id, _publisher)
            shared['_worklog_publisher'] = _publisher
        else:
            entry_id = shared['worklog_entry_id']
            tracker = shared.get('_worklog_tracker')
            if not isinstance(tracker, WorklogTracker):
                tracker = WorklogTracker(
                    entry_id,
                    controller=worklog_controller,
                    repository=worklog_repository,
                )
                shared['_worklog_tracker'] = tracker
            existing_entry = worklog_repository.get(entry_id)
            shared.setdefault(
                'worklog_markup',
                build_worklog_markup(
                    entry_id=entry_id,
                    payload=existing_entry or build_worklog_entry(entry_id),
                ),
            )
            step_manager = _get_step_manager(shared)
            if not isinstance(step_manager, StepManager):
                if existing_entry and existing_entry.plan_steps:
                    step_manager = StepManager.from_existing_steps(existing_entry.plan_steps)
                else:
                    step_manager = StepManager.from_existing_steps([])
                shared['_step_manager'] = step_manager
            plan_manager, work_logger = _ensure_runtime_helpers(
                shared,
                step_manager=step_manager,
                model_id=self.model_id,
                model_args=self.model_args,
            )
            shared.setdefault('_initial_plan_step_ids', step_manager.initial_step_ids)
            if existing_entry:
                _refresh_runtime_state_from_entry(shared, existing_entry)
                shared.setdefault(
                    'query_summary',
                    (existing_entry.metadata or {}).get('query_summary'),
                )
            else:
                _export_plan_state(shared)

        shared.setdefault('response_template', self.response_template)

        # Return `shared.litellm_messages`. This is passed as the `prep_res`
        # argument to `exec_async()`.
        return {
            "messages": shared['litellm_messages'],
            "worklog_markup": shared.get('worklog_markup', ''),
            "worklog_entry_id": shared['worklog_entry_id'],
            "shared_ref": shared,
        }
    

    def _init_litellm_messages(self) -> list[dict]:
        # Store the invoking message & the previous `params.history_size` messages
        # as `ychat_messages`.
        # TODO: ensure the invoking message is in this list
        all_messages = self.ychat.get_messages()
        ychat_messages: list[Message] = all_messages[-self.history_size - 1:]

        # Coerce each `Message` in `ychat_messages` to a dictionary following
        # the OpenAI spec, and store it as `litellm_messages`.
        litellm_messages: list[dict[str, Any]] = []
        for msg in ychat_messages:
            role = (
                "assistant"
                if msg.sender.startswith("jupyter-ai-personas::")
                else "system" if msg.sender == SYSTEM_USERNAME else "user"
            )
            litellm_messages.append({"role": role, "content": msg.body})
        
        # Insert system message as a dictionary if present.
        if self.system_prompt:
            system_litellm_message = {
                "role": "system",
                "content": self.system_prompt
            }
            litellm_messages = [system_litellm_message, *litellm_messages]

        # Return `litellm_messages`
        return litellm_messages


    async def exec_async(self, prep_res: dict[str, Any]):
        self.log.info("Running RootNode.exec_async()")
        # Gather arguments and start a reply stream via LiteLLM
        messages = list(prep_res.get('messages', []))
        worklog_markup = prep_res.get('worklog_markup', '')
        shared_ref = prep_res.get('shared_ref')
        entry_id = prep_res.get('worklog_entry_id')
        tracker = None
        if isinstance(shared_ref, dict):
            candidate_tracker = shared_ref.get('_worklog_tracker')
            if isinstance(candidate_tracker, WorklogTracker):
                tracker = candidate_tracker
            if shared_ref.pop('_tool_call_truncated', False):
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Only the first tool call from your previous response was executed. "
                            "Review the tool output before issuing the next action."
                        ),
                    }
                )
            pending_review = shared_ref.get('_awaiting_tool_review')
            if pending_review:
                review_lines = [
                    "Previous tool output summary:",
                    pending_review.get("summary") or pending_review.get("raw_output") or "(no output)",
                    "Review this result, describe any findings, and state the next action before calling another tool.",
                ]
                messages.append(
                    {
                        "role": "system",
                        "content": "\n".join(review_lines),
                    }
                )
            prompt_builder = PromptBuilder(
                plan_manager=_get_plan_manager(shared_ref),
                work_logger=_get_work_item_logger(shared_ref),
                query_summary=shared_ref.get('query_summary'),
            )
            messages = prompt_builder.build(messages)
        stream_id: str | None = None
        if isinstance(shared_ref, dict):
            candidate_message_id = shared_ref.get('display_message_id')
            if isinstance(candidate_message_id, str) and candidate_message_id:
                stream_id = candidate_message_id
        if not stream_id:
            placeholder_body = self.response_template.render(
                {
                    "content": "",
                    "tool_call_ui_elements": "",
                    "worklog_ui_elements": worklog_markup,
                }
            )
            stream_id = self.ychat.add_message(
                NewMessage(
                    sender=self.persona_id,
                    body=placeholder_body,
                )
            )
            if isinstance(shared_ref, dict):
                shared_ref['display_message_id'] = stream_id
                shared_ref['prev_message_id'] = stream_id
                shared_ref['latest_content'] = ""
                shared_ref['latest_tool_ui'] = ""
        if tracker:
            await tracker.wait_if_paused()
        tool_descriptions = self.toolkit.to_json()
        existing_tool_names = {
            tool.get("function", {}).get("name")
            for tool in tool_descriptions
            if isinstance(tool, dict)
        }
        for spec in (_STEP_COMPLETION_TOOL_SPEC, _LEGACY_STEP_COMPLETION_TOOL_SPEC):
            name = spec.get("function", {}).get("name")
            if name not in existing_tool_names:
                tool_descriptions.append(spec)
                existing_tool_names.add(name)

        reply_stream = await acompletion(
            **self.model_args,
            model=self.model_id,
            messages=messages,
            tools=tool_descriptions,
            stream=True,
        )

        # Iterate over reply stream
        content = ""
        tool_calls = ToolCallList()

        async for chunk in reply_stream:
            assert isinstance(chunk, ModelResponseStream)
            delta = chunk.choices[0].delta
            content_delta = delta.content
            toolcalls_delta = delta.tool_calls

            # Continue early if an empty chunk was emitted.
            # This sometimes happens with LiteLLM.
            if not (content_delta or toolcalls_delta):
                continue

            # Aggregate the content and tool calls from the deltas
            if content_delta:
                content += content_delta
                if (
                    entry_id
                    and isinstance(shared_ref, dict)
                    and not shared_ref.get('_plan_content_started')
                ):
                    if tracker:
                        await tracker.update(phase="executing")
                    shared_ref['_plan_content_started'] = True
            if toolcalls_delta:
                tool_calls += toolcalls_delta
                if (
                    entry_id
                    and isinstance(shared_ref, dict)
                    and not shared_ref.get('_plan_toolcalls_started')
                    and tracker
                ):
                    await tracker.update(phase="executing")
                    shared_ref['_plan_toolcalls_started'] = True
            
            # Create a new message if one does not yet exist
            if not stream_id:
                stream_id = self.ychat.add_message(NewMessage(
                    sender=self.persona_id,
                    body=""
                ))
                assert stream_id
                if isinstance(shared_ref, dict):
                    shared_ref['display_message_id'] = stream_id

            # Update the reply
            tool_ui = tool_calls.render()
            render_body = self.response_template.render({
                "content": "",
                "tool_call_ui_elements": "",
                "worklog_ui_elements": worklog_markup,
            })
            self.ychat.update_message(
                Message(
                    id=stream_id,
                    body=render_body,
                    time=time.time(),
                    sender=self.persona_id,
                    raw_time=False,
                )
            )
            if isinstance(shared_ref, dict):
                shared_ref.setdefault('latest_content', "")
                shared_ref['latest_tool_ui'] = tool_ui
                shared_ref.setdefault('response_template', self.response_template)
                shared_ref['display_message_id'] = stream_id

        truncated = False
        if len(tool_calls) > 1:
            tool_calls.truncate(1)
            truncated = True
        if truncated and isinstance(shared_ref, dict):
            shared_ref['_tool_call_truncated'] = True

        # Return message_id, content, and tool calls
        return stream_id, content, tool_calls
    
    async def post_async(self, shared, prep_res, exec_res: Tuple[str, str, ToolCallList]):
        self.log.info("Running RootNode.post_async()")
        # Assert that `shared['litellm_messages']` is of the correct type, and
        # that any tool calls returned are complete.
        message_id, content, tool_calls = exec_res
        clean_content, completion_flag = _strip_step_completion_markers(content)
        assert 'litellm_messages' in shared and isinstance(shared['litellm_messages'], list)
        assert tool_calls.complete

        if isinstance(prep_res, dict):
            shared.setdefault('worklog_markup', prep_res.get('worklog_markup', ''))
            shared.setdefault('worklog_entry_id', prep_res.get('worklog_entry_id'))

        # Add AI response to `shared['litellm_messages']`, including tool calls
        new_litellm_message = {
            "role": "assistant",
            "content": clean_content
        }
        if len(tool_calls):
            new_litellm_message['tool_calls'] = tool_calls.as_litellm_tool_calls()
        shared['litellm_messages'].append(new_litellm_message)

        # Add message ID to `shared['prev_message_id']`
        shared['prev_message_id'] = message_id
        shared['display_message_id'] = message_id

        # Add message content to `shared['prev_message_content]`
        shared['prev_message_content'] = clean_content
        shared['latest_content'] = ""

        # Add tool calls to `shared['next_tool_calls']`
        shared['next_tool_calls'] = tool_calls

        tracker_candidate = shared.get('_worklog_tracker')
        tracker_obj = tracker_candidate if isinstance(tracker_candidate, WorklogTracker) else None
        entry_id = shared.get('worklog_entry_id')
        current_step_id = shared.get('current_step_id')

        # Trigger `ToolExecutorNode` if tools were called.
        if len(tool_calls):
            if clean_content.strip():
                reasoning_title = None
                try:
                    resolved_calls = tool_calls.resolve()
                    if resolved_calls:
                        first_call = resolved_calls[0]
                        raw_title = first_call.function.arguments.get(WORK_ITEM_TITLE_ARG)
                        if isinstance(raw_title, str) and raw_title.strip():
                            reasoning_title = raw_title.strip()
                except Exception as error:
                    LOG.debug("Failed to derive reasoning title from tool call: %s", error)
                shared['_awaiting_tool_review'] = {
                    "reasoning": clean_content.strip(),
                    "reasoning_timestamp": time.time(),
                }
                reasoning_step_id = current_step_id if isinstance(current_step_id, str) else None
                if tracker_obj or entry_id:
                    await _log_self_reflection_node(
                        tracker_obj,
                        entry_id,
                        node_id=f"reasoning:{uuid4().hex}",
                        title=reasoning_title or _derive_reasoning_title(clean_content.strip()),
                        status="completed",
                        body=clean_content.strip(),
                        step_id=reasoning_step_id,
                    )
            return FLOW_SIGNAL_EXECUTE_TOOLS

        if completion_flag:
            notes_payload = clean_content or None
            result = await _complete_current_step(
                shared,
                tracker_obj,
                entry_id,
                notes=notes_payload,
                model_id=self.model_id,
                model_args=self.model_args,
            )
            shared['last_step_completion'] = result
            progress_after_completion = _capture_plan_progress(shared)
            if progress_after_completion.is_finished:
                shared['latest_content'] = clean_content
                return FLOW_SIGNAL_COMPLETE
            await _ensure_active_step(shared, tracker_obj, phase="executing")
            return FLOW_SIGNAL_CONTINUE

        pending_review = shared.get('_awaiting_tool_review')
        plan_manager = _get_plan_manager(shared)
        if pending_review and clean_content.strip():
            shared.pop('_awaiting_tool_review', None)
            summary_text, follow_up_actions = _parse_review_message(clean_content)
            review_entry = {
                "content": clean_content.strip(),
                "timestamp": time.time(),
                "tool_name": pending_review.get("tool_name"),
            }
            if summary_text:
                review_entry["summary"] = summary_text
            if pending_review.get("summary") and pending_review.get("summary") != summary_text:
                review_entry["tool_output"] = pending_review.get("summary")
            if isinstance(plan_manager, PlanStepManager) and isinstance(current_step_id, str):
                plan_manager.append_step_review(
                    current_step_id,
                    review_entry,
                    follow_up_actions,
                )
        elif clean_content.strip():
            shared['_awaiting_tool_review'] = {
                "reasoning": clean_content.strip(),
                "reasoning_timestamp": time.time(),
            }
            reasoning_step_id = current_step_id if isinstance(current_step_id, str) else None
            if tracker_obj or entry_id:
                    await _log_self_reflection_node(
                        tracker_obj,
                        entry_id,
                        node_id=f"reasoning:{uuid4().hex}",
                        title=_derive_reasoning_title(clean_content.strip()),
                        status="completed",
                        body=clean_content.strip(),
                        step_id=reasoning_step_id,
                )
        if isinstance(plan_manager, PlanStepManager) and isinstance(current_step_id, str):
            plan_manager.record_action(current_step_id, "message")
            _export_plan_state(shared)

        await _ensure_active_step(shared, tracker_obj, phase="executing")
        progress = _capture_plan_progress(shared)
        if progress.is_finished:
            shared['latest_content'] = clean_content
            return FLOW_SIGNAL_COMPLETE
        return FLOW_SIGNAL_CONTINUE

class ToolExecutorNode(JaiAsyncNode):
    """
    Node responsible for executing tool calls in the default flow.
    """


    async def prep_async(self, shared):
        self.log.info("Running ToolExecutorNode.prep_async()")
        # Extract `shared['next_tool_calls']` and the ID of the last message
        assert 'next_tool_calls' in shared and isinstance(shared['next_tool_calls'], ToolCallList)
        assert 'prev_message_id' in shared and isinstance(shared['prev_message_id'], str)
        tool_calls: ToolCallList = shared['next_tool_calls']
        resolved_calls = tool_calls.resolve()
        entry_id = shared.get('worklog_entry_id')

        tracker = shared.get('_worklog_tracker') if entry_id else None
        tracker_obj = tracker if isinstance(tracker, WorklogTracker) else None

        special_outputs: list[LitellmToolCallOutput] = []
        filtered_calls: list[ResolvedToolCall] = []
        for call in resolved_calls:
            if call.function.name in STEP_COMPLETION_TOOL_NAMES:
                output = await _handle_step_completion_call(
                    shared,
                    tracker_obj,
                    entry_id,
                    call,
                    model_id=self.model_id,
                    model_args=self.model_args,
                )
                special_outputs.append(output)
            else:
                filtered_calls.append(call)
        if special_outputs:
            setattr(tool_calls, "_complete_step_outputs", special_outputs)
        else:
            setattr(tool_calls, "_complete_step_outputs", [])
        resolved_calls = filtered_calls
        active_plan_step: PlanStep | None = None
        plan_manager = _get_plan_manager(shared)
        step_manager = _get_step_manager(shared)
        if isinstance(plan_manager, PlanStepManager):
            active_plan_step = plan_manager.current_step
        elif isinstance(step_manager, StepManager):
            active_plan_step = step_manager.active_step

        if isinstance(plan_manager, PlanStepManager) and active_plan_step and resolved_calls:
            plan_manager.record_action(
                active_plan_step.step_id,
                f"tool:{resolved_calls[0].function.name}",
            )
            _export_plan_state(shared)
        elif not isinstance(plan_manager, PlanStepManager) and isinstance(step_manager, StepManager):
            active_plan_step = step_manager.active_step

        return (
            shared['prev_message_id'],
            tool_calls,
            entry_id,
            resolved_calls,
            active_plan_step,
        )
    
    async def exec_async(
        self, prep_res: Tuple[str, ToolCallList, str | None, list, PlanStep | None]
    ) -> list[LitellmToolCallOutput]:
        self.log.info("Running ToolExecutorNode.exec_async()")
        message_id, tool_calls, entry_id, resolved_calls, active_plan_step = prep_res

        # TODO: Run 1 tool at a time?
        try:
            outputs = await run_tools(
                tool_calls,
                self.toolkit,
                entry_id=entry_id,
                resolved_calls=resolved_calls,
                active_plan_step=active_plan_step,
            )
        except WorklogStoppedError:
            self.log.info("Worklog stopped; skipping remaining tool execution.")
            if entry_id and resolved_calls:
                finished_at = datetime.now(timezone.utc).isoformat()
                cancelled_nodes = [
                    build_work_node(
                        node_id=f"work:{call.id}",
                        step_id=active_plan_step.step_id if active_plan_step else f"step:{call.id}",
                        node_type="tool_call",
                        status="cancelled",
                        title=f"Run tool {call.function.name}",
                    )
                    for call in resolved_calls
                ]
                if active_plan_step:
                    failed_steps = [active_plan_step.with_status("failed")]
                else:
                    failed_steps = [
                        build_plan_step(
                            step_id=f"step:{call.id}",
                            title=f"Run tool {call.function.name}",
                            status="failed",
                        )
                        for call in resolved_calls
                    ]
                await worklog_controller.update_entry(
                    build_worklog_patch(
                        entry_id,
                        plan_steps=failed_steps,
                        work_nodes=cancelled_nodes,
                        run_state="stopped",
                    )
                )
                for call in resolved_calls:
                    try:
                        canonical = json.dumps(
                            call.function.arguments,
                            sort_keys=True,
                            ensure_ascii=False,
                        )
                    except TypeError:
                        canonical = repr(call.function.arguments)
                    args_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                    await worklog_controller.emit_command_event(
                        entry_id,
                        {
                            "command_id": call.id,
                            "tool_name": call.function.name,
                            "args_hash": args_hash,
                            "status": "cancelled",
                            "finished_at": finished_at,
                        },
                    )
            return []

        special_outputs = getattr(tool_calls, "_complete_step_outputs", [])
        if special_outputs:
            outputs.extend(special_outputs)
            setattr(tool_calls, "_complete_step_outputs", [])

        return outputs

    async def post_async(
        self,
        shared,
        prep_res: Tuple[str, ToolCallList, str | None, list, PlanStep | None],
        exec_res: list[LitellmToolCallOutput],
    ):
        self.log.info("Running ToolExecutorNode.post_async()")

        # Update last message to include outputs
        prev_message_id = shared['prev_message_id']
        prev_message_content = shared['prev_message_content']
        tool_calls: ToolCallList = shared['next_tool_calls']
        tool_calls.render(outputs=exec_res)
        shared['latest_tool_ui'] = ""
        shared['display_message_id'] = prev_message_id

        # Add tool outputs to `shared['litellm_messages']`
        shared['litellm_messages'].extend(exec_res)

        if exec_res:
            primary_output = exec_res[0]
            tool_name = primary_output.get("name")
            review_summary = primary_output.get("content")
            summary_preview = review_summary
            if isinstance(summary_preview, str) and len(summary_preview) > 200:
                summary_preview = f"{summary_preview[:200]}…"
            pending_review = shared.get('_awaiting_tool_review')
            reasoning_preview = None
            if isinstance(pending_review, dict):
                reasoning_preview = pending_review.get("reasoning")
                if isinstance(reasoning_preview, str) and len(reasoning_preview) > 200:
                    reasoning_preview = f"{reasoning_preview[:200]}…"
            self.log.info(
                "Tool '%s' completed with summary: %s",
                tool_name or "unknown",
                summary_preview if summary_preview is not None else "<no content>",
            )
            if reasoning_preview:
                self.log.info("  ↳ preceding reasoning: %s", reasoning_preview)
            shared['_awaiting_tool_review'] = {
                "summary": review_summary,
                "reasoning": pending_review.get("reasoning") if isinstance(pending_review, dict) else None,
                "tool_name": tool_name,
                "raw_output": str(primary_output),
                "step_id": shared.get('current_step_id') if isinstance(shared.get('current_step_id'), str) else None,
                "timestamp": time.time(),
            }
            plan_manager = _get_plan_manager(shared)
            if isinstance(plan_manager, PlanStepManager) and isinstance(shared.get('current_step_id'), str):
                plan_manager.record_action(shared['current_step_id'], f"tool:{tool_name}")

        tracker_obj = shared.get('_worklog_tracker')
        tracker = tracker_obj if isinstance(tracker_obj, WorklogTracker) else None
        entry_id = shared.get('worklog_entry_id')
        entry_snapshot = _get_entry_snapshot(tracker, entry_id)
        _refresh_runtime_state_from_entry(shared, entry_snapshot)

        # Delete shared state that is now stale
        del shared['prev_message_id']
        del shared['prev_message_content']
        del shared['next_tool_calls']
        # This node will automatically return to `RootNode` after execution.

async def run_default_flow(params: DefaultFlowParams):
    # Initialize nodes
    root_node = RootNode()
    tool_executor_node = ToolExecutorNode()

    # Define state transitions
    ## Flow to ToolExecutorNode if tool calls were dispatched
    root_node - FLOW_SIGNAL_EXECUTE_TOOLS >> tool_executor_node 
    ## Always flow back to RootNode after running tools
    tool_executor_node >> root_node
    ## Loop back to RootNode when additional work remains
    root_node - FLOW_SIGNAL_CONTINUE >> root_node
    ## End the flow once all work is completed
    root_node - FLOW_SIGNAL_COMPLETE >> AsyncNode()
    
    # Initialize flow and set its parameters
    flow = AsyncFlow(start=root_node)
    flow.set_params(params)

    # Finally, run the async node
    shared_state: dict[str, Any] = {}

    success = True
    try:
        params['awareness'].set_local_state_field("isWriting", True)
        await flow.run_async(shared_state)
    except Exception as e:
        # TODO: implement error handling
        params['logger'].exception("Exception occurred while running default agent flow:")
        success = False
    finally:
        params['awareness'].set_local_state_field("isWriting", False)
        entry_id = shared_state.get('worklog_entry_id')
        tracker = shared_state.get('_worklog_tracker')
        publisher = shared_state.get('_worklog_publisher')
        final_answer = shared_state.get('latest_content')
        display_message_id = shared_state.get('display_message_id')
        response_template = (
            shared_state.get('response_template')
            or params.get('response_template')
            or Template(DEFAULT_RESPONSE_TEMPLATE)
        )
        entry_snapshot = None
        tracker_obj = tracker if isinstance(tracker, WorklogTracker) else None
        if entry_id and tracker_obj:
            entry_snapshot = tracker_obj.get_entry()
            if entry_snapshot:
                _refresh_runtime_state_from_entry(shared_state, entry_snapshot)

        plan_manager = _get_plan_manager(shared_state)
        step_manager = (
            plan_manager.step_manager
            if isinstance(plan_manager, PlanStepManager)
            else _get_step_manager(shared_state)
        )
        if isinstance(plan_manager, PlanStepManager):
            plan_steps_final = plan_manager.steps
        elif isinstance(step_manager, StepManager):
            plan_steps_final = step_manager.steps
        else:
            plan_steps_final = []

        plan_progress = _capture_plan_progress(shared_state)
        if plan_progress.has_remaining_work:
            LOG.info(
                "[Plan] flow exiting with pending steps; active=%s statuses=%s",
                plan_progress.active_step_id,
                [
                    f"{step_id}:{status}"
                    for step_id, status in zip(
                        plan_progress.step_ids, plan_progress.statuses
                    )
                ],
            )
            if entry_id and isinstance(tracker, WorklogTracker):
                entry_snapshot = entry_snapshot or tracker.get_entry()
                _refresh_runtime_state_from_entry(shared_state, entry_snapshot)
            if entry_id and publisher:
                worklog_controller.unregister_publisher(entry_id, publisher)
            return
        final_plan_step_id = None
        if isinstance(plan_manager, PlanStepManager):
            final_plan_step_id = (
                plan_manager.previous_step_id
                or (plan_manager.steps[-1].step_id if plan_manager.steps else None)
            )
        if final_plan_step_id is None and isinstance(step_manager, StepManager):
            steps = step_manager.steps
            if steps:
                final_plan_step_id = steps[-1].step_id
        if final_plan_step_id is None:
            prior = shared_state.get("previous_step_id")
            if isinstance(prior, str) and prior:
                final_plan_step_id = prior
        if final_plan_step_id is None and plan_steps_final:
            final_plan_step_id = plan_steps_final[-1].step_id


        summary_generator = _get_summary_generator(
            shared_state,
            model_id=params.get("model_id"),
            model_args=params.get("model_args"),
        )

        if entry_id and isinstance(tracker, WorklogTracker):
            entry_snapshot = tracker.get_entry()
            awaiting_plan_approval = bool(
                entry_snapshot and entry_snapshot.run_state == "awaiting_approval"
            )
            metadata_updates: dict[str, Any] | None = None
            if entry_snapshot and not awaiting_plan_approval:
                metadata_updates = dict(entry_snapshot.metadata or {})
                if (
                    summary_generator.should_generate(entry_snapshot.work_nodes)
                    and not metadata_updates.get("work_summary")
                ):
                    summary_task_id = f"summary:work-items:{entry_id}"
                    await _log_self_reflection_node(
                        tracker,
                        entry_id,
                        node_id=summary_task_id,
                        title="Summarizing work items results",
                        status="in_progress",
                        step_id=final_plan_step_id,
                    )
                    work_summary_payload = await summary_generator.generate(
                        work_nodes=entry_snapshot.work_nodes,
                        query_summary=metadata_updates.get("query_summary"),
                    )
                    if work_summary_payload is not None:
                        metadata_updates["work_summary"] = work_summary_payload
                        shared_state["work_summary"] = work_summary_payload
                        await _log_self_reflection_node(
                            tracker,
                            entry_id,
                            node_id=summary_task_id,
                            title="Summarizing work items results",
                            status="completed",
                            step_id=final_plan_step_id,
                        )
                    else:
                        await _log_self_reflection_node(
                            tracker,
                            entry_id,
                            node_id=summary_task_id,
                            title="Summarizing work items results",
                            status="failed",
                            step_id=final_plan_step_id,
                        )
            summary_text = "" if awaiting_plan_approval else (final_answer or "").strip()
            patch_phase = "finishing" if success else "executing"
            if summary_text:
                prepare_task_id = f"summary:final-message:{entry_id}"
                structure_task_id = f"summary:final-structure:{entry_id}"
                if final_plan_step_id:
                    await _log_self_reflection_node(
                        tracker,
                        entry_id,
                        node_id=f"work:final-answer:{entry_id}",
                        title="Deliver final answer",
                        status="completed",
                        body=summary_text,
                        step_id=final_plan_step_id,
                    )
                await _log_self_reflection_node(
                    tracker,
                    entry_id,
                    node_id=prepare_task_id,
                    title="Preparing final summary message",
                    status="completed",
                    step_id=final_plan_step_id,
                )
                await _log_self_reflection_node(
                    tracker,
                    entry_id,
                    node_id=structure_task_id,
                    title="Summarizing final response structure",
                    status="completed",
                    step_id=final_plan_step_id,
                )

            if success and summary_text:
                if plan_steps_final:
                    await _set_plan_active_index(
                        shared_state,
                        tracker,
                        len(plan_steps_final) - 1,
                        phase=patch_phase,
                    )
                    await _complete_plan(
                        shared_state,
                        tracker,
                        phase=patch_phase,
                    )

                entry = await tracker.update(
                    status="finished",
                    phase=patch_phase,
                    final_answer=summary_text,
                    summary=summary_text,
                    run_state="stopped",
                    metadata=metadata_updates or None,
                )
                _refresh_runtime_state_from_entry(shared_state, entry)
                shared_state['latest_content'] = summary_text or ""

                if display_message_id and response_template:
                    message_body = response_template.render(
                        {
                            "content": summary_text,
                            "tool_call_ui_elements": "",
                            "worklog_ui_elements": shared_state.get(
                                'worklog_markup', ''
                            ),
                        }
                    )
                    params['ychat'].update_message(
                        Message(
                            id=display_message_id,
                            body=message_body,
                            time=time.time(),
                            sender=params['persona_id'],
                            raw_time=False,
                        )
                    )
            else:
                patch_status = "finished" if success else "failed"
                if plan_steps_final:
                    await _set_plan_active_index(
                        shared_state,
                        tracker,
                        len(plan_steps_final) - 1,
                        phase=patch_phase,
                    )
                entry = await tracker.update(
                    status=patch_status,
                    phase=patch_phase,
                    final_answer=summary_text if success else None,
                    summary=summary_text if summary_text and success else None,
                    run_state="stopped" if success else None,
                    metadata=metadata_updates or None,
                )
                _refresh_runtime_state_from_entry(shared_state, entry)
                shared_state['latest_content'] = summary_text or ""
                if plan_steps_final:
                    await _complete_plan(
                        shared_state,
                        tracker,
                        phase=patch_phase,
                    )
            if display_message_id and summary_text and response_template:
                message_body = response_template.render(
                    {
                        "content": summary_text,
                        "tool_call_ui_elements": "",
                        "worklog_ui_elements": shared_state.get(
                            'worklog_markup', ''
                        ),
                    }
                )
                params['ychat'].update_message(
                    Message(
                        id=display_message_id,
                            body=message_body,
                            time=time.time(),
                            sender=params['persona_id'],
                            raw_time=False,
                        )
                    )
        elif entry_id:
            # Fallback in case tracker is unavailable
            summary_text = (final_answer or "").strip()
            patch_phase = "finishing" if success else "executing"
            if plan_steps_final:
                plan_updates = build_plan_progress_patch(plan_steps_final, None)
            else:
                plan_updates = []

            metadata_updates: dict[str, Any] | None = None
            work_nodes_snapshot: Sequence[WorkNode] = []
            existing_entry = worklog_repository.get(entry_id)
            awaiting_plan_approval = bool(
                existing_entry and existing_entry.run_state == "awaiting_approval"
            )
            if existing_entry and not awaiting_plan_approval:
                metadata_updates = dict(existing_entry.metadata or {})
                work_nodes_snapshot = existing_entry.work_nodes
                if (
                    summary_generator.should_generate(work_nodes_snapshot)
                    and not metadata_updates.get("work_summary")
                ):
                    summary_task_id = f"summary:work-items:{entry_id}"
                    await _log_self_reflection_node(
                        tracker=None,
                        entry_id=entry_id,
                        node_id=summary_task_id,
                        title="Summarizing work items results",
                        status="in_progress",
                        step_id=final_plan_step_id,
                    )
                    summary_payload = await summary_generator.generate(
                        work_nodes=work_nodes_snapshot,
                        query_summary=metadata_updates.get("query_summary"),
                    )
                    if summary_payload is not None:
                        metadata_updates["work_summary"] = summary_payload
                        shared_state["work_summary"] = summary_payload
                        await _log_self_reflection_node(
                            tracker=None,
                            entry_id=entry_id,
                            node_id=summary_task_id,
                            title="Summarizing work items results",
                            status="completed",
                            step_id=final_plan_step_id,
                        )
                    else:
                        await _log_self_reflection_node(
                            tracker=None,
                            entry_id=entry_id,
                            node_id=summary_task_id,
                            title="Summarizing work items results",
                            status="failed",
                            step_id=final_plan_step_id,
                        )

            if summary_text and not awaiting_plan_approval:
                prepare_task_id = f"summary:final-message:{entry_id}"
                structure_task_id = f"summary:final-structure:{entry_id}"
                if final_plan_step_id:
                    await _log_self_reflection_node(
                        tracker=None,
                        entry_id=entry_id,
                        node_id=f"work:final-answer:{entry_id}",
                        title="Deliver final answer",
                        status="completed",
                        body=summary_text,
                        step_id=final_plan_step_id,
                    )
                await _log_self_reflection_node(
                    tracker=None,
                    entry_id=entry_id,
                    node_id=prepare_task_id,
                    title="Preparing final summary message",
                    status="completed",
                    step_id=final_plan_step_id,
                )
                await _log_self_reflection_node(
                    tracker=None,
                    entry_id=entry_id,
                    node_id=structure_task_id,
                    title="Summarizing final response structure",
                    status="completed",
                    step_id=final_plan_step_id,
                )

            if success and summary_text:
                final_patch = build_worklog_patch(
                    entry_id,
                    status="finished",
                    phase=patch_phase,
                    plan_steps=plan_updates or None,
                    final_answer=summary_text,
                    summary=summary_text,
                    run_state="stopped",
                    metadata=metadata_updates or None,
                )

                entry = await worklog_controller.update_entry(final_patch)
                _refresh_runtime_state_from_entry(shared_state, entry)
                shared_state['latest_content'] = summary_text or ""

                if display_message_id and response_template:
                    message_body = response_template.render(
                        {
                            "content": summary_text,
                            "tool_call_ui_elements": "",
                            "worklog_ui_elements": shared_state.get(
                                'worklog_markup', ''
                            ),
                        }
                    )
                    params['ychat'].update_message(
                        Message(
                            id=display_message_id,
                            body=message_body,
                            time=time.time(),
                            sender=params['persona_id'],
                            raw_time=False,
                        )
                    )
            else:
                entry = await worklog_controller.update_entry(
                    build_worklog_patch(
                        entry_id,
                        status="finished" if success else "failed",
                        phase=patch_phase,
                        plan_steps=plan_updates or None,
                        final_answer=summary_text if success else None,
                        summary=summary_text if summary_text and success else None,
                        run_state="stopped" if success else None,
                        metadata=metadata_updates or None,
                    )
                )
                _refresh_runtime_state_from_entry(shared_state, entry)
                shared_state['latest_content'] = summary_text or ""

            if display_message_id and summary_text and response_template:
                message_body = response_template.render(
                    {
                        "content": summary_text,
                        "tool_call_ui_elements": "",
                        "worklog_ui_elements": shared_state.get(
                            'worklog_markup', ''
                        ),
                    }
                )
                params['ychat'].update_message(
                    Message(
                        id=display_message_id,
                        body=message_body,
                        time=time.time(),
                        sender=params['persona_id'],
                        raw_time=False,
                    )
                )
        if entry_id and publisher:
            worklog_controller.unregister_publisher(entry_id, publisher)
