from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Mapping, Sequence

from litellm import acompletion

from .streaming import extract_stream_delta
from .structured_summary import SummarySection


UpdateCallback = Callable[[str], Awaitable[None]]


class FinalAnswerComposer:
    """Generate the user-facing final answer text (optionally via streaming)."""

    def __init__(
        self,
        *,
        model_id: str | None,
        model_args: Mapping[str, Any] | None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._model_id = model_id
        self._model_args = dict(model_args or {})
        self._logger = logger or logging.getLogger(__name__)
        self._insight_builder = InsightFallbackBuilder()
        self._tool_insight_generator = ToolInsightGenerator(
            model_id=model_id,
            model_args=model_args,
            logger=self._logger,
        )

    async def compose(
        self,
        *,
        summary_payload: Any | None,
        fallback_text: str,
        summary_section: SummarySection | None,
        on_update: UpdateCallback,
    ) -> str:
        fallback_raw = (fallback_text or "").strip()
        normalized_fallback = self._normalize_fallback(fallback_raw)
        tool_insight = await self._tool_insight_generator.generate(
            summary_payload=summary_payload,
            summary_section=summary_section,
        )
        fallback_insight = self._insight_builder.build(
            summary_section=summary_section,
            summary_payload=summary_payload,
            fallback_text=normalized_fallback,
        )
        if tool_insight:
            fallback_insight = "\n\n".join(
                part for part in (tool_insight, normalized_fallback) if part
            ) or tool_insight

        summary_context = self._build_summary_context(summary_payload, fallback_raw, summary_section)
        summary_context = self._merge_context(summary_context, tool_insight)
        if self._model_id and summary_context:
            result = await self._stream_completion(
                summary_context=summary_context,
                fallback_raw=fallback_raw or "(none provided)",
                on_update=on_update,
            )
            if result:
                completed = self._ensure_completed_text(result, fallback_insight)
                if completed != result:
                    await on_update(completed)
                return completed

        final_message = fallback_insight or normalized_fallback or "결과를 정리할 수 없습니다."
        await on_update(final_message)
        return final_message

    async def _stream_completion(
        self,
        *,
        summary_context: str,
        fallback_raw: str,
        on_update: UpdateCallback,
    ) -> str:
        model_args = dict(self._model_args)
        model_args.pop("response_format", None)
        # Final responses should never invoke workflow tools again, so strip any
        # lingering tool/function wiring that may have been configured for the
        # planning steps.
        model_args.pop("tools", None)
        model_args.pop("functions", None)
        model_args.pop("function_call", None)
        model_args.pop("tool_choice", None)
        model_args.pop("parallel_tool_calls", None)
        model_args.setdefault("temperature", 0.5)
        model_args.setdefault("max_tokens", 600)

        try:
            stream = await acompletion(
                model=self._model_id,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are finishing a task for a user. Deliver a clear, concise final message "
                            "summarizing the completed work and highlighting follow-up actions. "
                            "Respond in plain text. Avoid JSON."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Structured summary of the work:\n"
                            f"{summary_context}\n\n"
                            "Previous draft (may be JSON or incomplete):\n"
                            f"{fallback_raw}\n\n"
                            "Write the final response with this structure:\n"
                            "1. Opening paragraph that explains the overall outcome and what the agent accomplished.\n"
                            "2. A short section titled \"주요 발견\" with bullet points describing 2-3 meaningful insights drawn from the work.\n"
                            "3. A concluding paragraph titled \"관점 제안\" that suggests how the user could explore the results further or what to watch next.\n"
                            "Keep the tone confident and helpful, and weave in the most relevant evidence from the summary. "
                            "Use Korean if the source text appears to be Korean; otherwise mirror the user's language."
                        ),
                    },
                ],
                stream=True,
                **model_args,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            self._logger.debug("Final answer streaming failed: %s", exc)
            return ""

        final_text = ""
        last_emitted = 0
        async for chunk in stream:
            payload = extract_stream_delta(chunk)
            if not payload:
                continue
            content_delta, _ = payload
            if not content_delta:
                continue
            final_text += content_delta
            if len(final_text) - last_emitted >= 48 or "\n" in content_delta:
                await on_update(final_text)
                last_emitted = len(final_text)
                await asyncio.sleep(0)

        final_text = final_text.strip()
        if final_text:
            await on_update(final_text)
        return final_text

    @staticmethod
    def _normalize_fallback(fallback_raw: str) -> str:
        if not fallback_raw:
            return ""
        try:
            candidate = json.loads(fallback_raw)
        except json.JSONDecodeError:
            return fallback_raw
        if not isinstance(candidate, Mapping):
            return fallback_raw

        blocks: list[str] = []
        overall = candidate.get("overall_summary") or candidate.get("summary")
        if isinstance(overall, str) and overall.strip():
            blocks.append(overall.strip())

        items = candidate.get("items")
        if isinstance(items, Sequence):
            item_lines: list[str] = []
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                title = item.get("title")
                status = item.get("status")
                details = item.get("details")
                name_bits = [
                    bit.strip()
                    for bit in (title, status)
                    if isinstance(bit, str) and bit.strip()
                ]
                if name_bits:
                    item_lines.append("• " + " — ".join(name_bits))
                if isinstance(details, str) and details.strip():
                    item_lines.append(f"  {details.strip()}")
            if item_lines:
                blocks.append("\n".join(item_lines))

        next_actions = candidate.get("next_actions")
        if isinstance(next_actions, Sequence):
            action_lines = [
                f"- {action.strip()}"
                for action in next_actions
                if isinstance(action, str) and action.strip()
            ]
            if action_lines:
                blocks.append("Next actions:\n" + "\n".join(action_lines))

        normalized = "\n\n".join(part for part in blocks if part.strip())
        return normalized or fallback_raw

    @staticmethod
    def _build_summary_context(
        summary_payload: Any | None,
        fallback_raw: str,
        summary_section: SummarySection | None,
    ) -> str:
        if summary_section:
            context_json = summary_section.to_context_json()
            if context_json:
                return context_json
        if isinstance(summary_payload, Mapping) and summary_payload:
            try:
                return json.dumps(summary_payload, ensure_ascii=False, indent=2)
            except TypeError:
                return str(summary_payload)
        if summary_payload is not None:
            return str(summary_payload)
        return fallback_raw

    @staticmethod
    def _merge_context(summary_context: str, tool_insight: str) -> str:
        parts = []
        if summary_context and summary_context.strip():
            parts.append(summary_context.strip())
        if tool_insight and tool_insight.strip():
            parts.append(f"LLM-generated recap of tool outputs:\n{tool_insight.strip()}")
        return "\n\n".join(parts)

    @staticmethod
    def _ensure_completed_text(text: str, fallback_block: str | None) -> str:
        """
        Prevent partially formatted fallback text (often verbose status reports)
        from leaking into the final answer unless we have no composed text at all.
        """
        trimmed = text.strip()
        if trimmed:
            return trimmed
        return (fallback_block or "").strip()


class InsightFallbackBuilder:
    """Compose deterministic insight text when streaming fails."""

    def build(
        self,
        *,
        summary_section: SummarySection | None,
        summary_payload: Any | None,
        fallback_text: str,
    ) -> str:
        lines: list[str] = []
        if fallback_text:
            lines.append(fallback_text)
        findings = self._findings(summary_section, summary_payload)
        if findings:
            findings_block = "\n".join(f"- {item}" for item in findings)
            lines.append(f"주요 발견\n{findings_block}")
        prompts = self._prompts(summary_section, summary_payload)
        if prompts:
            prompt_block = "\n".join(f"- {prompt}" for prompt in prompts)
            lines.append(f"관점 제안\n{prompt_block}")
        return "\n\n".join(part for part in lines if part).strip()

    def _findings(
        self,
        summary_section: SummarySection | None,
        summary_payload: Any | None,
    ) -> list[str]:
        outline = summary_section.outline if summary_section else None
        findings: list[str] = []
        if outline:
            for unit in outline.units[:3]:
                details = unit.details or unit.title
                if details:
                    findings.append(f"{unit.title}: {details}")
        if findings:
            return findings
        if isinstance(summary_payload, Mapping):
            items = summary_payload.get("items")
            if isinstance(items, Sequence):
                for item in items:
                    if not isinstance(item, Mapping):
                        continue
                    title = str(item.get("title") or "결과").strip()
                    details = str(item.get("details") or "").strip()
                    if not details:
                        continue
                    findings.append(f"{title}: {details}")
                    if len(findings) >= 3:
                        break
        return findings

    def _prompts(
        self,
        summary_section: SummarySection | None,
        summary_payload: Any | None,
    ) -> list[str]:
        outline = summary_section.outline if summary_section else None
        prompts: list[str] = []
        if outline and outline.next_actions:
            for action in outline.next_actions[:3]:
                prompts.append(action)
        if prompts:
            return prompts
        if isinstance(summary_payload, Mapping):
            next_actions = summary_payload.get("next_actions")
            if isinstance(next_actions, Sequence):
                for action in next_actions:
                    if isinstance(action, str) and action.strip():
                        prompts.append(action.strip())
                        if len(prompts) >= 3:
                            break
        return prompts


class ToolInsightGenerator:
    """LLM-powered recap of tool executions for final answers."""

    SYSTEM_PROMPT = (
        "You review an autonomous agent's structured work summary (JSON plus optional prose). "
        "Write a concise Korean recap of the most important tool executions and add 1-2 insight bullets "
        "that explain the implications for the user. Keep everything in plain text (no markdown headings)."
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

    async def generate(
        self,
        *,
        summary_payload: Any | None,
        summary_section: SummarySection | None,
    ) -> str:
        if not self._model_id:
            return ""
        context = self._build_context(summary_payload, summary_section)
        if not context:
            return ""
        payload_args = dict(self._model_args)
        payload_args.pop("response_format", None)
        payload_args.setdefault("temperature", 0.35)
        payload_args.setdefault("max_tokens", 400)
        try:
            response = await acompletion(
                model=self._model_id,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": context},
                ],
                **payload_args,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.debug("Tool insight generation failed: %s", exc)
            return ""
        text = self._extract_text(response)
        return text.strip()

    def _build_context(
        self,
        summary_payload: Any | None,
        summary_section: SummarySection | None,
    ) -> str:
        parts: list[str] = []
        if isinstance(summary_payload, Mapping):
            overall = summary_payload.get("overall_summary") or summary_payload.get("summary")
            if isinstance(overall, str) and overall.strip():
                parts.append(f"전체 작업 요약: {overall.strip()}")
            items = summary_payload.get("items")
            if isinstance(items, Sequence):
                highlights: list[str] = []
                for item in items:
                    if not isinstance(item, Mapping):
                        continue
                    title = str(item.get("title") or "").strip() or "작업"
                    details = str(item.get("details") or "").strip()
                    status = str(item.get("status") or "").strip()
                    snippet = f"{title}"
                    if status:
                        snippet += f" ({status})"
                    if details:
                        snippet += f": {details}"
                    highlights.append(snippet)
                    if len(highlights) >= 5:
                        break
                if highlights:
                    parts.append("주요 도구 실행 요약:\n- " + "\n- ".join(highlights))
            next_actions = summary_payload.get("next_actions")
            if isinstance(next_actions, Sequence):
                actions = [
                    str(action).strip()
                    for action in next_actions
                    if isinstance(action, str) and action.strip()
                ]
                if actions:
                    parts.append("후속 제안:\n- " + "\n- ".join(actions[:3]))
        if summary_section and summary_section.text:
            parts.append("Rendered summary text:\n" + summary_section.text)
        return "\n\n".join(part for part in parts if part.strip())

    @staticmethod
    def _extract_text(response: Any) -> str:
        try:
            choices = getattr(response, "choices", None)
            if not choices:
                return ""
            message = getattr(choices[0], "message", None)
            if isinstance(message, dict):
                return str(message.get("content") or "").strip()
            content = getattr(message, "content", None)
            return str(content or "").strip()
        except Exception:  # pragma: no cover - defensive
            return ""

__all__ = ["FinalAnswerComposer"]
