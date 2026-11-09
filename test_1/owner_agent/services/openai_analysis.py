"""OpenAI-backed call analysis for the owner agent.

The service only extracts and normalizes call facts. It does not decide
whether HostHub marked a call handled and it does not perform any action.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
import json
import re
from typing import Any

import requests
from dateutil import parser as date_parser
from django.conf import settings
from django.utils import timezone as django_timezone

from testendpoint.models import Call

from ..models import OwnerAgentAnalysis


PROMPT_VERSION = "owner-call-analysis-v2"
RESPONSES_URL = "https://api.openai.com/v1/responses"
SENSITIVE_VARIABLE_KEYS = {
    "call_token",
    "phone_number",
    "short_from",
    "short_to",
    "from",
    "to",
    "host_email",
    "manager_email",
    "email",
}


class OpenAIAnalysisError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMAnalysisResult:
    meaningful_conversation: bool
    intent: str
    workflow: str
    reservation_date: date | None
    reservation_time: time | None
    guest_count: int | None
    future_commitment: bool
    booking_link_sent: bool
    kitchen_share_completed: bool
    details_shared_with_manager: bool
    manager_review_required: bool
    customer_waiting_confirmation: bool
    customer_request: str
    normalized_summary: str
    confidence: float
    raw_output: dict[str, Any]
    input_snapshot: dict[str, Any]
    model_name: str
    prompt_version: str = PROMPT_VERSION

    def as_analysis_object(self) -> Any:
        """Return a lightweight object accepted by the rule engine."""

        return self


ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "meaningful_conversation": {"type": "boolean"},
        "intent": {"type": "string"},
        "workflow": {"type": "string"},
        "reservation_date": {"type": "string"},
        "reservation_time": {"type": "string"},
        "guest_count": {"type": "integer"},
        "future_commitment": {"type": "boolean"},
        "booking_link_sent": {"type": "boolean"},
        "kitchen_share_completed": {"type": "boolean"},
        "details_shared_with_manager": {"type": "boolean"},
        "manager_review_required": {"type": "boolean"},
        "customer_waiting_confirmation": {"type": "boolean"},
        "customer_request": {"type": "string"},
        "normalized_summary": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": [
        "meaningful_conversation",
        "intent",
        "workflow",
        "reservation_date",
        "reservation_time",
        "guest_count",
        "future_commitment",
        "booking_link_sent",
        "kitchen_share_completed",
        "details_shared_with_manager",
        "manager_review_required",
        "customer_waiting_confirmation",
        "customer_request",
        "normalized_summary",
        "confidence",
    ],
}


SYSTEM_PROMPT = """
You analyze one HostHub restaurant phone call.

Return only the requested JSON schema. Extract facts from the supplied HostHub
fields and transcript. Do not use external systems and do not assume access to
Resy. Do not decide whether the call was handled in HostHub; that is controlled
by HostHub's own status field.

Rules:
- meaningful_conversation is false when the caller provided no meaningful
  request or only silence/empty speech.
- workflow must be one of: reservation_new, reservation_change,
  reservation_cancel, private_event_new, private_event_existing, carryout,
  leave_message, general_question, silent, other.
- Use reservation_new for a new table reservation request, reservation_change
  for moving or editing an existing reservation, and reservation_cancel for a
  cancellation request. Use private_event_new for a new party/event inquiry
  and private_event_existing when the caller is discussing an event already
  arranged.
- reservation_date must be YYYY-MM-DD or an empty string.
- reservation_time must be 24-hour HH:MM or an empty string.
- guest_count must be a positive integer or 0 when unknown.
- future_commitment is true only when the call contains a future reservation,
  future private-event request, explicit callback, or other future follow-up.
- booking_link_sent is true only when the agent explicitly says a reservation
  booking link was sent to the caller.
- kitchen_share_completed is true only when the conversation reaches the point
  where the agent explicitly says the carryout order was shared with the
  kitchen/team or that the kitchen has started preparing it. Saying a link will
  be sent is not enough.
- details_shared_with_manager is true only when the agent explicitly says the
  event/request details were shared or forwarded to the manager, host stand, or
  team.
- manager_review_required is true for reservations larger than 8 guests, new
  private events requiring manager pricing/review, or any request explicitly
  sent to a manager for confirmation.
- For a new reservation of 8 or fewer guests, a booking link normally means the
  caller was given the next step; preserve that fact in the summary. For a new
  reservation larger than 8 guests, no booking link should be inferred and the
  caller should be treated as waiting for manager confirmation when the
  transcript says the request was sent for review.
- customer_waiting_confirmation is true when the customer is waiting for a
  reservation, change, cancellation, private-event, or manager confirmation.
- For a carryout call, kitchen_share_completed is the decisive checkpoint:
  true only when the transcript reaches an explicit kitchen/team handoff or
  says the kitchen started preparing the order. An order link, payment link,
  order total, or promise to share later is not enough.
- Never claim a reservation was completed unless that fact is explicitly present
  in the supplied HostHub data.
- normalized_summary must be one concise, factual owner-digest sentence, ideally
  under 220 characters. Include the requested date/time, guest count when
  known, and the next expected step when it is explicit. For an unhandled
  reservation change/cancellation, say confirmation was not stated when that
  is the supported fact. For a private event, say details were shared with the
  manager only when that is explicit. Do not include a phone number; the
  application adds it separately.
- Do not say a manager will call or text unless the transcript explicitly says
  that. Do not invent a completion, confirmation, payment, attendance, or
  external-system result.
- confidence must be between 0 and 1.
""".strip()


def _redact_value(value: Any, key: str | None = None) -> Any:
    if key and key.lower() in SENSITIVE_VARIABLE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", value)
        value = re.sub(r"\+?\d[\d().\- ]{8,}\d", "[PHONE]", value)
    return value


def _transcript_text(call: Call) -> str:
    full_transcript = (call.full_transcript or "").strip()
    if full_transcript:
        return full_transcript[:16000]

    rows = call.transcripts if isinstance(call.transcripts, list) else []
    parts = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        role = row.get("user") or row.get("role") or "unknown"
        text = str(row.get("text") or "").strip()
        if text:
            parts.append(f"{role}: {text}")
    return "\n".join(parts)[:16000]


def build_analysis_input(call: Call, evaluation_time: datetime) -> dict[str, Any]:
    return {
        "call_id": call.bland_call_id,
        "call_created_at": call.created_at.isoformat() if call.created_at else "",
        "evaluation_time": evaluation_time.isoformat(),
        "caller_name": call.user_name or "",
        "display_category": call.display_category,
        "disposition": call.disposition or "",
        "existing_summary": call.summary or "",
        "variables": _redact_value(call.variables or {}),
        "transcript": _transcript_text(call),
    }


def _extract_response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    raise OpenAIAnalysisError("OpenAI returned no structured output text.")


def _parse_json_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise OpenAIAnalysisError("OpenAI returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise OpenAIAnalysisError("OpenAI returned a non-object analysis.")
    return parsed


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date_parser.parse(text, fuzzy=True).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_time(value: Any) -> time | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date_parser.parse(text, default=datetime(2000, 1, 1)).time().replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_guest_count(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _bounded_text(value: Any, *, default: str, max_length: int) -> str:
    text = str(value or default).strip()
    return text[:max_length]


def normalize_analysis_output(
    raw_output: dict[str, Any],
    *,
    input_snapshot: dict[str, Any],
    model_name: str,
) -> LLMAnalysisResult:
    confidence = float(raw_output.get("confidence") or 0)
    confidence = min(1.0, max(0.0, confidence))
    return LLMAnalysisResult(
        meaningful_conversation=bool(raw_output.get("meaningful_conversation")),
        intent=_bounded_text(
            raw_output.get("intent"),
            default="unknown",
            max_length=80,
        ).lower(),
        workflow=_bounded_text(
            raw_output.get("workflow"),
            default="other",
            max_length=80,
        ).lower(),
        reservation_date=_parse_date(raw_output.get("reservation_date")),
        reservation_time=_parse_time(raw_output.get("reservation_time")),
        guest_count=_parse_guest_count(raw_output.get("guest_count")),
        future_commitment=bool(raw_output.get("future_commitment")),
        booking_link_sent=bool(raw_output.get("booking_link_sent")),
        kitchen_share_completed=bool(raw_output.get("kitchen_share_completed")),
        details_shared_with_manager=bool(raw_output.get("details_shared_with_manager")),
        manager_review_required=bool(raw_output.get("manager_review_required")),
        customer_waiting_confirmation=bool(raw_output.get("customer_waiting_confirmation")),
        customer_request=str(raw_output.get("customer_request") or "").strip(),
        normalized_summary=str(raw_output.get("normalized_summary") or "").strip(),
        confidence=confidence,
        raw_output=raw_output,
        input_snapshot=input_snapshot,
        model_name=model_name,
    )


def analyze_call(
    call: Call,
    *,
    evaluation_time: datetime,
    model_name: str | None = None,
    timeout: int | None = None,
) -> LLMAnalysisResult:
    api_key = getattr(settings, "OPENAI_API_KEY", "")
    if not api_key:
        raise OpenAIAnalysisError("OPENAI_API_KEY is not configured.")

    model_name = model_name or getattr(settings, "OPENAI_OWNER_AGENT_MODEL", "gpt-6-luna")
    timeout = timeout or getattr(settings, "OPENAI_OWNER_AGENT_TIMEOUT_SECONDS", 30)
    input_snapshot = build_analysis_input(call, evaluation_time)

    response = requests.post(
        RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model_name,
            "input": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(input_snapshot, ensure_ascii=False),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "owner_call_analysis",
                    "strict": True,
                    "schema": ANALYSIS_SCHEMA,
                }
            },
        },
        timeout=timeout,
    )

    if response.status_code < 200 or response.status_code >= 300:
        detail = response.text[:500].replace("\n", " ")
        raise OpenAIAnalysisError(
            f"OpenAI API returned HTTP {response.status_code}: {detail}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise OpenAIAnalysisError("OpenAI returned a non-JSON response.") from exc

    raw_output = _parse_json_text(_extract_response_text(payload))
    return normalize_analysis_output(
        raw_output,
        input_snapshot=input_snapshot,
        model_name=model_name,
    )


def save_analysis(call: Call, result: LLMAnalysisResult) -> OwnerAgentAnalysis:
    analysis, _ = OwnerAgentAnalysis.objects.update_or_create(
        call=call,
        defaults={
            "status": OwnerAgentAnalysis.Status.COMPLETE,
            "meaningful_conversation": result.meaningful_conversation,
            "intent": result.intent,
            "workflow": result.workflow,
            "reservation_date": result.reservation_date,
            "reservation_time": result.reservation_time,
            "guest_count": result.guest_count,
            "future_commitment": result.future_commitment,
            "booking_link_sent": result.booking_link_sent,
            "kitchen_share_completed": result.kitchen_share_completed,
            "details_shared_with_manager": result.details_shared_with_manager,
            "manager_review_required": result.manager_review_required,
            "customer_waiting_confirmation": result.customer_waiting_confirmation,
            "customer_request": result.customer_request,
            "normalized_summary": result.normalized_summary,
            "confidence": result.confidence,
            "llm_output": result.raw_output,
            "input_snapshot": result.input_snapshot,
            "model_name": result.model_name,
            "prompt_version": result.prompt_version,
            "error_message": "",
            "analyzed_at": django_timezone.now(),
        },
    )
    return analysis


def analyze_and_save_call(call: Call, **kwargs: Any) -> OwnerAgentAnalysis:
    try:
        result = analyze_call(call, **kwargs)
    except Exception as exc:
        analysis, _ = OwnerAgentAnalysis.objects.update_or_create(
            call=call,
            defaults={
                "status": OwnerAgentAnalysis.Status.FAILED,
                "model_name": kwargs.get("model_name")
                or getattr(settings, "OPENAI_OWNER_AGENT_MODEL", "gpt-6-luna"),
                "prompt_version": PROMPT_VERSION,
                "error_message": str(exc),
                "analyzed_at": django_timezone.now(),
            },
        )
        return analysis
    return save_analysis(call, result)
