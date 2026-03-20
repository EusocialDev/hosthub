from django.utils import timezone
from testendpoint.models import CallSession, CallAlert, TranscriptTurn
from datetime import timedelta

import re

HUMAN_REQUEST_PHRASES = (
    "manager",
    "manger",              # common misspelling
    "representative",
    "rep",
    "real person",
    "human",
    "someone else",
    "real host",
    "operator",
    "supervisor",
    "talk to a person",
    "talk to someone",
    "talk to a human",
    "speak to a person",
    "speak to someone",
    "speak to a human",
    "speak to a manager",
    "speak to representative",
    "transfer me",
    "transfer to a person",
    "transfer to a human",
)

NO_USER_RESPONSE_SECONDS = 30
AGENT_LOOP_COUNT = 2
AGENT_LOOP_WINDOW_SECONDS = 60

def _normalize_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)   # drop punctuation
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _user_requests_human(text: str) -> bool:
    t = _normalize_text(text)
    if not t:
        return False
    return any(phrase in t for phrase in HUMAN_REQUEST_PHRASES)

# <------------ Helpers ----------------->

def _ensure_alert(call: CallSession, severity: str, reason_code: str, message:str) -> None:
    if CallAlert.objects.filter(call=call, resolved_at__isnull=True, reason_code=reason_code).exists():
        return
    CallAlert.objects.create(call=call, severity=severity, reason_code=reason_code, message=message)

def evaluate_alerts_for_call(call: CallSession) -> None:
    if call.status != CallSession.Status.ACTIVE:
        return
    
    now = timezone.now()

    # A) No user response
    last_user = (
        TranscriptTurn.objects.filter (call=call, role=TranscriptTurn.Role.USER).order_by("-created_at").first()
    )

    # A0) User requests a human
    if last_user and _user_requests_human(last_user.text):
        _ensure_alert(
            call,
            severity=CallAlert.Severity.RED,
            reason_code="HUMAN_REQUEST",
            message="User requested a manager/representative/real person.",
        )


    # B) agent looping 
    window_start = now - timedelta(seconds=AGENT_LOOP_WINDOW_SECONDS)
    recent_agent = list(
        TranscriptTurn.objects.filter(
            call=call,
            role=TranscriptTurn.Role.AGENT,
            created_at__gte=window_start,
        ).order_by("-created_at")[:10]
    )
    if len(recent_agent) >= AGENT_LOOP_COUNT:
        counts={}
        for t in recent_agent:
            txt = (t.text or '').strip()
            if not txt:
                continue
            counts[txt]=counts.get(txt, 0) + 1

        top_text, top_count = None, 0
        for txt, c in counts.items():
            if c > top_count:
                top_text, top_count = txt, c
        if top_text and top_count >= AGENT_LOOP_COUNT:
            _ensure_alert(
                call,
                severity=CallAlert.Severity.RED,
                reason_code="AGENT_LOOP",
                message=f"Agent repeated the same message {top_count}x (call is possibly stuck)."
            )

