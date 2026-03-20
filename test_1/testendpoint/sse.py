import asyncio
import json
from collections import defaultdict
from typing import DefaultDict, Set 


# call_id -> set(queues)
_listeners: DefaultDict[str, Set[asyncio.Queue]] = defaultdict(set)
_lock = asyncio.Lock()

SSE_RETRY_MS = 1500

def _format_sse(data: dict, event: str = "message", event_id: str|int|None = None) -> str:
    """
    Build an SSE frame
    """
    payload = json.dumps(data, ensure_ascii=False)
    lines = []
    lines.append(f"event: {event}")
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"retry: {SSE_RETRY_MS}")
    lines.append(f"data: {payload}")
    lines.append("") # End of Frame ends the event
    return "\n".join(lines) + "\n"

async def subscribe(call_id: str) -> asyncio.Queue:
    """
    Register a new listener queue for a call_id.
    """
    q : asyncio.Queue = asyncio.Queue(maxsize=200)
    async with _lock:
        _listeners[call_id].add(q)
    return q

async def unsubscribe(call_id: str, q: asyncio.Queue):
    """
    Unregister a listener queue for a call_id.
    """
    async with _lock:
        if call_id in _listeners and q in _listeners[call_id]:
            _listeners[call_id].remove(q)
            if not _listeners[call_id]:
                del _listeners[call_id]

async def publish(call_id: str, event: str, data: dict, event_id: str|int|None = None):
    """"
    Push an even to all listeners of a call_id.
    Non-blocking - drops if queue is full.
    """

    frame = _format_sse(data=data, event=event, event_id=event_id)

    async with _lock:
        queues = list(_listeners.get(call_id, set()))

    for q in queues:
        try:
            q.put_nowait(frame)
        except asyncio.QueueFull:
            pass