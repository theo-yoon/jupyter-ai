from __future__ import annotations

import json
from typing import Any, MutableMapping, Sequence

from jupyter_ai.litellm_lib import LitellmToolCallOutput
from jupyter_ai.litellm_lib.toolcall_list import JAI_TOOL_CALL_TEMPLATE
from jupyter_ai.litellm_lib.types import JaiToolCallProps

from .tool_run_store import ToolRunStore, ToolRunView


def _stringify_output(content: Any) -> str:
    if isinstance(content, str):
        text = content.strip()
        return text[:5000] if len(text) > 5000 else text
    try:
        serialized = json.dumps(content, ensure_ascii=False, indent=2)
    except TypeError:
        serialized = repr(content)
    return serialized[:5000]


class ToolResultRecorder:
    """
    Persists rendered `<jai-tool-call>` elements plus lightweight metadata so
    downstream services can reuse the UI in final responses.
    """

    def __init__(self, shared: MutableMapping[str, Any]) -> None:
        self._shared = shared
        self._store = ToolRunStore(shared)

    # ------------------------------------------------------------------ helpers
    def _outputs_by_id(
        self, outputs: Sequence[LitellmToolCallOutput]
    ) -> dict[str, LitellmToolCallOutput]:
        mapping: dict[str, LitellmToolCallOutput] = {}
        for output in outputs:
            call_id = output.get("tool_call_id")
            if isinstance(call_id, str) and call_id:
                mapping[call_id] = output
        return mapping

    def _render_markup(self, props: JaiToolCallProps) -> str:
        return JAI_TOOL_CALL_TEMPLATE.render({"props_list": [props]}).strip()

    def _resolve_label(
        self, props: JaiToolCallProps, output: LitellmToolCallOutput | None
    ) -> str:
        if isinstance(props.get("function_name"), str) and props["function_name"]:
            return props["function_name"]  # type: ignore[return-value]
        if output and isinstance(output.get("name"), str) and output["name"]:
            return output["name"]
        return "tool_call"

    def _resolve_summary(self, output: LitellmToolCallOutput | None) -> str | None:
        if not output:
            return None
        content = output.get("content")
        if content is None:
            return None
        return _stringify_output(content)

    # ------------------------------------------------------------------ recording
    def record_batch(
        self,
        *,
        props_list: Sequence[JaiToolCallProps],
        outputs: Sequence[LitellmToolCallOutput],
        active_plan_step: Any | None,
    ) -> None:
        if not props_list:
            return

        step_id = getattr(active_plan_step, "step_id", None) if active_plan_step else None
        if step_id is not None and not isinstance(step_id, str):
            step_id = str(step_id)
        step_title = getattr(active_plan_step, "title", None) if active_plan_step else None
        if step_title is not None and not isinstance(step_title, str):
            step_title = str(step_title)

        outputs_by_id = self._outputs_by_id(outputs)
        records: list[ToolRunView] = []

        for props in props_list:
            call_id = props.get("id")
            if not isinstance(call_id, str) or not call_id:
                continue
            markup = self._render_markup(props)
            output = outputs_by_id.get(call_id)
            label = self._resolve_label(props, output)
            summary = self._resolve_summary(output)
            status = "completed" if output else "pending"
            records.append(
                ToolRunView(
                    tool_call_id=call_id,
                    label=label,
                    markup=markup,
                    summary=summary,
                    step_id=step_id,
                    step_title=step_title,
                    status=status,
                )
            )

        if records:
            self._store.save_many(records)

    # ------------------------------------------------------------------- queries
    def runs_for_step(self, step_id: str | None) -> list[ToolRunView]:
        return self._store.for_step(step_id)

    def runs_without_step(self) -> list[ToolRunView]:
        return self._store.without_step()

    def all_runs(self) -> list[ToolRunView]:
        return self._store.all()

    def get_run(self, tool_call_id: str) -> ToolRunView | None:
        return self._store.get(tool_call_id)


__all__ = ["ToolResultRecorder", "ToolRunView"]
