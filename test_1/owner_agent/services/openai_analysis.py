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


PROMPT_VERSION = "owner-call-analysis-v1"
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
    reservation_date: date | None
    reservation_time: time | None
    guest_count: int | None
    future_commitment: bool
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
        "reservation_date": {"type": "string"},
        "reservation_time": {"type": "string"},
        "guest_count": {"type": "integer"},
        "future_commitment": {"type": "boolean"},
        "customer_request": {"type": "string"},
        "normalized_summary": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": [
        "meaningful_conversation",
        "intent",
        "reservation_date",
        "reservation_time",
        "guest_count",
        "future_commitment",
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
- reservation_date must be YYYY-MM-DD or an empty string.
- reservation_time must be 24-hour HH:MM or an empty string.
- guest_count must be a positive integer or 0 when unknown.
- future_commitment is true only when the call contains a future reservation,
  future private-event request, explicit callback, or other future follow-up.
- Never claim a reservation was completed unless that fact is explicitly present
  in the supplied HostHub data.
- normalized_summary must be concise, factual, and suitable for an owner digest.
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
        intent=str(raw_output.get("intent") or "unknown").strip().lower(),
        reservation_date=_parse_date(raw_output.get("reservation_date")),
        reservation_time=_parse_time(raw_output.get("reservation_time")),
        guest_count=_parse_guest_count(raw_output.get("guest_count")),
        future_commitment=bool(raw_output.get("future_commitment")),
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
            "reservation_date": result.reservation_date,
            "reservation_time": result.reservation_time,
            "guest_count": result.guest_count,
            "future_commitment": result.future_commitment,
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
