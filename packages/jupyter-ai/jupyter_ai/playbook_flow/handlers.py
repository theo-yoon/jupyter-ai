from __future__ import annotations

import asyncio
import json

from jupyter_server.base.handlers import APIHandler
from tornado import web
from tornado.websocket import WebSocketClosedError, WebSocketHandler

from . import build_run_payload, playbook_broadcaster, repository


class PlaybookRunHandler(APIHandler):
    """Return the latest serialized payload for a playbook run."""

    SUPPORTED_METHODS = ("GET",)

    async def get(self, run_id: str):
        run = await repository.get(run_id)
        if run is None:
            raise web.HTTPError(404, reason="Playbook run not found")
        payload = build_run_payload(run)
        self.set_status(200)
        self.finish(payload)


class PlaybookUpdatesWebSocketHandler(WebSocketHandler):
    """Stream realtime playbook updates to subscribed clients."""

    def initialize(self, *args, **kwargs):  # type: ignore[override]
        super().initialize(*args, **kwargs)
        self._unsubscribe = None

    def open(self, run_id: str):
        async def _listener(payload: dict):
            if self.ws_connection is None:
                return
            try:
                await self.write_message(json.dumps(payload))
            except WebSocketClosedError:
                self.close()

        self._unsubscribe = playbook_broadcaster.subscribe(run_id, _listener)
        asyncio.create_task(self._send_initial_snapshot(run_id))

    def on_close(self):
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    async def _send_initial_snapshot(self, run_id: str) -> None:
        run = await repository.get(run_id)
        if run is None or self.ws_connection is None:
            return
        try:
            await self.write_message(json.dumps(build_run_payload(run)))
        except WebSocketClosedError:
            self.close()
