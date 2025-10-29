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


class CommandResultHandler(BaseAPIHandler):
    """Receive command results from the frontend and resolve pending tool calls."""

    @web.authenticated
    async def post(self):
        payload = self.get_json_body() or {}
        request_id = payload.get("request_id")
        if not request_id or not isinstance(request_id, str):
            raise HTTPError(400, "`request_id` must be provided")

        status = payload.get("status")
        if not status or not isinstance(status, str):
            raise HTTPError(400, "`status` must be provided")
        status_lower = status.lower()
        if status_lower not in {"ok", "error"}:
            raise HTTPError(400, "`status` must be either 'ok' or 'error'")

        result_payload = {
            "request_id": request_id,
            "status": status_lower,
        }
        from .tools.pending_commands import resolve_pending_command  # defer to avoid circular import

        if "result" in payload:
            result_payload["result"] = payload["result"]
        if "error" in payload:
            result_payload["error"] = payload["error"]
        if "metadata" in payload:
            result_payload["metadata"] = payload["metadata"]

        resolved = resolve_pending_command(request_id, result_payload)
        if not resolved:
            raise HTTPError(404, f"Unknown command request_id: {request_id}")

        self.set_status(204)
        self.finish()
