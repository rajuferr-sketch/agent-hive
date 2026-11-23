"""Bidirectional universal WebSocket connector (``/ws/universal``).

Protocol (JSON frames, one per line):

* client → server: ``{"id": "...", "action": "universal.request",
  "payload": {...UniversalRequest fields...}}`` or
  ``{"id": "...", "action": "tool.call",
  "payload": {"name": "...", "arguments": {...}}}`` or
  ``{"id": "...", "action": "resume",
  "payload": {"session_id": "...", "instruction": "..."}}``
* server → client: ``{"id": "...", "ok": true|false, "data"| "error"}``
* the plain event stream (``/ws``) remains available for firehose use.

Frames are processed sequentially per connection; a bad frame yields
``{"ok": false, "error": {...}}`` and never kills the connection.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agent_hive.core.logging import get_logger
from agent_hive.gateway.gateway import UniversalRequest

log = get_logger("agent_hive.connectors.ws")


def build_ws_router(app_state) -> APIRouter:  # noqa: ANN001
    router = APIRouter()

    @router.websocket("/ws/universal")
    async def universal_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        hive = app_state.hive()
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    frame = json.loads(raw)
                    if not isinstance(frame, dict):
                        raise ValueError("frame must be a JSON object")
                except ValueError as exc:
                    await websocket.send_text(json.dumps({
                        "ok": False,
                        "error": {"code": "bad_frame", "message": str(exc)},
                    }))
                    continue

                frame_id = str(frame.get("id") or "")
                action = str(frame.get("action") or "")
                payload = frame.get("payload") or {}
                try:
                    if action == "universal.request":
                        response = await hive.gateway.handle(
                            UniversalRequest(
                                instruction=str(payload.get("instruction") or ""),
                                client_id=str(payload.get("client_id") or "ws"),
                                client_kind="ws",
                                session_id=str(payload.get("session_id") or "global"),
                                user_id=str(payload.get("user_id") or "default"),
                                project_id=str(payload.get("project_id") or "default"),
                            )
                        )
                        await websocket.send_text(json.dumps({
                            "id": frame_id, "ok": response.ok,
                            "data": response.data if response.ok else None,
                            "error": response.error,
                        }, ensure_ascii=False, default=str))
                    elif action == "tool.call":
                        outcome = await hive.gateway.tool_call(
                            str(payload.get("name") or ""),
                            payload.get("arguments") or {},
                            client="ws",
                        )
                        await websocket.send_text(json.dumps(
                            {"id": frame_id, **outcome},
                            ensure_ascii=False, default=str,
                        ))
                    elif action == "resume":
                        response = await hive.gateway.resume(
                            str(payload.get("session_id") or ""),
                            str(payload.get("instruction") or ""),
                            client_id=str(payload.get("client_id") or "ws"),
                            client_kind="ws",
                        )
                        await websocket.send_text(json.dumps({
                            "id": frame_id, "ok": response.ok,
                            "data": response.data if response.ok else None,
                            "error": response.error,
                        }, ensure_ascii=False, default=str))
                    elif action == "ping":
                        await websocket.send_text(json.dumps(
                            {"id": frame_id, "ok": True, "data": {"pong": True}}
                        ))
                    else:
                        await websocket.send_text(json.dumps({
                            "id": frame_id, "ok": False,
                            "error": {"code": "unknown_action",
                                      "message": f"action '{action}' not supported"},
                        }))
                except Exception as exc:  # noqa: BLE001 — reply, keep socket
                    log.exception("ws action failed")
                    await websocket.send_text(json.dumps({
                        "id": frame_id, "ok": False,
                        "error": {"code": "internal_error", "message": str(exc)[:300]},
                    }))
        except WebSocketDisconnect:
            log.debug("universal ws client disconnected")

    return router
