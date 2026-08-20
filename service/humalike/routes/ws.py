"""WSS gateway (spec/02 §WebSocket protocol, spec/03 §WebSocket frames).

The upgrade always completes; an expired or garbage grant then closes with
code 4000 and an empty reason. A valid grant attaches the socket to its
channel and sends the distinct three-field attached frame. An established
connection does not depend on continued grant validity.
"""

from __future__ import annotations

from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect

from .. import metrics
from ..fanout import registry
from ..grants import validate
from ..timefmt import ts_offset, utcnow

router = APIRouter()


@router.websocket("/v1/ws/turn-taking-thread")
async def turn_taking_thread(websocket: WebSocket) -> None:
    await websocket.accept()
    token = websocket.query_params.get("token") or ""
    payload = validate(token)
    if payload is None:
        await websocket.close(code=4000, reason="")
        metrics.record_ws_close(4000)
        return
    channel = payload["c"]
    await registry.register(channel, websocket)
    metrics.record_ws_connection()
    try:
        await websocket.send_json({
            "type": "attached",
            "channel": channel,
            "server_time": ts_offset(utcnow()),
        })
        while True:
            # Inbound client messages are not part of the tested contract.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await registry.unregister(channel, websocket)
        metrics.record_ws_close(1000)
