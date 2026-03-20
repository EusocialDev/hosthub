from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.http import JsonResponse, HttpResponseNotAllowed
from django.contrib.auth.decorators import login_required

from testendpoint.models import CallAlert, CallSession, TranscriptTurn

@require_GET
def live_alerts_poll(request):
    limit = int(request.GET.get("limit", 10))
    alerts = (
        CallAlert.objects.filter(resolved_at__isnull=True).select_related("call").order_by("-created_at")[:limit]
    )

    data = [{
        "id": a.id,
        "call_id": a.call.call_id,
        "severity": a.severity,
        "reason_code":a.reason_code,
        "message":a.message,
        "from_number": a.call.from_number,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    } for a in alerts]

    return JsonResponse({"server_time": timezone.now().isoformat(), "alerts": data})

@require_POST
def resolve_alert(request, alert_id: int):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    updated = CallAlert.objects.filter(id=alert_id, resolved_at__isnull=True).update(
        resolved_at=timezone.now()
    )

    return JsonResponse({"ok": True, "updated":bool(updated)})

#######   Live Transcript Endpoints   ########

@require_GET
@login_required
def get_transcript_turns(request, call_id:str):
    limit = int(request.GET.get("limit", 200))

    call = CallSession.objects.filter(call_id=call_id).first()
    if not call:
        return JsonResponse({"ok": True, "call_id": call_id, "turns": []})
    
    qs = (TranscriptTurn.objects
          .filter(call=call)
          .order_by("sequence", "id")[:limit]
          )

    turns = [
        {
            "sequence": t.sequence,
            "role": t.role,
            "text": t.text,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in qs
    ]

    return JsonResponse({"ok":True, "call_id":call_id, "turns": turns})