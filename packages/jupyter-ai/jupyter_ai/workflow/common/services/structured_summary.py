from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from litellm import acompletion
from litellm.exceptions import JSONSchemaValidationError

from jupyter_ai.workflow.common.worklog.plan_steps import PlanStep


def _clean_text(value: Any) -> str:
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed:
            return trimmed
    return ""


@dataclass(frozen=True, slots=True)
class SummaryReference:
    """Describes the provenance of a summarized work unit."""

    label: str
    ref_id: str | None
    stage: str  # e.g., "plan", "work"

    def display_label(self) -> str:
        stage_map = {
            "plan": "계획",
            "work": "작업",
            "summary": "요약",
        }
        prefix = stage_map.get(self.stage, self.stage or "참조")
        label = self.label or (self.ref_id or "알 수 없음")
        return f"[{prefix}: {label}]"

    def to_payload(self) -> Mapping[str, str | None]:
        return {
            "label": self.label or self.ref_id,
            "ref_id": self.ref_id,
            "stage": self.stage,
        }


@dataclass(frozen=True, slots=True)
class SummaryUnit:
    """Single summarized work cluster."""

    title: str
    details: str
    references: tuple[SummaryReference, ...]


@dataclass(frozen=True, slots=True)
class SummaryOutline:
    """Structured representation of the summarize stage."""

    overall_summary: str | None
    units: tuple[SummaryUnit, ...]
    next_actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SummarySection:
    """Rendered summarize-stage section for the final response."""

    outline: SummaryOutline
    text: str

    def to_context_payload(self) -> Mapping[str, Any]:
        return _outline_to_payload(self.outline)

    def to_context_json(self) -> str:
        try:
            return json.dumps(self.to_context_payload(), ensure_ascii=False, indent=2)
        except Exception:
            return ""


class StructuredSummaryBuilder:
    """Build structured summaries that track source stages."""

    def build(
        self,
        *,
        summary_payload: Any | None,
        plan_steps: Sequence[PlanStep] | None,
    ) -> SummaryOutline:
        plan_lookup = {
            step.step_id: step
            for step in plan_steps or ()
            if getattr(step, "step_id", None)
        }
        payload = summary_payload if isinstance(summary_payload, Mapping) else {}
        summary_text = _clean_text(payload.get("overall_summary"))
        items = payload.get("items")
        next_actions = tuple(
            action.strip()
            for action in _iter_actions(payload.get("next_actions"))
            if action.strip()
        )

        units: list[SummaryUnit] = []
        if isinstance(items, Sequence):
            for item in items:
                unit = self._build_unit(item, plan_lookup)
                if unit:
                    units.append(unit)

        if not units and plan_lookup:
            units = [
                SummaryUnit(
                    title=_clean_text(step.title) or step.step_id,
                    details=f"계획 단계 '{step.title}' 상태: {step.status}",
                    references=(
                        SummaryReference(
                            label=_clean_text(step.title) or step.step_id,
                            ref_id=step.step_id,
                            stage="plan",
                        ),
                    ),
                )
                for step in plan_lookup.values()
            ]

        outline = SummaryOutline(
            overall_summary=summary_text or None,
            units=tuple(units),
            next_actions=next_actions,
        )
        return outline

    def _build_unit(
        self,
        item: Any,
        plan_lookup: Mapping[str, PlanStep],
    ) -> SummaryUnit | None:
        if not isinstance(item, Mapping):
            return None
        step_id = _clean_text(item.get("step_id"))
        plan_ref = plan_lookup.get(step_id) if step_id else None
        title = _clean_text(item.get("title")) or (plan_ref.title if plan_ref else "")
        details = _clean_text(item.get("details"))
        status = _clean_text(item.get("status"))
        if status:
            details = f"{details} (상태: {status})" if details else f"상태: {status}"
        if not title and not details:
            return None

        references: list[SummaryReference] = []
        if plan_ref:
            references.append(
                SummaryReference(
                    label=plan_ref.title or plan_ref.step_id,
                    ref_id=plan_ref.step_id,
                    stage="plan",
                )
            )
        elif step_id:
            references.append(
                SummaryReference(
                    label=step_id,
                    ref_id=step_id,
                    stage="plan",
                )
            )

        fallback_label = title or details or "Work item"
        references.append(
            SummaryReference(
                label=fallback_label,
                ref_id=step_id or None,
                stage="work",
            )
        )
        deduped = self._dedupe_references(references)
        return SummaryUnit(
            title=title or fallback_label,
            details=details or fallback_label,
            references=tuple(deduped),
        )

    @staticmethod
    def _dedupe_references(references: Iterable[SummaryReference]) -> list[SummaryReference]:
        unique: list[SummaryReference] = []
        seen: set[tuple[str | None, str]] = set()
        for reference in references:
            key = (reference.ref_id, reference.stage)
            if key in seen:
                continue
            seen.add(key)
            unique.append(reference)
        return unique


class SummarySectionFormatter:
    """Render a user-facing summarize section."""

    def format(self, outline: SummaryOutline) -> str:
        lines: list[str] = ["서머라이즈"]
        if outline.overall_summary:
            lines.append(f"> {outline.overall_summary}")
        if not outline.units:
            lines.append("- 참고할 작업 요약이 없습니다.")
        else:
            for index, unit in enumerate(outline.units, start=1):
                lines.append(f"{index}. {unit.title}")
                lines.append(f"   - {unit.details}")
                citations = ", ".join(ref.display_label() for ref in unit.references)
                lines.append(f"   - 출처: {citations or '기록 없음'}")
        if outline.next_actions:
            lines.append("후속 작업")
            for action in outline.next_actions:
                lines.append(f"- {action}")
        return "\n".join(lines).strip()


class SummaryNarrator:
    """LLM-backed renderer for the summarize stage."""

    SUMMARY_SYSTEM_PROMPT = (
        "You are the summarization brain for an autonomous agent. "
        "Review the structured outline of completed work and produce concise Korean sentences "
        "that capture the key intent of each unit. Always respond by calling the "
        "`submit_summary_section` tool so the caller receives structured data."
    )

    SUMMARY_USER_TEMPLATE = (
        "Structured outline data (JSON):\n{payload}\n\n"
        "Requirements:\n"
        "- Preserve the order of the provided units. Use the provided `unit_index` (1-based) when filling the tool payload.\n"
        "- Each summary sentence must be written in Korean, stay under two clauses, and focus on the user-facing impact.\n"
        "- If an overall summary is apparent, provide it in Korean; otherwise leave it blank.\n"
        "- Only include next actions when the outline's `next_actions` array is non-empty.\n"
        "- Do NOT output markdown or free text responses. Always call the `submit_summary_section` function."
    )

    def __init__(
        self,
        *,
        model_id: str | None,
        model_args: Mapping[str, Any] | None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._model_id = model_id if isinstance(model_id, str) and model_id.strip() else None
        self._model_args = dict(model_args or {})
        self._logger = logger or logging.getLogger(__name__)

    @property
    def enabled(self) -> bool:
        return bool(self._model_id)

    async def narrate(self, outline: SummaryOutline) -> str | None:
        if not self.enabled:
            return None
        payload = _outline_to_payload(outline)
        payload_text = _safe_json(payload)
        payload_args = _summary_payload_defaults(self._model_args)
        tools = list(payload_args.get("tools", []))
        if not any(_matches_summary_tool(spec) for spec in tools):
            tools.append(_summary_tool_spec())
        payload_args["tools"] = tools

        enforced_tool = payload_args.get("tool_choice") is None
        if enforced_tool:
            payload_args["tool_choice"] = {
                "type": "function",
                "function": {"name": "submit_summary_section"},
            }

        messages = [
            {"role": "system", "content": self.SUMMARY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": self.SUMMARY_USER_TEMPLATE.format(payload=payload_text),
            },
        ]

        response = await _invoke_summary_model(
            self._model_id,
            messages,
            payload_args,
        )
        if not response and enforced_tool:
            fallback_args = _summary_payload_defaults(self._model_args)
            fallback_args["tools"] = tools
            fallback_args.pop("tool_choice", None)
            response = await _invoke_summary_model(
                self._model_id,
                messages,
                fallback_args,
            )
        if not response:
            return None
        return _render_summary_text(outline, response)


async def _invoke_summary_model(
    model_id: str,
    messages: list[dict[str, Any]],
    payload_args: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    try:
        response = await acompletion(
            model=model_id,
            messages=messages,
            **payload_args,
        )
    except JSONSchemaValidationError as exc:  # pragma: no cover - defensive
        raw = getattr(exc, "raw_response", None)
        payload = _stringify_raw_response(raw)
        return _coerce_summary_payload(payload)
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER = logging.getLogger(__name__)
        LOGGER.debug("Summary narration model call failed: %s", exc)
        return None

    parsed = _extract_summary_tool_payload(response)
    if parsed:
        return parsed
    return None


def _extract_summary_tool_payload(response: Any) -> Mapping[str, Any] | None:
    try:
        choices = getattr(response, "choices", None)
        if not choices:
            return None
        message = getattr(choices[0], "message", None)
        if isinstance(message, dict):
            tool_call = message.get("tool_calls")
        else:
            tool_call = getattr(message, "tool_calls", None)
        if not tool_call:
            return None
        first_call = tool_call[0]
        function_data = first_call.get("function") if isinstance(first_call, dict) else None
        if not function_data:
            return None
        arguments = function_data.get("arguments")
    except Exception:  # pragma: no cover - defensive
        return None
    return _coerce_summary_payload(arguments)


def _coerce_summary_payload(raw: Any) -> Mapping[str, Any] | None:
    if not raw:
        return None
    if isinstance(raw, Mapping):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, Mapping):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


class SummaryStageService:
    """Facade that combines outline building and formatting."""

    def __init__(
        self,
        *,
        builder: StructuredSummaryBuilder | None = None,
        formatter: SummarySectionFormatter | None = None,
        narrator: SummaryNarrator | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._builder = builder or StructuredSummaryBuilder()
        self._formatter = formatter or SummarySectionFormatter()
        self._narrator = narrator
        self._logger = logger or logging.getLogger(__name__)

    async def render(
        self,
        *,
        summary_payload: Any | None,
        plan_steps: Sequence[PlanStep] | None,
    ) -> SummarySection:
        outline = self._builder.build(
            summary_payload=summary_payload,
            plan_steps=plan_steps,
        )
        text = await self._compose_text(outline)
        return SummarySection(outline=outline, text=text)

    async def _compose_text(self, outline: SummaryOutline) -> str:
        if self._narrator and self._narrator.enabled:
            try:
                llm_text = await self._narrator.narrate(outline)
            except Exception:  # pragma: no cover - defensive
                self._logger.debug("Summary narrator failed.", exc_info=True)
                llm_text = None
            if llm_text:
                return llm_text
        return self._formatter.format(outline)


def _iter_actions(candidate: Any) -> Iterable[str]:
    if isinstance(candidate, str):
        yield candidate
        return
    if isinstance(candidate, Mapping):
        return
    if isinstance(candidate, Sequence):
        for item in candidate:
            if isinstance(item, str):
                yield item


__all__ = [
    "StructuredSummaryBuilder",
    "SummaryOutline",
    "SummaryUnit",
    "SummaryReference",
    "SummarySection",
    "SummarySectionFormatter",
    "SummaryNarrator",
    "SummaryStageService",
]


def _outline_to_payload(outline: SummaryOutline) -> dict[str, Any]:
    return {
        "overall_summary": outline.overall_summary,
        "units": [
            {
                "unit_index": index + 1,
                "title": unit.title,
                "details": unit.details,
                "references": [ref.to_payload() for ref in unit.references],
            }
            for index, unit in enumerate(outline.units)
        ],
        "next_actions": list(outline.next_actions),
    }


def _safe_json(payload: Mapping[str, Any]) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except TypeError:
        return str(payload)


def _summary_payload_defaults(model_args: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = dict(model_args or {})
    payload.setdefault("temperature", 0.35)
    payload.setdefault("max_tokens", 600)
    payload.pop("response_format", None)
    return payload


def _summary_tool_spec() -> Mapping[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "submit_summary_section",
            "description": (
                "Return Korean summaries for each outline unit using the provided unit_index."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "overview": {
                        "type": "string",
                        "description": "Optional Korean overview sentence.",
                    },
                    "units": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "unit_index": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "description": "1-based index of the outline unit.",
                                },
                                "summary": {
                                    "type": "string",
                                    "description": "Korean sentence describing that unit.",
                                },
                            },
                            "required": ["unit_index", "summary"],
                            "additionalProperties": False,
                        },
                        "minItems": 1,
                    },
                    "next_actions": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "description": "Optional Korean next actions.",
                        },
                    },
                },
                "required": ["units"],
                "additionalProperties": False,
            },
        },
    }


def _matches_summary_tool(spec: Mapping[str, Any]) -> bool:
    if not isinstance(spec, Mapping):
        return False
    if spec.get("type") != "function":
        return False
    function = spec.get("function")
    if not isinstance(function, Mapping):
        return False
    return function.get("name") == "submit_summary_section"


def _render_summary_text(outline: SummaryOutline, structured: Mapping[str, Any]) -> str:
    lines: list[str] = ["서머라이즈"]
    overview = _clean_text(structured.get("overview")) or _clean_text(outline.overall_summary)
    if overview:
        lines.append(f"> {overview}")

    ordered_units = _ordered_unit_entries(structured.get("units"), len(outline.units))
    for display_index, unit_index in enumerate(ordered_units, start=1):
        if unit_index >= len(outline.units):
            continue
        unit = outline.units[unit_index]
        summary_text = _lookup_unit_summary(structured.get("units"), unit_index)
        body = summary_text or unit.details or unit.title
        if not body:
            continue
        lines.append(f"{display_index}. {body}")
        citations = _format_citations(unit.references)
        if citations:
            lines.append(f"   - 출처: {citations}")

    next_actions = _clean_actions(structured.get("next_actions"))
    if not next_actions:
        next_actions = [
            action.strip()
            for action in outline.next_actions
            if isinstance(action, str) and action.strip()
        ]
    if next_actions:
        lines.append("후속 작업")
        for action in next_actions[:4]:
            lines.append(f"- {action}")

    return "\n".join(lines).strip()


def _ordered_unit_entries(entries: Any, total_units: int) -> list[int]:
    order: list[int] = []
    seen: set[int] = set()
    if isinstance(entries, Sequence):
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            idx = entry.get("unit_index")
            if not isinstance(idx, int) or idx <= 0:
                continue
            normalized = idx - 1
            if normalized in seen or normalized >= total_units:
                continue
            seen.add(normalized)
            order.append(normalized)
    for idx in range(total_units):
        if idx not in seen:
            order.append(idx)
    return order


def _lookup_unit_summary(entries: Any, unit_index: int) -> str | None:
    if not isinstance(entries, Sequence):
        return None
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        idx = entry.get("unit_index")
        if not isinstance(idx, int) or idx - 1 != unit_index:
            continue
        return _clean_text(entry.get("summary"))
    return None


def _format_citations(references: Sequence[SummaryReference]) -> str:
    labels = [ref.display_label() for ref in references]
    cleaned = [label for label in labels if label]
    return ", ".join(cleaned)


def _clean_actions(candidate: Any) -> list[str]:
    if not isinstance(candidate, Sequence):
        return []
    actions: list[str] = []
    for entry in candidate:
        if isinstance(entry, str):
            cleaned = entry.strip()
            if cleaned:
                actions.append(cleaned)
    return actions


def _stringify_raw_response(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw, ensure_ascii=False)
    except Exception:
        return str(raw)
