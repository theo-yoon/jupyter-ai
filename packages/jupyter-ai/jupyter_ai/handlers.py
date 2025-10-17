from jupyter_ai.config_manager import ConfigManager, KeyEmptyError, WriteConflictError
from jupyter_server.base.handlers import APIHandler as BaseAPIHandler
from pydantic import ValidationError
from tornado import web
from tornado.web import HTTPError

from .config import UpdateConfigRequest


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
