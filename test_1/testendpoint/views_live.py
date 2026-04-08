from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.http import JsonResponse, HttpResponseNotAllowed
from django.contrib.auth.decorators import login_required
from django.http import Http404
from .views import _normalize_phone_number

from testendpoint.models import CallAlert, CallSession, TranscriptTurn, PhoneNumber

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

    
    access = getattr(request.user, "has_access_to_call", None)
    
    if not access or not access.is_active:
        raise Http404("call not found or access denied")
    allowed_location_ids = access.locations.filter(
        is_active=True,
    ).values_list("id", flat=True)

    allowed_numbers = set(PhoneNumber.objects.filter(
        account = access.account,
        location_id__in=allowed_location_ids,
        is_active=True,
    ).values_list("number", flat=True)
    )

    call_session = CallSession.objects.filter(call_id=call_id).first()
    if not call_session:
        raise Http404("call not found")
    
    normalized_to = _normalize_phone_number(call_session.to_number)
    if not normalized_to or normalized_to not in allowed_numbers:
        raise Http404("call not found or access denied")
    
    
    qs = (TranscriptTurn.objects
          .filter(call=call_session)
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