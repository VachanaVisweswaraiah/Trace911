import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db import SessionLocal
from app.pubsub import broker
from app.repository import calls as calls_repo

router = APIRouter()


@router.websocket("/ws/calls/{call_id}")
async def call_ws(websocket: WebSocket, call_id: str) -> None:
    # Verify the call exists + grab the snapshot for replay.
    async with SessionLocal() as db:
        snap = await calls_repo.snapshot(db, call_id)
        call = await calls_repo.get(db, call_id) if snap else None
    if snap is None or call is None:
        await websocket.close(code=4404)
        return

    # Make sure the broker knows when this call started (e.g. after a server restart).
    broker.register_call(call_id, call.started_at)

    await websocket.accept()
    queue = broker.subscribe(call_id)

    await websocket.send_json({
        "type": "snapshot",
        "t": broker.t_for(call_id),
        "payload": snap.model_dump(mode="json"),
    })

    sender = asyncio.create_task(_forward(websocket, queue))
    try:
        while True:
            msg = await websocket.receive_json()
            await _handle_client_message(call_id, msg)
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        broker.unsubscribe(call_id, queue)


async def _forward(ws: WebSocket, queue: asyncio.Queue) -> None:
    try:
        while True:
            msg = await queue.get()
            await ws.send_json(msg)
    except asyncio.CancelledError:
        return


async def _handle_client_message(call_id: str, msg: dict) -> None:
    kind = msg.get("type")
    if kind == "audio_frame":
        # TODO: push frame into services.audio_enhancement
        return
    if kind == "operator_event":
        payload = msg.get("payload") or {}
        # TODO: route confirm / override / ask to extraction + assist services
        await broker.publish(call_id, "operator_event_ack", payload)
