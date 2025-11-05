from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Sequence

from litellm import acompletion
from litellm.exceptions import JSONSchemaValidationError

from jupyter_ai.worklog.work_nodes import WorkNode

WORK_SUMMARY_SYSTEM_PROMPT = (
    "You are an analytical assistant that reviews an agent's worklog. "
    "Produce a concise, structured summary that helps the agent recall key actions, "
    "outcomes, and follow-up considerations."
)

WORK_SUMMARY_USER_TEMPLATE = (
    "Original request summary (if available): {query_summary}\n\n"
    "Executed work items:\n{work_items}\n\n"
    "Return a JSON object with:\n"
    '  - "overall_summary": A short paragraph.\n'
    '  - "items": array of objects with fields "step_id", "title", "status", and "details".\n'
    '  - "next_actions": optional array of recommended follow-up tasks (strings).\n'
    "Keep details concise and actionable."
)


class SummaryGenerator:
    """LLM-powered summaries for completed steps and worklogs."""

    def __init__(self, model_id: str | None, model_args: dict[str, Any] | None = None) -> None:
        self._model_id = model_id
        self._model_args = dict(model_args or {})

    @property
    def has_model(self) -> bool:
        return bool(self._model_id)

    async def generate(
        self,
        *,
        work_nodes: Sequence[WorkNode],
        query_summary: str | None = None,
    ) -> Any | None:
        if not self._model_id or not work_nodes:
            return None

        payload_args = deepcopy(self._model_args)
        payload_args.setdefault("temperature", 0.2)
        payload_args.setdefault("max_tokens", 512)
        if "response_format" not in payload_args:
            payload_args["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "WorkSummary",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "overall_summary": {"type": "string"},
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "step_id": {"type": "string"},
                                        "title": {"type": "string"},
                                        "status": {"type": "string"},
                                        "details": {"type": "string"},
                                    },
                                    "required": ["step_id", "title", "status", "details"],
                                    "additionalProperties": False,
                                },
                            },
                            "next_actions": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["overall_summary", "items"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            }

        context = format_work_nodes_for_summary(work_nodes)
        messages = [
            {"role": "system", "content": WORK_SUMMARY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": WORK_SUMMARY_USER_TEMPLATE.format(
                    query_summary=query_summary or "Unavailable",
                    work_items=context,
                ),
            },
        ]

        try:
            response = await acompletion(
                model=self._model_id,
                messages=messages,
                **payload_args,
            )
        except JSONSchemaValidationError as exc:
            raw_content = stringify_raw_response(getattr(exc, "raw_response", None))
            if raw_content:
                try:
                    return json.loads(raw_content)
                except json.JSONDecodeError:
                    trimmed = raw_content.strip()
                    if trimmed:
                        return {"overall_summary": trimmed}
            return None
        except Exception:
            return None

        return extract_summary_payload(response)

    def should_generate(self, work_nodes: Sequence[WorkNode]) -> bool:
        return should_generate_work_summary(work_nodes)

    @staticmethod
    def extract_summary_text(payload: Any | None) -> str | None:
        if isinstance(payload, dict):
            summary = payload.get("overall_summary") or payload.get("summary")
            if isinstance(summary, str):
                cleaned = summary.strip()
                return cleaned or None
        if isinstance(payload, str):
            cleaned = payload.strip()
            return cleaned or None
        return None

    @staticmethod
    def extract_next_actions(payload: Any | None) -> list[str]:
        if not isinstance(payload, dict):
            return []
        next_actions = payload.get("next_actions")
        if not isinstance(next_actions, list):
            return []
        return [action for action in next_actions if isinstance(action, str) and action.strip()]


def format_work_nodes_for_summary(work_nodes: Sequence[WorkNode]) -> str:
    lines: list[str] = []
    for index, node in enumerate(work_nodes, start=1):
        body = (node.body or "").strip()
        if len(body) > 400:
            body = body[:400].rstrip() + "…"
        lines.append(
            f"{index}. step_id={node.step_id or '-'} "
            f"type={node.node_type} status={node.status}\n"
            f"   title={node.title or 'N/A'}\n"
            f"   body={body or 'No additional details.'}"
        )
    return "\n".join(lines)


def should_generate_work_summary(work_nodes: Sequence[WorkNode]) -> bool:
    tool_nodes = [node for node in work_nodes if node.node_type == "tool_call"]
    if len(tool_nodes) >= 3:
        return True
    total_chars = sum(len(node.body or "") for node in tool_nodes)
    return total_chars >= 600


def stringify_raw_response(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw, ensure_ascii=False)
    except Exception:
        return str(raw)


def extract_summary_payload(response: Any) -> Any | None:
    try:
        choices = getattr(response, "choices", None)
        if not choices:
            return None
        message = getattr(choices[0], "message", None)
        if isinstance(message, dict):
            parsed = message.get("parsed")
            if parsed is not None:
                return parsed
            content = message.get("content")
        else:
            parsed = getattr(message, "parsed", None)
            if parsed is not None:
                return parsed
            content = getattr(message, "content", None)
    except Exception:
        return None

    if not content:
        return None

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        trimmed = str(content).strip()
        if trimmed:
            return {"overall_summary": trimmed}
    return None


__all__ = [
    "SummaryGenerator",
    "WORK_SUMMARY_SYSTEM_PROMPT",
    "WORK_SUMMARY_USER_TEMPLATE",
    "extract_summary_payload",
    "format_work_nodes_for_summary",
    "should_generate_work_summary",
    "stringify_raw_response",
]
