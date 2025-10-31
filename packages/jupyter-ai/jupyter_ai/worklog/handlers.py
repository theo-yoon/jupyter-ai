"""HTTP and WebSocket handlers for worklog interactions."""

from __future__ import annotations

import json
from typing import Callable, Literal

from jupyter_server.base.handlers import APIHandler
from tornado import web
from tornado.websocket import WebSocketHandler, WebSocketClosedError

from .controller import WorklogController
from .broadcaster import WorklogUpdateBroadcaster

WorklogAction = Literal["pause", "resume", "stop"]


class WorklogRunStateHandler(APIHandler):
    """Handle pause/resume/stop requests from the UI."""

    SUPPORTED_METHODS = ("POST",)

    def initialize(self, *args, **kwargs):  # type: ignore[override]
        super().initialize(*args, **kwargs)
        controller = self.settings.get("jai_worklog_controller")
        if not isinstance(controller, WorklogController):
            raise web.HTTPError(500, reason="Worklog controller unavailable")
        self._controller: WorklogController = controller

    async def post(self, entry_id: str):
        body = self.get_json_body() or {}
        action = body.get("action")
        if action not in {"pause", "resume", "stop"}:
            raise web.HTTPError(400, reason="Invalid action")

        patch = await self._apply_action(entry_id, action)
        self.set_status(200)
        self.write(patch.model_dump_non_null())

    async def _apply_action(self, entry_id: str, action: WorklogAction):
        if action == "pause":
            return await self._controller.pause(entry_id)
        if action == "resume":
            return await self._controller.resume(entry_id)
        return await self._controller.stop(entry_id)


class WorklogUpdatesWebSocketHandler(WebSocketHandler):
    """Stream realtime worklog patches to subscribed clients."""

    def initialize(self, *args, **kwargs):  # type: ignore[override]
        super().initialize(*args, **kwargs)
        broadcaster = self.settings.get("jai_worklog_broadcaster")
        if not isinstance(broadcaster, WorklogUpdateBroadcaster):
            raise web.HTTPError(500, reason="Worklog broadcaster unavailable")
        self._broadcaster: WorklogUpdateBroadcaster = broadcaster
        self._unsubscribe: Callable[[], None] | None = None

    def open(self, entry_id: str):
        self._unsubscribe = self._broadcaster.subscribe(entry_id, self._send_patch)

    def on_close(self):
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    async def _send_patch(self, payload: dict) -> None:
        if self.ws_connection is None:
            return
        try:
            await self.write_message(json.dumps(payload))
        except WebSocketClosedError:
            self.close()
