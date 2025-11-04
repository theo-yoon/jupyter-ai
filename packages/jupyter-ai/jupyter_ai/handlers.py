from jupyter_ai.config_manager import ConfigManager, KeyEmptyError, WriteConflictError
from jupyter_server.base.handlers import APIHandler as BaseAPIHandler
from pydantic import ValidationError
from tornado import web
from tornado.web import HTTPError

from .config import UpdateConfigRequest
from .personas import PersonaManager


class CommandExecutionAckHandler(BaseAPIHandler):
    """Record the completion of a pending frontend command execution."""

    @property
    def persona_managers(self):
        return self.settings.get("jai_persona_managers", {})

    @web.authenticated
    def post(self):
        payload = self.get_json_body()
        if not isinstance(payload, dict):
            raise HTTPError(400, "Request body must be a JSON object.")

        room_id = payload.get("room_id")
        tool_call_id = payload.get("tool_call_id")
        status = payload.get("status")
        result = payload.get("result")
        message = payload.get("message")
        executor = payload.get("executor")

        if tool_call_id is None or not isinstance(tool_call_id, str) or not tool_call_id:
            raise HTTPError(400, "Missing required field 'tool_call_id'.")
        if status not in {"success", "error"}:
            raise HTTPError(400, "Field 'status' must be 'success' or 'error'.")

        persona_manager = None

        if isinstance(room_id, str) and room_id:
            persona_manager = self.persona_managers.get(room_id)

        if persona_manager is None:
            pending = PersonaManager.lookup_pending_tool_command(tool_call_id)
            if pending and pending.manager:
                persona_manager = pending.manager
                room_id = pending.room_id

        if persona_manager is None:
            if isinstance(room_id, str):
                raise HTTPError(404, f"No chat found for room_id '{room_id}'.")
            raise HTTPError(404, "No chat found for the provided tool call ID.")

        try:
            persona_manager.resolve_pending_tool_command(
                tool_call_id=tool_call_id,
                status=status,
                result=str(result) if result is not None else None,
                message=str(message) if message is not None else None,
                executor=str(executor) if executor is not None else None,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            self.log.exception(
                "Failed to resolve pending command %s for room %s", tool_call_id, room_id
            )
            raise HTTPError(500, "Failed to resolve pending tool command.") from exc

        self.set_status(204)
        self.finish()


class PlanApprovalHandler(BaseAPIHandler):
    """Record the approval or rejection of a pending plan."""

    @property
    def persona_managers(self):
        return self.settings.get("jai_persona_managers", {})

    @web.authenticated
    def post(self):
        payload = self.get_json_body()
        if not isinstance(payload, dict):
            raise HTTPError(400, "Request body must be a JSON object.")

        plan_id = payload.get("plan_id")
        decision_value = payload.get("decision")
        decision = decision_value.lower() if isinstance(decision_value, str) else None
        room_id = payload.get("room_id")

        auto_raw = payload.get("auto_approve")
        if isinstance(auto_raw, bool):
            auto_approve = auto_raw
        elif isinstance(auto_raw, str):
            auto_approve = auto_raw.lower() in {"1", "true", "yes", "on"}
        else:
            auto_approve = None

        if not plan_id or not isinstance(plan_id, str):
            raise HTTPError(400, "Missing required field 'plan_id'.")
        if decision not in {"approved", "rejected"}:
            raise HTTPError(400, "Field 'decision' must be 'approved' or 'rejected'.")

        persona_manager = None
        if isinstance(room_id, str) and room_id:
            persona_manager = self.persona_managers.get(room_id)
        if persona_manager is None:
            pending = PersonaManager.lookup_pending_plan(plan_id)
            if pending and pending.manager:
                persona_manager = pending.manager
                room_id = pending.room_id

        if persona_manager is None:
            if isinstance(room_id, str):
                raise HTTPError(404, f"No chat found for room_id '{room_id}'.")
            raise HTTPError(404, "No chat found for the provided plan ID.")

        try:
            pending = persona_manager.resolve_pending_plan(plan_id, decision)
            if auto_approve is not None:
                persona_manager.set_auto_approve_plans(auto_approve)
            elif decision == "rejected":
                persona_manager.set_auto_approve_plans(False)
        except KeyError as exc:
            raise HTTPError(404, f"Pending plan '{plan_id}' not found.") from exc
        except Exception as exc:  # pragma: no cover - defensive
            self.log.exception(
                "Failed to resolve pending plan %s for room %s", plan_id, room_id
            )
            raise HTTPError(500, "Failed to resolve pending plan.") from exc

        self.set_status(204)
        self.finish()


class GlobalConfigHandler(BaseAPIHandler):
    """API handler for fetching and setting the
    model and emebddings config.
    """

    @property
    def config_manager(self):
        return self.settings["jai_config_manager"]

    @web.authenticated
    def get(self):
        config = self.config_manager.get_config()
        if not config:
            raise HTTPError(500, "No config found.")

        self.finish(config.model_dump_json())

    @web.authenticated
    def post(self):
        try:
            config = UpdateConfigRequest(**self.get_json_body())
            self.config_manager.update_config(config)
            self.set_status(204)
            self.finish()
        except (ValidationError, WriteConflictError, KeyEmptyError) as e:
            self.log.exception(e)
            raise HTTPError(500, str(e)) from e
        except ValueError as e:
            self.log.exception(e)
            raise HTTPError(500, str(e.cause) if hasattr(e, "cause") else str(e))
        except Exception as e:
            self.log.exception(e)
            raise HTTPError(
                500, "Unexpected error occurred while updating the config."
            ) from e


class InterruptStreamingHandler(BaseAPIHandler):
    """Interrupt a current message streaming"""

    @web.authenticated
    def post(self):
        message_id = self.get_json_body().get("message_id")
        message_interrupted = self.settings.get("jai_message_interrupted")
        if message_id and message_id in message_interrupted.keys():
            message_interrupted[message_id].set()


class ChatMessageHandler(BaseAPIHandler):
    """Append a chat message to an existing chat room."""

    @property
    def persona_managers(self):
        return self.settings.get("jai_persona_managers", {})

    @web.authenticated
    def post(self):
        payload = self.get_json_body()
        if not isinstance(payload, dict):
            raise HTTPError(400, "Request body must be a JSON object.")

        room_id = payload.get("room_id")
        body = payload.get("body")

        if not room_id or not isinstance(room_id, str):
            raise HTTPError(400, "Missing required field 'room_id'.")

        if not body or not isinstance(body, str):
            raise HTTPError(400, "Missing required field 'body'.")

        persona_manager = self.persona_managers.get(room_id)
        if persona_manager is None:
            raise HTTPError(404, f"No chat found for room_id '{room_id}'.")

        role = payload.get("role", "system")

        if role == "system":
            persona_manager.send_system_message(body)
            self.set_status(204)
            self.finish()
            return

        if role != "user":
            raise HTTPError(400, f"Unsupported role '{role}'.")

        username, display_name = self._resolve_user_identity()
        if not username:
            raise HTTPError(403, "Unable to resolve current user identity.")

        persona_manager.send_user_message(
            username=username,
            body=body,
            display_name=display_name,
        )
        self.set_status(204)
        self.finish()

    def _resolve_user_identity(self) -> tuple[str | None, str | None]:
        """
        Resolves the current user's username and display name.
        """
        current = self.get_current_user()

        if current is None:
            return None, None

        username: str | None = None
        display_name: str | None = None

        if isinstance(current, dict):
            username = (
                current.get("name")
                or current.get("username")
                or current.get("user")
            )
            display_name = (
                current.get("display_name")
                or current.get("displayName")
                or username
            )
        elif hasattr(current, "username"):
            username = getattr(current, "username")
            display_name = getattr(current, "display_name", None)
            if display_name is None:
                display_name = getattr(current, "name", None) or username
        else:
            username = str(current)
            display_name = username

        return username, display_name
