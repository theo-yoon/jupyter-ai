from jupyterlab_chat.models import Message

from ..base_persona import BasePersona, PersonaDefaults
from ...default_flow import run_routing_flow, DefaultFlowParams
from ...workflow.common.repositories.voc_repository import build_coordinator_from_env
from .prompt_template import (
    JUPYTERNAUT_SYSTEM_PROMPT_TEMPLATE,
    JupyternautSystemPromptArgs,
)
from ...tools import AGENT_TOOLKIT


class JupyternautPersona(BasePersona):
    """
    The Jupyternaut persona, the main persona provided by Jupyter AI.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._knowledge_coordinator = build_coordinator_from_env(
            logger=self.log,
            config_manager=self.config_manager,
        )

    @property
    def defaults(self):
        return PersonaDefaults(
            name="Jupyternaut",
            avatar_path="/api/ai/static/jupyternaut.svg",
            description="The standard agent provided by JupyterLab. Currently has no tools.",
            system_prompt="...",
        )

    async def process_message(self, message: Message) -> None:
        # Return early if no chat model is configured
        if not self.config_manager.chat_model:
            self.send_message(
                "No chat model is configured.\n\n"
                "You must set one first in the Jupyter AI settings, found in 'Settings > AI Settings' from the menu bar."
            )
            return

        # Build default flow params
        system_prompt = self._build_system_prompt(message)
        flow_params: DefaultFlowParams = {
            "persona_id": self.id,
            "model_id": self.config_manager.chat_model,
            "model_args": self.config_manager.chat_model_args,
            "ychat": self.ychat,
            "awareness": self.awareness,
            "system_prompt": system_prompt,
            "toolkit": AGENT_TOOLKIT,
            "logger": self.log,
            "room_id": getattr(self.parent, "room_id", None),
            "_session_state": self.session_state,
        }
        if self._knowledge_coordinator:
            flow_params["knowledge_coordinator"] = self._knowledge_coordinator

        # Run default agent flow
        await run_routing_flow(flow_params)

    def _build_system_prompt(self, message: Message) -> str:
        context = self.process_attachments(message)
        format_args = JupyternautSystemPromptArgs(
            persona_name=self.name,
            model_id=self.config_manager.chat_model,
            context=context,
        )
        system_prompt = JUPYTERNAUT_SYSTEM_PROMPT_TEMPLATE.render(format_args.model_dump())
        return system_prompt
