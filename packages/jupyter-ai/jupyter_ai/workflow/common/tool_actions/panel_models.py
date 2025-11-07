from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from uuid import uuid4


ACTION_PANEL_COMPONENT = "jai.action_panel"


@dataclass(frozen=True, slots=True)
class LabCommandSpec:
    """Describes a JupyterLab command invocation."""

    command_id: str
    arguments: Mapping[str, Any]

    def to_payload(self) -> Mapping[str, Any]:
        return {
            "type": "jupyterlab_command",
            "command_id": self.command_id,
            "args": dict(self.arguments),
        }


@dataclass(frozen=True, slots=True)
class UserActionButton:
    """Definition of a single user-triggered action."""

    action_id: str
    label: str
    description: str | None
    command: LabCommandSpec

    def to_payload(self) -> Mapping[str, Any]:
        payload = {
            "action_id": self.action_id,
            "label": self.label,
            "command": self.command.to_payload(),
        }
        if self.description:
            payload["description"] = self.description
        return payload


@dataclass(frozen=True, slots=True)
class UserActionPanel:
    """Collection of related user actions rendered as a card."""

    panel_id: str
    title: str
    description: str | None
    actions: tuple[UserActionButton, ...]
    completion_label: str | None = None
    placement: str = "tool"
    await_command: str | None = None
    await_args: Mapping[str, Any] | None = None
    await_timeout: float | None = None

    def to_payload(self) -> Mapping[str, Any]:
        payload = {
            "component": ACTION_PANEL_COMPONENT,
            "panel_id": self.panel_id,
            "title": self.title,
            "actions": [action.to_payload() for action in self.actions],
            "placement": self.placement,
        }
        if self.description:
            payload["description"] = self.description
        if self.completion_label:
            payload["completion"] = {"label": self.completion_label}
        if self.await_command:
            payload["await"] = {
                "command_id": self.await_command,
                "args": dict(self.await_args or {}),
                "timeout": self.await_timeout,
            }
        return payload


def _ensure_action_id(value: str | None) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else uuid4().hex


def _ensure_panel_id(value: str | None) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else uuid4().hex


def _build_lab_command(spec: Mapping[str, Any]) -> LabCommandSpec:
    command_id = spec.get("command_id") or spec.get("id")
    if not isinstance(command_id, str) or not command_id.strip():
        raise ValueError("User action command payload must include command_id")
    args = spec.get("args") or spec.get("arguments") or {}
    if not isinstance(args, Mapping):
        raise ValueError("User action command args must be a mapping")
    return LabCommandSpec(command_id=command_id.strip(), arguments=dict(args))


def _build_action(button: Mapping[str, Any]) -> UserActionButton:
    label = button.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("User action button requires a label")
    description = button.get("description")
    if isinstance(description, str):
        description = description.strip() or None
    command_payload = button.get("command")
    if not isinstance(command_payload, Mapping):
        raise ValueError("User action button requires a command payload")
    command_type = command_payload.get("type") or "jupyterlab_command"
    if command_type != "jupyterlab_command":
        raise ValueError(f"Unsupported user action command type: {command_type!r}")
    spec = _build_lab_command(command_payload)
    return UserActionButton(
        action_id=_ensure_action_id(button.get("action_id")),
        label=label.strip(),
        description=description,
        command=spec,
    )


def parse_action_panels(outputs: Sequence[Any]) -> list[UserActionPanel]:
    """
    Extract user-action panels from tool call outputs.

    Each panel must be encoded as JSON with ``component`` equal to
    ``jai.action_panel`` to avoid colliding with regular tool responses.
    """

    panels: list[UserActionPanel] = []
    for output in outputs:
        content = output.get("content") if isinstance(output, Mapping) else None
        for payload in _extract_panel_payloads(content):
            panel = _build_user_action_panel(payload)
            if panel is not None:
                panels.append(panel)
    return panels


def _extract_panel_payloads(content: Any) -> list[Mapping[str, Any]]:
    payloads: list[Mapping[str, Any]] = []
    queue: list[Mapping[str, Any]] = []
    candidate = _ensure_mapping(content)
    if candidate:
        queue.append(candidate)

    while queue:
        node = queue.pop()
        if node.get("component") == ACTION_PANEL_COMPONENT:
            payloads.append(node)
            continue
        for key in ("panel", "action_panel"):
            nested = node.get(key)
            nested_map = _ensure_mapping(nested)
            if nested_map:
                queue.append(nested_map)
        for key in ("panels", "action_panels"):
            nested_seq = node.get(key)
            if isinstance(nested_seq, Sequence):
                for item in nested_seq:
                    nested_map = _ensure_mapping(item)
                    if nested_map:
                        queue.append(nested_map)
        meta = node.get("meta")
        if isinstance(meta, Mapping):
            queue.append(meta)
        data = node.get("data")
        if isinstance(data, Mapping):
            queue.append(data)
    return payloads


def _ensure_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except Exception:
            return None
        if isinstance(decoded, Mapping):
            return decoded
    return None


def _build_user_action_panel(payload: Mapping[str, Any]) -> UserActionPanel | None:
    component = payload.get("component")
    if component != ACTION_PANEL_COMPONENT:
        return None
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    description = payload.get("description")
    if isinstance(description, str):
        description = description.strip() or None
    actions_payload = payload.get("actions") or []
    if not isinstance(actions_payload, Sequence) or not actions_payload:
        return None
    try:
        actions = tuple(
            _build_action(button) for button in actions_payload if isinstance(button, Mapping)
        )
    except ValueError:
        return None
    if not actions:
        return None
    completion_label = None
    completion = payload.get("completion")
    if isinstance(completion, Mapping):
        label_value = completion.get("label")
        if isinstance(label_value, str):
            completion_label = label_value.strip() or None
    placement = payload.get("placement") or payload.get("target") or "tool"
    if not isinstance(placement, str) or not placement.strip():
        placement = "tool"
    await_command = None
    await_args: Mapping[str, Any] | None = None
    await_timeout: float | None = None
    await_payload = payload.get("await")
    if isinstance(await_payload, Mapping):
        command_id = await_payload.get("command_id")
        if isinstance(command_id, str) and command_id.strip():
            await_command = command_id.strip()
            args = await_payload.get("args")
            if isinstance(args, Mapping):
                await_args = dict(args)
            timeout_value = await_payload.get("timeout")
            if isinstance(timeout_value, (int, float)):
                await_timeout = float(timeout_value)
    return UserActionPanel(
        panel_id=_ensure_panel_id(payload.get("panel_id")),
        title=title.strip(),
        description=description,
        actions=actions,
        completion_label=completion_label,
        placement=placement.strip(),
        await_command=await_command,
        await_args=await_args,
        await_timeout=await_timeout,
    )
