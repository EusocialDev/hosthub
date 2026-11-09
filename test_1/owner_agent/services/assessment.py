"""Deterministic owner-agent follow-up assessment.

This module deliberately does not call an LLM. It combines authoritative
HostHub fields with optional structured analysis produced elsewhere.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil import parser as date_parser
from dateutil.parser import ParserError
from django.utils import timezone as django_timezone

from ..models import OwnerAgentAssessment


DATE_KEYS = ("date", "date_requested", "party_date", "reservation_date")
TIME_KEYS = ("time", "party_time", "reservation_time")
GUEST_KEYS = ("guests", "guest", "number_of_people", "party_size")
REQUEST_KEYS = (
    "request",
    "user_request",
    "reason_for_calling",
    "reason",
    "party_message",
)
CALLBACK_KEYS = (
    "callback",
    "callback_requested",
    "needs_callback",
    "manager_callback",
    "follow_up",
)

CARRYOUT_HANDOFF_PATTERNS = (
    r"shared .* with (?:the )?(?:kitchen|team)",
    r"shared .* (?:to|with) (?:the )?(?:kitchen|team)",
    r"(?:kitchen|team) (?:has )?(?:already )?started preparing",
    r"(?:sent|passed) .* order .* (?:to|with) (?:the )?(?:kitchen|team)",
)

BOOKING_LINK_PATTERNS = (
    r"(?:sent|send|text|texted|shared|provide|provided) .*\b(?:booking|reservation) link",
    r"link .* (?:to|for) (?:complete|finalize|make) .* reservation",
)

FALSE_VALUES = {"", "0", "false", "no", "none", "null", "n/a"}


@dataclass(frozen=True)
class AssessmentResult:
    status: str
    reason: str
    explanation: str
    evaluated_for_date: date
    basis: dict[str, Any]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_value(values: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = values.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _valid_timezone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "America/Detroit")
    except (ZoneInfoNotFoundError, TypeError):
        return ZoneInfo("America/Detroit")


def _localize(value: datetime, tz: ZoneInfo) -> datetime:
    if django_timezone.is_naive(value):
        return django_timezone.make_aware(value, timezone=tz)
    return value.astimezone(tz)


def _reference_datetime(call: Any, evaluation_time: datetime | None, tz: ZoneInfo) -> datetime:
    if evaluation_time is not None:
        return _localize(evaluation_time, tz)

    now = django_timezone.now()
    if now is not None:
        return _localize(now, tz)

    created_at = getattr(call, "created_at", None)
    if created_at:
        return _localize(created_at, tz)

    return datetime.now(tz)


def _call_local_date(call: Any, tz: ZoneInfo, fallback: date) -> date:
    created_at = getattr(call, "created_at", None)
    if created_at:
        return _localize(created_at, tz).date()
    return fallback


def _parse_date(value: Any, reference_date: date, tz: ZoneInfo) -> date | None:
    if isinstance(value, datetime):
        return _localize(value, tz).date()
    if isinstance(value, date):
        return value

    text = _clean_text(value)
    normalized = text.lower().strip()
    if not normalized or normalized in FALSE_VALUES:
        return None

    relative_days = {
        "today": 0,
        "tonight": 0,
        "tomorrow": 1,
        "tomorrow night": 1,
        "yesterday": -1,
    }
    if normalized in relative_days:
        return reference_date + timedelta(days=relative_days[normalized])

    weekday_match = re.search(
        r"\b(?:(this|next|coming)\s+)?"
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        normalized,
    )
    if weekday_match:
        modifier = weekday_match.group(1)
        target_weekday = (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ).index(weekday_match.group(2))
        days_ahead = (target_weekday - reference_date.weekday()) % 7
        if modifier in {"next", "coming"} and days_ahead == 0:
            days_ahead = 7
        return reference_date + timedelta(days=days_ahead)

    try:
        parsed = date_parser.parse(
            text,
            fuzzy=True,
            default=datetime.combine(reference_date, time.min),
        )
    except (TypeError, ValueError, OverflowError, ParserError):
        return None

    return parsed.date()


def _parse_time(value: Any) -> time | None:
    if isinstance(value, datetime):
        return value.time().replace(tzinfo=None)
    if isinstance(value, time):
        return value.replace(tzinfo=None)

    text = _clean_text(value)
    if not text or text.lower() in FALSE_VALUES:
        return None

    try:
        parsed = date_parser.parse(text, default=datetime(2000, 1, 1))
    except (TypeError, ValueError, OverflowError, ParserError):
        return None
    return parsed.time().replace(tzinfo=None)


def _parse_guest_count(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None

    text = _clean_text(value)
    if not text or re.search(r"\bto\b|[-–]", text, flags=re.IGNORECASE):
        return None
    match = re.fullmatch(r"\s*(\d+)\s*", text)
    return int(match.group(1)) if match else None


def _user_texts(call: Any) -> tuple[list[str], bool]:
    """Return user turns and whether a transcript source was available."""

    transcript_rows = getattr(call, "transcripts", None)
    if isinstance(transcript_rows, list):
        user_texts = []
        for row in transcript_rows:
            if not isinstance(row, dict):
                continue
            role = str(row.get("user") or row.get("role") or "").lower()
            if role not in {"user", "caller", "customer"}:
                continue
            text = _clean_text(row.get("text"))
            if text:
                user_texts.append(text)
        return user_texts, True

    full_transcript = _clean_text(getattr(call, "full_transcript", ""))
    if not full_transcript:
        return [], False

    matches = re.findall(
        r"(?im)^\s*(?:user|caller|customer)\s*:\s*(.*)$",
        full_transcript,
    )
    if matches:
        return [text.strip() for text in matches if text.strip()], True

    return [], False


def _has_callback_request(call: Any, variables: dict[str, Any]) -> bool:
    for key in CALLBACK_KEYS:
        value = variables.get(key)
        if value is None:
            continue
        text = _clean_text(value).lower()
        if text and text not in FALSE_VALUES:
            return True

    searchable = " ".join(
        _clean_text(value)
        for value in (
            getattr(call, "summary", ""),
            getattr(call, "notes", ""),
            _first_value(variables, REQUEST_KEYS),
        )
    ).lower()
    if re.search(r"\b(?:no|not|without)\s+(?:a\s+)?callback\b", searchable):
        return False
    return bool(re.search(r"\bcallback\b|\bcall\s+back\b|\bfollow[- ]?up\b", searchable))


def _analysis_value(analysis: Any, field: str) -> Any:
    return getattr(analysis, field, None) if analysis is not None else None


def _get_analysis(call: Any, analysis: Any | None) -> Any | None:
    # Callers must explicitly provide an analysis result. This keeps the
    # deterministic baseline stable and avoids hidden database lookups during
    # previews or comparisons.
    return analysis


def _searchable_call_text(call: Any) -> str:
    parts = [
        _clean_text(getattr(call, "summary", "")),
        _clean_text(getattr(call, "notes", "")),
        _clean_text(getattr(call, "full_transcript", "")),
    ]
    transcript_rows = getattr(call, "transcripts", None)
    if isinstance(transcript_rows, list):
        parts.extend(
            _clean_text(row.get("text"))
            for row in transcript_rows
            if isinstance(row, dict)
        )
    return " ".join(part for part in parts if part).lower()


def _explicit_carryout_handoff(call: Any) -> bool:
    text = _searchable_call_text(call)
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in CARRYOUT_HANDOFF_PATTERNS)


def _explicit_booking_link(call: Any) -> bool:
    text = _searchable_call_text(call)
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in BOOKING_LINK_PATTERNS)


def _effective_bool(analysis: Any, field: str, fallback: bool | None) -> bool | None:
    value = _analysis_value(analysis, field)
    return fallback if value is None else bool(value)


def _reservation_fields(call: Any, analysis: Any | None, tz: ZoneInfo) -> tuple[date | None, time | None, int | None]:
    variables = _as_dict(getattr(call, "variables", None))
    analysis_date = _analysis_value(analysis, "reservation_date")
    analysis_time = _analysis_value(analysis, "reservation_time")
    analysis_guests = _analysis_value(analysis, "guest_count")

    call_date = _call_local_date(call, tz, datetime.now(tz).date())
    raw_date = analysis_date or _first_value(variables, DATE_KEYS)
    raw_time = analysis_time or _first_value(variables, TIME_KEYS)
    raw_guests = analysis_guests or _first_value(variables, GUEST_KEYS)

    return (
        _parse_date(raw_date, call_date, tz),
        _parse_time(raw_time),
        _parse_guest_count(raw_guests),
    )


def _commitment_state(
    reservation_date: date | None,
    reservation_time: time | None,
    reference: datetime,
) -> str:
    if reservation_date is None:
        return "unknown"
    if reservation_date > reference.date():
        return "future"
    if reservation_date < reference.date():
        return "past"
    if reservation_time is None:
        return "unknown"
    return "future" if reservation_time > reference.time().replace(tzinfo=None) else "past"


def assess_call(
    call: Any,
    *,
    evaluation_time: datetime | None = None,
    evaluated_for_date: date | None = None,
    timezone_name: str | None = None,
    analysis: Any | None = None,
) -> AssessmentResult:
    """Assess one call without making an LLM or external-service request."""

    location = getattr(call, "location", None)
    location_timezone = getattr(location, "timezone", None)
    tz = _valid_timezone(timezone_name or location_timezone)
    reference = _reference_datetime(call, evaluation_time, tz)
    report_date = evaluated_for_date or reference.date()
    analysis = _get_analysis(call, analysis)
    variables = _as_dict(getattr(call, "variables", None))

    basis: dict[str, Any] = {
        "host_status": getattr(call, "host_status", None),
        "handled_at": getattr(call, "handled_at", None).isoformat()
        if getattr(call, "handled_at", None)
        else None,
        "display_category": getattr(call, "display_category", None),
        "disposition": getattr(call, "disposition", None),
    }

    # HostHub's handled state is authoritative and always wins.
    if getattr(call, "host_status", None) == "resolved" or getattr(call, "handled_at", None):
        return AssessmentResult(
            status=OwnerAgentAssessment.Status.HANDLED,
            reason=OwnerAgentAssessment.Reason.HOSTHUB_HANDLED,
            explanation="The call is marked handled in HostHub.",
            evaluated_for_date=report_date,
            basis=basis,
        )

    meaningful = _analysis_value(analysis, "meaningful_conversation")
    if meaningful is None:
        user_texts, transcript_available = _user_texts(call)
        if transcript_available:
            meaningful = bool(user_texts)
        else:
            meaningful = None
        basis["user_turn_count"] = len(user_texts)
        basis["transcript_available"] = transcript_available
    else:
        basis["meaningful_conversation_source"] = "owner_agent_analysis"

    if meaningful is False:
        return AssessmentResult(
            status=OwnerAgentAssessment.Status.CONTEXT_ONLY,
            reason=OwnerAgentAssessment.Reason.SILENT_CALL,
            explanation="The call did not contain meaningful customer speech.",
            evaluated_for_date=report_date,
            basis=basis,
        )

    workflow = _analysis_value(analysis, "workflow") or ""
    searchable_text = _searchable_call_text(call)
    if not workflow:
        if getattr(call, "display_category", None) == "reservation":
            if re.search(r"\b(cancel|cancell?ation|change|modify|move|update)\b", searchable_text):
                workflow = (
                    "reservation_cancel"
                    if re.search(r"\bcancel|cancell?ation\b", searchable_text)
                    else "reservation_change"
                )
            else:
                workflow = "reservation_new"
        elif getattr(call, "display_category", None) in {"private_event", "private_events"}:
            workflow = "private_event_new"
        elif getattr(call, "display_category", None) == "carryout":
            workflow = "carryout"

    booking_link_sent = _effective_bool(analysis, "booking_link_sent", _explicit_booking_link(call))
    kitchen_share_completed = _effective_bool(
        analysis,
        "kitchen_share_completed",
        _explicit_carryout_handoff(call),
    )
    details_shared_with_manager = _analysis_value(analysis, "details_shared_with_manager")
    manager_review_required = _analysis_value(analysis, "manager_review_required")
    customer_waiting_confirmation = _analysis_value(analysis, "customer_waiting_confirmation")

    basis.update(
        {
            "workflow": workflow,
            "booking_link_sent": booking_link_sent,
            "kitchen_share_completed": kitchen_share_completed,
            "details_shared_with_manager": details_shared_with_manager,
            "manager_review_required": manager_review_required,
            "customer_waiting_confirmation": customer_waiting_confirmation,
        }
    )

    # Carryout has a specific completion checkpoint in the conversation. If
    # OpenAI confirms the kitchen handoff was reached, this is context-only;
    # otherwise an unhandled carryout is potentially incomplete.
    if getattr(call, "display_category", None) == "carryout":
        if kitchen_share_completed is True:
            return AssessmentResult(
                status=OwnerAgentAssessment.Status.CONTEXT_ONLY,
                reason=OwnerAgentAssessment.Reason.CARRYOUT_SHARED_WITH_KITCHEN,
                explanation="The AI explicitly shared the carryout details with the kitchen.",
                evaluated_for_date=report_date,
                basis=basis,
            )
        return AssessmentResult(
            status=OwnerAgentAssessment.Status.NEEDS_ATTENTION,
            reason=OwnerAgentAssessment.Reason.INCOMPLETE_CARRYOUT,
            explanation="The carryout conversation did not reach the kitchen handoff confirmation.",
            evaluated_for_date=report_date,
            basis=basis,
        )

    reservation_date, reservation_time, guest_count = _reservation_fields(call, analysis, tz)
    commitment_state = _commitment_state(reservation_date, reservation_time, reference)
    callback_requested = bool(_analysis_value(analysis, "future_commitment")) or _has_callback_request(
        call,
        variables,
    )

    basis.update(
        {
            "reservation_date": reservation_date.isoformat() if reservation_date else None,
            "reservation_time": reservation_time.isoformat() if reservation_time else None,
            "guest_count": guest_count,
            "commitment_state": commitment_state,
            "callback_requested": callback_requested,
        }
    )

    # A change or cancellation for today still needs owner visibility even if
    # the requested time is earlier than the digest's send time. The rule is
    # date-based for these workflows: today or later means the caller may be
    # waiting for confirmation.
    if (
        workflow in {"reservation_change", "reservation_cancel"}
        and reservation_date is not None
        and reservation_date >= reference.date()
    ):
        return AssessmentResult(
            status=OwnerAgentAssessment.Status.NEEDS_ATTENTION,
            reason=OwnerAgentAssessment.Reason.FUTURE_RESERVATION,
            explanation="The caller requested a reservation change or cancellation for today or a future date and may be waiting for confirmation.",
            evaluated_for_date=report_date,
            basis=basis,
        )

    if (
        commitment_state == "future"
        and getattr(call, "display_category", None) == "reservation"
        and workflow in {"reservation_new", ""}
        and booking_link_sent is True
        and (guest_count is None or guest_count <= 8)
    ):
        return AssessmentResult(
            status=OwnerAgentAssessment.Status.CONTEXT_ONLY,
            reason=OwnerAgentAssessment.Reason.BOOKING_LINK_SENT,
            explanation="A booking link was sent for a future reservation; the owner can verify it in Resy.",
            evaluated_for_date=report_date,
            basis=basis,
        )

    if commitment_state == "future":
        reason = (
            OwnerAgentAssessment.Reason.FUTURE_RESERVATION
            if getattr(call, "display_category", None) == "reservation"
            else OwnerAgentAssessment.Reason.FUTURE_COMMITMENT
        )
        return AssessmentResult(
            status=OwnerAgentAssessment.Status.NEEDS_ATTENTION,
            reason=reason,
            explanation="The unhandled call contains a future-dated customer commitment.",
            evaluated_for_date=report_date,
            basis=basis,
        )

    if commitment_state == "past":
        reason = (
            OwnerAgentAssessment.Reason.PAST_RESERVATION
            if getattr(call, "display_category", None) == "reservation"
            else OwnerAgentAssessment.Reason.PAST_COMMITMENT
        )
        return AssessmentResult(
            status=OwnerAgentAssessment.Status.CONTEXT_ONLY,
            reason=reason,
            explanation="The requested date or commitment has already passed.",
            evaluated_for_date=report_date,
            basis=basis,
        )

    if callback_requested:
        return AssessmentResult(
            status=OwnerAgentAssessment.Status.NEEDS_ATTENTION,
            reason=OwnerAgentAssessment.Reason.FUTURE_CALLBACK,
            explanation="The caller requested a callback or follow-up.",
            evaluated_for_date=report_date,
            basis=basis,
        )

    if commitment_state == "unknown" and (
        manager_review_required is True
        or details_shared_with_manager is True
        or customer_waiting_confirmation is True
    ):
        return AssessmentResult(
            status=OwnerAgentAssessment.Status.NEEDS_ATTENTION,
            reason=OwnerAgentAssessment.Reason.FUTURE_COMMITMENT,
            explanation="The unhandled call requires manager review or customer confirmation.",
            evaluated_for_date=report_date,
            basis=basis,
        )

    if meaningful is None:
        return AssessmentResult(
            status=OwnerAgentAssessment.Status.CONTEXT_ONLY,
            reason=OwnerAgentAssessment.Reason.INSUFFICIENT_INFORMATION,
            explanation="The call is unhandled, but HostHub does not have enough structured information to recommend action.",
            evaluated_for_date=report_date,
            basis=basis,
        )

    return AssessmentResult(
        status=OwnerAgentAssessment.Status.CONTEXT_ONLY,
        reason=OwnerAgentAssessment.Reason.INSUFFICIENT_INFORMATION,
        explanation="The unhandled call does not contain an identifiable future commitment.",
        evaluated_for_date=report_date,
        basis=basis,
    )


def save_assessment(call: Any, result: AssessmentResult) -> Any:
    """Persist the current assessment while keeping the Call table unchanged."""

    from ..models import OwnerAgentAssessment

    assessment, _ = OwnerAgentAssessment.objects.update_or_create(
        call=call,
        defaults={
            "status": result.status,
            "reason": result.reason,
            "explanation": result.explanation,
            "evaluated_for_date": result.evaluated_for_date,
            "basis": result.basis,
        },
    )
    return assessment


def assess_and_save_call(call: Any, **kwargs: Any) -> Any:
    result = assess_call(call, **kwargs)
    return save_assessment(call, result)
