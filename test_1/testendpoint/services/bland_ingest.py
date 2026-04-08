import hashlib
from django.db import transaction
from django.utils import timezone


from testendpoint.models import CallSession, TranscriptTurn
from testendpoint.services.alert_rules import evaluate_alerts_for_call

from testendpoint.sse import publish
from testendpoint.models import TranscriptTurn, CallSession
from asgiref.sync import async_to_sync

from testendpoint.utils.phone import _normalize_phone_number

AGENT_PREFIXES = ("Agent speech:", "Agent says:")
USER_PREFIXES = ("Handling user speech:", "User speech:")

def parse_bland_message(message:str):
    if not message:
        return None, None
    
    msg = message.strip()

    for p in AGENT_PREFIXES:
        if msg.startswith(p):
            return TranscriptTurn.Role.AGENT, msg[len(p):].strip()
        
    for p in USER_PREFIXES:
        if msg.startswith(p):
            return TranscriptTurn.Role.USER, msg[len(p):].strip()
        
    return None, None

def _dedupe_hash(role:str, text:str) -> str:
    norm = f"{role}|{text.strip()}"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()



@transaction.atomic
def ingest_bland_webhook_event(payload: dict) -> CallSession:
    call_id = payload.get("call_id")
    if not call_id:
        raise ValueError("Missing call_id")
    
    now = timezone.now()

    call, _ =CallSession.objects.select_for_update().get_or_create(
        call_id=call_id,
        defaults={
            "status": CallSession.Status.ACTIVE,
            "started_at": now,
            "last_event_at": now,
        },
    )

    # Keep ACTIVE while events come in
    if call.status != CallSession.Status.ACTIVE:
        call.status = CallSession.Status.ACTIVE
        if not call.started_at:
            call.started_at = now

    raw_from = payload.get("from")
    raw_to = payload.get("to")

    print("TOP LEVEL TO:", payload.get("to"))
    print("NESTED TO:", (payload.get("call") or {}).get("to"))
    print("PAYLOAD KEYS:", payload.keys())

    if raw_from:
        call.from_number = _normalize_phone_number(raw_from)
    if raw_to:
        call.to_number = _normalize_phone_number(raw_to)

    call.last_event_at = now
    call.save(update_fields=['status', 'started_at', 'last_event_at', "updated_at", "from_number", "to_number"])

    role, text = parse_bland_message(payload.get("message", ""))

    if role and text:
        dh = _dedupe_hash(role, text)

        recent = (
            TranscriptTurn.objects
            .filter(call=call)
            .order_by("-created_at")
            .only("dedupe_hash")[:5]
        )

        if any (t.dedupe_hash == dh for t in recent if t.dedupe_hash):
            evaluate_alerts_for_call(call)
            return call
        
        last_seq = (
            TranscriptTurn.objects
            .filter(call=call, sequence__isnull=False)
            .order_by("-sequence")
            .values_list("sequence", flat=True)
            .first()
        ) or 0 

        next_seq = last_seq + 1

        turn = TranscriptTurn.objects.create(
            call=call,
            role=role,
            text=text,
            sequence=next_seq,
            dedupe_hash=dh,
        )

        # ------------ SSE Publish ------------
        async_to_sync(publish)(
                    call_id,                   # positional (matches publish signature)
                    "turn",                    # event
                    {
                        "call_id": call_id,
                        "sequence": turn.sequence,
                        "role": turn.role,
                        "text": turn.text,
                        "created_at": turn.created_at.isoformat() if turn.created_at else None,
                    },
                    event_id=turn.sequence,    # optional kw arg OK
        )
    evaluate_alerts_for_call(call)
    return call
