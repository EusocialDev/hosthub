# testendpoint/views_sse.py
import logging
from django.conf import settings
from django.http import StreamingHttpResponse, JsonResponse, Http404
from .models import PhoneNumber, CallSession
from .views import _normalize_phone_number
from asgiref.sync import sync_to_async
from .sse import subscribe, unsubscribe  # your async pubsub



logger = logging.getLogger(__name__)


async def sse_call_stream(request, call_id: str):
    # 1. Require Auth user
    user = request.user
    if not user.is_authenticated:
        return JsonResponse({"ok": False, "error": "authentication required"}, status=401)
    
    #2. Optional extra token gate
    expected = getattr(settings, "HOSTHUB_SSE_TOKEN", "")
    token = request.GET.get("token", "")
    if not expected or token != expected:
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)
    
    # 3. Resolve Hosthub access
    access = await sync_to_async(lambda: getattr(user, "hosthub_access", None))()
    if not access or not access.is_active:
        raise Http404("call not found or access denied")
    
    allowed_location_ids = await sync_to_async( 
        lambda: list(
                access.locations.filter(is_active=True)
                .values_list("id", flat=True)
        )    
    )()

    allowed_numbers = await sync_to_async(
        lambda: set(
            _normalize_phone_number(n)
            for n in PhoneNumber.objects.filter(
            account = access.account,
            location_id__in=allowed_location_ids,
            is_active=True,
            ).values_list("number", flat=True)
        )
    )()

    # 4. Resolev Live Session
    call_session = await CallSession.objects.filter(call_id=call_id).afirst()
    if not call_session:
        raise Http404("call not found")
    
    normalized_to = _normalize_phone_number(call_session.to_number)
    if not normalized_to or normalized_to not in allowed_numbers:
        raise Http404("call not found")
    
    # Logs (safe-ish: shows repr. Consider masking later.)
    logger.warning("SSE DEBUG call_id=%s expected=%r received=%r match=%s",
                   call_id, expected, token, token == expected)

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
