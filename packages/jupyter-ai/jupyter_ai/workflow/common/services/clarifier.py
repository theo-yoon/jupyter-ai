from __future__ import annotations

import logging
from typing import Iterable, Mapping, Sequence

from litellm import acompletion


class ClarificationService:
    """Lightweight helper that rewrites user questions when needed."""

    def __init__(
        self,
        *,
        model_id: str | None,
        model_args: Mapping[str, object] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._model_id = model_id
        self._model_args = dict(model_args or {})
        self._logger = logger or logging.getLogger(__name__)

    async def clarify(
        self,
        *,
        latest_message: str | None,
        conversation_snippets: str | None,
        execution_signals: Sequence[Mapping[str, object]] | None,
    ) -> str | None:
        message = (latest_message or "").strip()
        if not message:
            return None
        if not self._model_id:
            self._logger.debug("[clarifier] Skipped; no model configured.")
            return None
        model_args = dict(self._model_args)
        model_args.pop("stream", None)
        prompt = _build_prompt(
            message,
            snippets=conversation_snippets,
            execution_signals=execution_signals,
        )
        try:
            response = await acompletion(
                model=self._model_id,
                messages=[
                    {"role": "system", "content": _CLARIFIER_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                **model_args,
            )
        except Exception as err:
            self._logger.warning("[clarifier] Model invocation failed: %s", err, exc_info=True)
            return None
        clarified = _extract_response_text(response)
        if clarified:
            self._logger.info("[clarifier] Produced refined request.")
        return clarified


def summarize_recent_conversation(
    messages: Iterable[Mapping[str, object]],
    *,
    limit: int = 6,
) -> str | None:
    snippets: list[str] = []
    for msg in reversed(list(messages)):
        if len(snippets) >= limit:
            break
        sender = (msg.get("sender") or "").strip()
        if sender.startswith("jupyter-ai-personas::"):
            continue
        body = msg.get("body")
        if not isinstance(body, str):
            continue
        text = body.strip()
        if not text:
            continue
        role = "assistant" if sender.startswith("jupyter-ai-personas::") else "user"
        snippet = text if len(text) <= 200 else f"{text[:200]}…"
        snippets.append(f"- {role}: {snippet}")
    return "\n".join(reversed(snippets)) if snippets else None


def _build_prompt(
    latest_message: str,
    *,
    snippets: str | None,
    execution_signals: Sequence[Mapping[str, object]] | None,
) -> str:
    signal_block = _format_execution_signals(execution_signals)
    return (
        "Original user request:\n"
        + latest_message
        + "\n\nRecent conversation snippets:\n"
        + (snippets or "- none")
        + "\n\nRecent execution summaries:\n"
        + signal_block
        + "\n\nRewrite the user request now."
    )


def _extract_response_text(response) -> str | None:
    try:
        content = response.choices[0].message.get("content", "")
    except Exception:
        return None
    text = (content or "").strip()
    return text or None


def _format_execution_signals(execution_signals: Sequence[Mapping[str, object]] | None) -> str:
    if not execution_signals:
        return "- none"
    lines: list[str] = []
    for signal in execution_signals:
        summary = signal.get("summary")
        if not isinstance(summary, str):
            continue
        flag = "error" if signal.get("has_error") else "ok"
        lines.append(f"- [{flag}] {summary}")
    return "\n".join(lines) if lines else "- none"


_CLARIFIER_PROMPT = (
    "You are an assistant that reformulates user requests so agents understand the task without missing context. "
    "Rewrite the request so it is explicit about the desired outcome, inputs, recent tool outputs, and constraints. "
    "When the user mentions a single cohort (e.g., age band, gender, region, customer segment) expand the request to compare other statistically meaningful cohorts when that improves insight. "
    "Encourage multi-dimensional analysis (age, gender, geography, product line, time period) whenever it could influence the answer, and mention assumptions if underlying data may be limited. "
    "Include references to recent actions when relevant. Respond with a single improved request sentence or short paragraph.\n"
    "Examples:\n"
    "- Original: \"Which products do people in their 20s like?\"\n"
    "  Rewrite: \"Analyze recent customer insights to compare top product preferences across age brackets (teens, 20s, 30s, 40+), highlight the favorite items for people in their 20s, and note any gender or regional differences when they matter.\"\n"
    "- Original: \"What was the conversion rate last week?\"\n"
    "  Rewrite: \"Review last week's conversion metrics across primary traffic sources and device types, report the overall conversion rate, and explain any significant deviations from the previous week.\"\n"
    "- Original: \"Summarize the survey feedback from Europe.\"\n"
    "  Rewrite: \"Summarize survey feedback by comparing key themes across European regions, contrasting them with North America and APAC where possible, and call out sentiment differences or sample-size caveats.\""
)


__all__ = ["ClarificationService", "summarize_recent_conversation"]
