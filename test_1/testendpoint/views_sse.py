# testendpoint/views_sse.py
import logging
from django.conf import settings
from django.http import StreamingHttpResponse, JsonResponse

from .sse import subscribe, unsubscribe  # your async pubsub

logger = logging.getLogger(__name__)


async def sse_call_stream(request, call_id: str):
    expected = getattr(settings, "HOSTHUB_SSE_TOKEN", "")
    token = request.GET.get("token", "")

    # Logs (safe-ish: shows repr. Consider masking later.)
    logger.warning("SSE DEBUG call_id=%s expected=%r received=%r match=%s",
                   call_id, expected, token, token == expected)

    if not expected or token != expected:
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    q = await subscribe(call_id)

    async def event_stream():
        try:
            # comment keeps connection alive
            yield ": connected\n\n"

            while True:
                frame = await q.get()   # frame should already be "event: ...\ndata: ...\n\n"
                yield frame
        finally:
            await unsubscribe(call_id, q)

    resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["Connection"] = "keep-alive"
    resp["X-Accel-Buffering"] = "no"
    return resp
