from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence

from jupyter_ai.tools.jlab_command_tool import execute_jlab_command
from jupyter_ai.workflow.common.tool_actions import parse_action_panels
from jupyter_ai.workflow.common.ui import build_action_panel_markup
from jupyter_ai.workflow.common.services import get_services


@dataclass(frozen=True, slots=True)
class ActionAwaitDirective:
    command_id: str
    args: Mapping[str, Any]
    timeout: float | None = None
    panel_payload: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class InteractionRenderResult:
    tool_markup: list[str]
    await_directives: list[ActionAwaitDirective]


class InteractiveActionRelay:
    """
    Coordinates interactive action panels emitted by tools.

    - Collects panels from tool outputs.
    - Renders markup for tool/answer surfaces.
    - Awaits user acknowledgement when required.
    """

    def __init__(self, shared: MutableMapping[str, Any]) -> None:
        self._shared = shared

    def handle_tool_outputs(
        self,
        *,
        entry_id: str | None,
        outputs: Sequence[Mapping[str, Any]],
    ) -> InteractionRenderResult:
        panels = parse_action_panels(outputs)
        tool_markup: list[str] = []
        answer_markup: list[str] = []
        await_directives: list[ActionAwaitDirective] = []
        if not panels or not isinstance(entry_id, str) or not entry_id:
            return InteractionRenderResult(tool_markup, await_directives)

        for panel in panels:
            panel_payload = panel.to_payload()
            markup = build_action_panel_markup(
                entry_id=entry_id,
                panel=panel_payload,
            )
            placement = panel.placement.lower()
            if placement == "answer":
                answer_markup.append(markup)
            else:
                tool_markup.append(markup)

            if panel.await_command:
                args = dict(panel.await_args or {})
                args.setdefault("panelId", panel.panel_id)
                await_directives.append(
                    ActionAwaitDirective(
                        command_id=panel.await_command,
                        args=args,
                        timeout=panel.await_timeout,
                        panel_payload=panel_payload,
                    )
                )

        if answer_markup:
            bucket = self._shared.setdefault("_answer_action_panels", [])
            if isinstance(bucket, list):
                bucket.extend(answer_markup)

        return InteractionRenderResult(tool_markup, await_directives)

    async def await_directives(
        self,
        *,
        entry_id: str | None,
        directives: Sequence[ActionAwaitDirective],
    ) -> None:
        if not directives or not isinstance(entry_id, str) or not entry_id:
            return
        services = get_services(self._shared)
        worklog_service = services.worklog()
        for directive in directives:
            timeout = directive.timeout if directive.timeout and directive.timeout > 0 else 600.0
            await self._log_panel_event(
                worklog_service,
                entry_id=entry_id,
                directive=directive,
                status="awaiting_user",
            )
            try:
                await execute_jlab_command(
                    directive.command_id,
                    dict(directive.args),
                    entry_id=entry_id,
                    timeout=timeout,
                )
            except Exception:
                await self._log_panel_event(
                    worklog_service,
                    entry_id=entry_id,
                    directive=directive,
                    status="failed",
                )
                continue
            await self._log_panel_event(
                worklog_service,
                entry_id=entry_id,
                directive=directive,
                status="completed",
            )

    def consume_answer_markup(self) -> str:
        bucket = self._shared.pop("_answer_action_panels", None)
        if isinstance(bucket, list) and bucket:
            return "".join(bucket)
        return ""

    async def _log_panel_event(
        self,
        worklog_service: Any,
        *,
        entry_id: str,
        directive: ActionAwaitDirective,
        status: str,
    ) -> None:
        if (
            worklog_service is None
            or not isinstance(directive.panel_payload, Mapping)
            or not directive.panel_payload
        ):
            return
        try:
            await worklog_service.record_action_panel_event(
                entry_id=entry_id,
                panel_payload=dict(directive.panel_payload),
                status=status,
            )
        except Exception:
            # Logging failures should not block the main workflow.
            return
