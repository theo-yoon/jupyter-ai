from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple
import json

from jinja2 import Template

from .litellm_lib.toolcall_renderer import serialize_tool_call

PlanActionType = Literal['add_tasks', 'update_tasks']
WorklogActionType = Literal['log_entries']
CommandActionType = Literal['run_command']
FinalActionType = Literal['final_summary']


@dataclass
class TaskAttempt:
    status: Literal['pending', 'in_progress', 'success', 'failed']
    detail: Optional[str] = None


@dataclass
class TaskPayload:
    id: str
    title: str
    status: Literal['pending', 'in_progress', 'success', 'failed', 'blocked']
    description: Optional[str] = None
    attempts: List[TaskAttempt] = field(default_factory=list)


@dataclass
class PlanAction:
    action: PlanActionType
    tasks: List[TaskPayload]


@dataclass
class WorklogEntry:
    log_id: str
    task_id: Optional[str]
    status: Literal['info', 'running', 'success', 'failed']
    description: str
    detail: Optional[str] = None


@dataclass
class WorklogAction:
    action: WorklogActionType
    entries: List[WorklogEntry]


@dataclass
class FinalSummaryAction:
    action: FinalActionType
    outcome: Literal['success', 'partial', 'failed']
    headline: str
    details: Optional[str] = None
    completed_tasks: List[str] = field(default_factory=list)
    blocked_tasks: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)


@dataclass
class RunCommandAction:
    action: CommandActionType
    command_id: str
    args: dict[str, Any]
    summary: Optional[str] = None
    auto_approve: bool = True
    success_message: Optional[str] = None
    failure_message: Optional[str] = None


AgentAction = PlanAction | WorklogAction | FinalSummaryAction | RunCommandAction

JAI_TOOL_CALL_TEMPLATE = Template(
    """
{% for props in props_list %}
<jai-tool-call {{props | xmlattr}}>
</jai-tool-call>
{% endfor %}
""".strip()
)


plan_state: Dict[str, Dict[str, TaskPayload]] = {}
worklog_state: Dict[str, Dict[str, WorklogEntry]] = {}
final_summary_state: Dict[str, FinalSummaryAction] = {}
command_state: Dict[str, Dict[str, RunCommandAction]] = {}


def _normalize_task_status(status: Optional[str]) -> str:
    if not status:
        return 'in_progress'
    normalized = status.lower()
    mapping = {
        'pending': 'pending',
        'not_started': 'pending',
        'waiting': 'pending',
        'running': 'in_progress',
        'in_progress': 'in_progress',
        'started': 'in_progress',
        'success': 'success',
        'completed': 'success',
        'done': 'success',
        'failed': 'failed',
        'error': 'failed',
        'blocked': 'failed'
    }
    return mapping.get(normalized, 'in_progress')


def _merge_task(existing: TaskPayload, new: TaskPayload) -> TaskPayload:
    existing.title = new.title or existing.title
    if new.description:
        existing.description = new.description
    existing.status = _normalize_task_status(new.status) or existing.status
    if new.attempts:
        existing.attempts = new.attempts
    return existing


def _ensure_task(tasks: Dict[str, TaskPayload], task_id: str, title: Optional[str] = None) -> TaskPayload:
    task = tasks.get(task_id)
    if task is None:
        task = TaskPayload(
            id=task_id,
            title=title or task_id,
            status='pending',
            description=None,
            attempts=[]
        )
        tasks[task_id] = task
    return task


def _record_attempt(task: TaskPayload, status: Optional[str], detail: Optional[str]) -> None:
    normalized = _normalize_task_status(status)
    task.attempts.append(TaskAttempt(status=normalized, detail=detail))
    if normalized in {'success', 'failed'}:
        task.status = normalized
    elif normalized == 'in_progress' and task.status not in {'success', 'failed'}:
        task.status = normalized


def _extract_action_objects(raw_text: str) -> tuple[list[dict], str]:
    objects: list[dict] = []
    segments: list[str] = []
    depth = 0
    start: int | None = None
    in_string = False
    escape = False
    last_index = 0
    for idx, ch in enumerate(raw_text):
        if ch == '\\' and not escape:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
        if not in_string:
            if ch == '{':
                if depth == 0:
                    if idx > last_index:
                        segments.append(raw_text[last_index:idx])
                    start = idx
                depth += 1
            elif ch == '}' and depth:
                depth -= 1
                if depth == 0 and start is not None:
                    segment = raw_text[start:idx + 1]
                    try:
                        obj = json.loads(segment)
                    except json.JSONDecodeError:
                        segments.append(segment)
                    else:
                        if isinstance(obj, dict) and obj.get('action'):
                            objects.append(obj)
                        else:
                            segments.append(segment)
                    last_index = idx + 1
                    start = None
        if escape:
            escape = False
    if last_index < len(raw_text):
        segments.append(raw_text[last_index:])
    filtered = ''.join(segments)
    return objects, filtered


def _build_actions(payloads: list[dict]) -> List[AgentAction]:
    actions: List[AgentAction] = []
    for payload in payloads:
        kind = payload.get('action')
        if kind in ('add_tasks', 'update_tasks'):
            raw_tasks = payload.get('tasks', [])
            if isinstance(raw_tasks, str):
                try:
                    raw_tasks = json.loads(raw_tasks)
                except Exception:
                    raw_tasks = []
            if not isinstance(raw_tasks, list):
                continue
            tasks = []
            for item in raw_tasks:
                if not isinstance(item, dict):
                    continue
                try:
                    task = TaskPayload(
                        id=item['id'],
                        title=item['title'],
                        status=item.get('status', 'pending'),
                        description=item.get('description'),
                        attempts=[
                            TaskAttempt(status=attempt.get('status', 'pending'), detail=attempt.get('detail'))
                            for attempt in item.get('attempts', [])
                            if isinstance(attempt, dict)
                        ]
                    )
                except KeyError:
                    continue
                tasks.append(task)
            if tasks:
                actions.append(PlanAction(action=kind, tasks=tasks))
        elif kind == 'log_entries':
            raw_entries = payload.get('entries', [])
            if isinstance(raw_entries, str):
                try:
                    raw_entries = json.loads(raw_entries)
                except Exception:
                    raw_entries = []
            if not isinstance(raw_entries, list):
                continue
            entries = []
            for item in raw_entries:
                if not isinstance(item, dict):
                    continue
                try:
                    entry = WorklogEntry(
                        log_id=item['log_id'],
                        task_id=item.get('task_id'),
                        status=item.get('status', 'info'),
                        description=item['description'],
                        detail=item.get('detail')
                    )
                except KeyError:
                    continue
                entries.append(entry)
            if entries:
                actions.append(WorklogAction(action='log_entries', entries=entries))
        elif kind == 'final_summary':
            try:
                actions.append(
                    FinalSummaryAction(
                        action='final_summary',
                        outcome=payload.get('outcome', 'success'),
                        headline=payload['headline'],
                        details=payload.get('details'),
                        completed_tasks=payload.get('completed_tasks', []),
                        blocked_tasks=payload.get('blocked_tasks', []),
                        next_steps=payload.get('next_steps', []),
                    )
                )
            except KeyError:
                continue
        elif kind == 'run_command':
            command_id = payload.get('command_id') or payload.get('commandId')
            if not isinstance(command_id, str):
                continue
            args = payload.get('args', {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if not isinstance(args, dict):
                continue
            auto_raw = payload.get('auto_approve', payload.get('autoApprove'))
            if isinstance(auto_raw, str):
                auto_approve = auto_raw.lower() not in ('false', '0', 'no')
            elif auto_raw is not None:
                auto_approve = bool(auto_raw)
            else:
                auto_approve = True
            success_message = payload.get('success_message', payload.get('successMessage'))
            failure_message = payload.get('failure_message', payload.get('failureMessage'))
            actions.append(
                RunCommandAction(
                    action='run_command',
                    command_id=command_id,
                    args=args,
                    summary=payload.get('summary') if isinstance(payload.get('summary'), str) else None,
                    auto_approve=auto_approve,
                    success_message=success_message if isinstance(success_message, str) else None,
                    failure_message=failure_message if isinstance(failure_message, str) else None,
                )
            )
    return actions


class _SyntheticFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _SyntheticToolCall:
    def __init__(self, call_id: str, name: str, arguments: str, index: int):
        self.id = call_id
        self.index = index
        self.type = 'function'
        self.function = _SyntheticFunction(name, arguments)


def process_agent_output(raw_text: str, room_id: Optional[str]) -> Tuple[str, str]:
    payloads, visible_content = _extract_action_objects(raw_text)
    actions = _build_actions(payloads)

    scoped_room = room_id or 'global'
    tasks: Dict[str, TaskPayload] = dict(plan_state.get(scoped_room, {}))
    worklog_map: Dict[str, WorklogEntry] = dict(worklog_state.get(scoped_room, {}))
    worklog_order: List[str] = list(worklog_map.keys())
    final_summary: Optional[FinalSummaryAction] = final_summary_state.get(scoped_room)
    commands = command_state.get(scoped_room, {})

    for action in actions:
        if isinstance(action, PlanAction):
            for task in action.tasks:
                existing = tasks.get(task.id)
                normalized_status = _normalize_task_status(task.status)
                incoming = TaskPayload(
                    id=task.id,
                    title=task.title,
                    status=normalized_status,
                    description=task.description,
                    attempts=task.attempts[:]
                )
                if existing:
                    _merge_task(existing, incoming)
                else:
                    tasks[task.id] = incoming
        elif isinstance(action, WorklogAction):
            for entry in action.entries:
                if entry.log_id not in worklog_map:
                    worklog_order.append(entry.log_id)
                worklog_map[entry.log_id] = entry
                if entry.task_id:
                    task = _ensure_task(tasks, entry.task_id)
                    _record_attempt(task, entry.status, entry.description or entry.detail)
        elif isinstance(action, FinalSummaryAction):
            final_summary = action
        elif isinstance(action, RunCommandAction):
            commands[action.command_id] = action

    plan_state[scoped_room] = tasks
    worklog_state[scoped_room] = worklog_map
    if final_summary:
        final_summary_state[scoped_room] = final_summary
    else:
        final_summary = final_summary_state.get(scoped_room)
    if commands:
        command_state[scoped_room] = commands

    props_list: List[dict[str, Any]] = []
    index_counter = 0

    if tasks:
        payload = {
            "tasks": [
                {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status,
                    "description": task.description,
                    "attempts": [
                        {"status": attempt.status, "detail": attempt.detail}
                        for attempt in task.attempts
                    ],
                }
                for task in tasks.values()
            ]
        }
        call = _SyntheticToolCall(
            f"{scoped_room}::advanced_plan_summary",
            'advanced_plan_summary',
            json.dumps(payload),
            index_counter,
        )
        props = serialize_tool_call(call, None, room_id)
        props['output'] = json.dumps(payload)
        props_list.append(props)
        index_counter += 1

    if worklog_order:
        entries_payload = []
        for log_id in worklog_order:
            entry = worklog_map[log_id]
            entries_payload.append(
                {
                    "log_id": entry.log_id,
                    "task_id": entry.task_id,
                    "status": entry.status,
                    "description": entry.description,
                    "detail": entry.detail,
                }
            )
        payload = {"entries": entries_payload}
        call = _SyntheticToolCall(
            f"{scoped_room}::advanced_plan_worklog",
            'advanced_plan_worklog',
            json.dumps(payload),
            index_counter,
        )
        props = serialize_tool_call(call, None, room_id)
        props['output'] = json.dumps(payload)
        props_list.append(props)
        index_counter += 1

    if final_summary:
        payload = {
            "outcome": final_summary.outcome,
            "headline": final_summary.headline,
            "details": final_summary.details,
            "completed_tasks": final_summary.completed_tasks,
            "blocked_tasks": final_summary.blocked_tasks,
            "next_steps": final_summary.next_steps,
        }
        call = _SyntheticToolCall(
            f"{scoped_room}::advanced_plan_final_summary",
            'advanced_plan_final_summary',
            json.dumps(payload),
            index_counter,
        )
        props = serialize_tool_call(call, None, room_id)
        props['output'] = json.dumps(payload)
        props_list.append(props)
        index_counter += 1

    if commands:
        for command in commands.values():
            command_payload = {
                "type": "jupyterlab-command",
                "commandId": command.command_id,
                "args": command.args,
                "summary": command.summary,
                "autoApprove": command.auto_approve,
                "successMessage": command.success_message,
                "failureMessage": command.failure_message,
                "status": "pending"
            }
            props_list.append({
                "tool_id": f"{scoped_room}::cmd::{command.command_id}",
                "type": "function",
                "function_name": "request_jupyterlab_command",
                "function_args": json.dumps({
                    "command_id": command.command_id,
                    "args": command.args,
                    "summary": command.summary,
                    "auto_approve": command.auto_approve,
                    "success_message": command.success_message,
                    "failure_message": command.failure_message
                }),
                "index": index_counter,
                "output": json.dumps(command_payload),
                "room_id": room_id
            })
            index_counter += 1

    tool_html = JAI_TOOL_CALL_TEMPLATE.render({"props_list": props_list}) if props_list else ""
    return visible_content.strip(), tool_html


def reset_command_state(room_id: Optional[str]) -> None:
    scoped = room_id or 'global'
    command_state.pop(scoped, None)


def complete_command(room_id: Optional[str], command_id: str) -> None:
    scoped = room_id or 'global'
    commands = command_state.get(scoped)
    if not commands:
        return
    commands.pop(command_id, None)
    if not commands:
        command_state.pop(scoped, None)


def parse_agent_actions(raw_text: str) -> List[AgentAction]:
    payloads, _ = _extract_action_objects(raw_text)
    return _build_actions(payloads)


def reset_plan_state(room_id: Optional[str]) -> None:
    scoped = room_id or 'global'
    plan_state.pop(scoped, None)
    worklog_state.pop(scoped, None)
    final_summary_state.pop(scoped, None)
