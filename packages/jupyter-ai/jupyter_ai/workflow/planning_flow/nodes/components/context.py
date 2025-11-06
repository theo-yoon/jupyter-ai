from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from typing import Any, Mapping

from jupyterlab_chat.models import Message
from ....common.services.bootstrap import PlanningInitializer
from ....common.utils import latest_user_message
from ....common.knowledge import KnowledgeContext

from .knowledge import maybe_enrich_knowledge


_LOGGER = logging.getLogger(__name__)
if not _LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("[planning.context] %(levelname)s %(message)s"))
    _LOGGER.addHandler(handler)
_LOGGER.setLevel(logging.INFO)
_LOGGER.propagate = False


@dataclass(slots=True)
class PrepContext:
    messages: list[dict[str, Any]]
    worklog_markup: str
    worklog_entry_id: str | None
    shared_ref: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "messages": self.messages,
            "worklog_markup": self.worklog_markup,
            "worklog_entry_id": self.worklog_entry_id,
            "shared_ref": self.shared_ref,
        }


async def prepare_context(node: Any, shared: dict[str, Any], *, system_username: str) -> PrepContext:
    """
    Populate the shared state with base chat context and run the planning initializer.
    """
    if not _has_messages(shared):
        shared["litellm_messages"] = _initialize_messages(node, system_username)

    shared["latest_user_message"] = latest_user_message(shared["litellm_messages"])
    clarified_message = node.params.get("_clarified_user_message")

    initializer = PlanningInitializer(
        model_id=node.model_id,
        model_args=node.model_args,
        persona_id=node.persona_id,
        response_template=node.response_template,
        ychat=node.ychat,
        logger=node.log,
    )

    async def update_worklog_markup(markup: str) -> None:
        message_id = shared.get("prev_message_id")
        if not message_id:
            return
        message_body = node.response_template.render(
            {
                "content": shared.get("latest_content", ""),
                "tool_call_ui_elements": shared.get("latest_tool_ui", ""),
                "worklog_ui_elements": markup,
                "answer_ui_elements": shared.get("answer_markup", ""),
            }
        )
        node.ychat.update_message(
            Message(
                id=message_id,
                body=message_body,
                time=time.time(),
                sender=node.persona_id,
                raw_time=False,
            )
        )

    metadata = _build_metadata(node)
    knowledge_context = node.params.get("_knowledge_context")
    if not isinstance(knowledge_context, KnowledgeContext):
        knowledge_context = None
    _LOGGER.info(
        "[prepare_context] before setup shared keys=%s",
        sorted(shared.keys()),
    )
    await initializer.setup(
        shared,
        metadata=metadata,
        clarified_message=_clean_clarified_message(clarified_message),
        update_display=update_worklog_markup,
        knowledge_context=knowledge_context,
    )
    _LOGGER.info(
        "[prepare_context] after setup shared keys=%s",
        sorted(shared.keys()),
    )

    await maybe_enrich_knowledge(node, shared)
    shared.setdefault("response_template", node.response_template)

    return PrepContext(
        messages=shared["litellm_messages"],
        worklog_markup=shared.get("worklog_markup", ""),
        worklog_entry_id=shared.get("worklog_entry_id"),
        shared_ref=shared,
    )


def _has_messages(shared: dict[str, Any]) -> bool:
    messages = shared.get("litellm_messages")
    return isinstance(messages, list) and bool(messages)


def _initialize_messages(node: Any, system_username: str) -> list[dict[str, Any]]:
    history: list[Message] = node.ychat.get_messages()
    ychat_messages = history[-node.history_size - 1 :]

    litellm_messages: list[dict[str, Any]] = []
    for msg in ychat_messages:
        role = (
            "assistant"
            if msg.sender.startswith("jupyter-ai-personas::")
            else "system"
            if msg.sender == system_username
            else "user"
        )
        litellm_messages.append({"role": role, "content": msg.body})

    if node.system_prompt:
        system_message = {"role": "system", "content": node.system_prompt}
        litellm_messages = [system_message, *litellm_messages]

    invoking_candidates = [
        node.params.get("_clarified_user_message"),
        node.params.get("_routing_user_message"),
    ]
    for candidate in invoking_candidates:
        if not isinstance(candidate, str):
            continue
        normalized = candidate.strip()
        if not normalized:
            continue
        already_present = any(
            isinstance(item, dict)
            and item.get("role") == "user"
            and isinstance(item.get("content"), str)
            and item["content"].strip() == normalized
            for item in litellm_messages
        )
        if not already_present:
            litellm_messages.append({"role": "user", "content": normalized})
        break
    return litellm_messages


def _build_metadata(node: Any) -> dict[str, Any]:
    metadata = {
        "room_id": node.room_id,
        "persona_id": node.persona_id,
    }
    return {key: value for key, value in metadata.items() if value}


def _clean_clarified_message(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None
