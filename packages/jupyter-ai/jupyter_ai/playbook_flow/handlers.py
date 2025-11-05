from __future__ import annotations

import asyncio
import json

from jupyter_server.base.handlers import APIHandler
from tornado import web
from tornado.websocket import WebSocketClosedError, WebSocketHandler

from workflow.playbook_flow.broadcaster import playbook_broadcaster
from workflow.playbook_flow.repository import repository


def _build_run_payload(run):
    from workflow.playbook_flow.runtime.helpers import build_run_payload as _builder

    return _builder(run)


class PlaybookRunHandler(APIHandler):
    """Return the latest serialized payload for a playbook run."""

    SUPPORTED_METHODS = ("GET",)

    async def get(self, run_id: str):
        run = await repository.get(run_id)
        if run is None:
            raise web.HTTPError(404, reason="Playbook run not found")
        payload = _build_run_payload(run)
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
            await self.write_message(json.dumps(_build_run_payload(run)))
        except WebSocketClosedError:
            self.close()
