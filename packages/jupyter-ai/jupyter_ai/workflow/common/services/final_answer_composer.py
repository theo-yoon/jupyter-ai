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

        summary_context = self._build_summary_context(summary_payload, fallback_raw, summary_section)
        if self._model_id and summary_context:
            result = await self._stream_completion(
                summary_context=summary_context,
                fallback_raw=fallback_raw or "(none provided)",
                on_update=on_update,
            )
            if result:
                return result

        if normalized_fallback:
            final_message = normalized_fallback
        else:
            final_message = "결과를 정리할 수 없습니다."
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

__all__ = ["FinalAnswerComposer"]
