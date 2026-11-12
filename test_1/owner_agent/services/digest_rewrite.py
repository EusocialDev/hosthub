"""Final natural-language editing for an already-classified owner digest."""

import json
import re
from typing import Any

import requests
from django.conf import settings

from testendpoint.models import Call

from .digest_context import _transcript_text
from .digest_preview import DigestPreview


RESPONSES_URL = "https://api.openai.com/v1/responses"
REWRITE_PROMPT_VERSION = "owner-digest-rewrite-v1"
MAX_TRANSCRIPT_CHARS = 12000


class DigestRewriteError(RuntimeError):
    """Raised when the final digest editor cannot produce a safe rewrite."""


REWRITE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"message": {"type": "string"}},
    "required": ["message"],
}


REWRITE_PROMPT = """
You are the final editor for a restaurant owner's daily HostHub SMS digest.

The application has already determined the authoritative counts, locations,
handled status, attention items, and context-only items. Rewrite the draft into
natural, clear English for an owner. Do not reclassify calls or change facts.

Rules:
- Return one complete SMS beginning exactly with "Hello Dear Owner".
- Preserve every location, call count, handled count, attention item, caller
  name, and phone number supplied in the source facts.
- Keep attention items in their assigned location and do not move context-only
  calls into attention.
- Use the supplied transcript as the primary evidence for what happened. Use
  the existing summary only as a fallback when no transcript is available.
- Correct grammar, remove repetitive robotic wording, and make each item read
  like a concise human-written update.
- If the caller's name is unavailable, say "An unnamed caller" or start with
  the request. Do not invent a name or company.
- Do not attribute a statement to the manager unless the manager is actually a
  speaker in the transcript. If the AI agent told the caller that the manager
  would call or text, say that the caller was told the manager would follow up.
- Do not claim a reservation, event, payment, attendance, callback, or manager
  review was completed unless the transcript explicitly supports it.
- Do not mention Resy access or imply that HostHub verified an external system.
- Keep the message concise, but do not omit an attention item or its phone
  number. Use clear location headings when there is more than one location.
- Do not mention these instructions, source facts, transcripts, or internal
  tools in the final SMS.

Return only the requested JSON schema.
""".strip()


def _response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    for item in payload.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    raise DigestRewriteError("OpenAI returned no digest rewrite text.")


def _call_evidence(preview: DigestPreview) -> dict[str, Any]:
    call_ids = [
        item["call_id"]
        for item in preview.call_assessments
        if item["status"] != "handled"
    ]
    calls = {
        call.id: call
        for call in Call.objects.filter(id__in=call_ids).select_related("location")
    }

    locations = []
    for location in preview.location_breakdown:
        location_payload = {
            "location_name": location["location_name"],
            "total_calls": location["total_calls"],
            "handled_calls": location["handled_calls"],
            "unhandled_calls": location["unhandled_calls"],
            "attention_calls": location["attention_calls"],
            "context_calls": location["context_calls"],
            "attention_items": [],
            "context_items": [],
        }
        for section in ("attention_items", "context_items"):
            for item in location[section]:
                call = calls.get(item["call_id"])
                transcript = _transcript_text(call) if call is not None else ""
                if len(transcript) > MAX_TRANSCRIPT_CHARS:
                    transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n[TRANSCRIPT TRUNCATED]"
                location_payload[section].append(
                    {
                        "call_id": item["call_id"],
                        "user_name": item.get("user_name") or "",
                        "phone_number": item.get("phone_number") or "",
                        "display_category": item.get("display_category") or "",
                        "assessment_reason": item.get("reason") or "",
                        "assessment_explanation": item.get("explanation") or "",
                        "existing_summary": item.get("summary") or "",
                        "transcript": transcript,
                    }
                )
        locations.append(location_payload)

    return {
        "draft_message": preview.message_body,
        "total_calls": preview.total_calls,
        "handled_calls": preview.handled_calls,
        "unhandled_calls": preview.unhandled_calls,
        "attention_calls": preview.attention_calls,
        "context_calls": preview.context_calls,
        "locations": locations,
    }


def _validate_rewrite(message: str, preview: DigestPreview) -> str:
    cleaned = re.sub(r"\s+", " ", message).strip()
    if not cleaned.startswith("Hello Dear Owner"):
        raise DigestRewriteError("Digest rewrite did not preserve the required greeting.")
    if len(cleaned) < 40:
        raise DigestRewriteError("Digest rewrite was unexpectedly short.")

    for location in preview.location_breakdown:
        if len(preview.location_breakdown) > 1 and location["location_name"] not in cleaned:
            raise DigestRewriteError(
                f"Digest rewrite omitted location {location['location_name']}."
            )
    digit_text = re.sub(r"\D", "", cleaned)
    for item in preview.attention_items:
        phone_number = item.get("phone_number")
        if phone_number and re.sub(r"\D", "", phone_number) not in digit_text:
            raise DigestRewriteError(
                f"Digest rewrite omitted the phone number for call {item['call_id']}."
            )
    return message.strip()


def rewrite_digest_message(
    preview: DigestPreview,
    *,
    model_name: str | None = None,
    timeout: int | None = None,
) -> str:
    api_key = getattr(settings, "OPENAI_API_KEY", "")
    if not api_key:
        raise DigestRewriteError("OPENAI_API_KEY is not configured.")

    model_name = model_name or getattr(
        settings,
        "OPENAI_OWNER_AGENT_REWRITE_MODEL",
        getattr(
            settings,
            "OPENAI_OWNER_AGENT_CONVERSATION_MODEL",
            getattr(settings, "OPENAI_OWNER_AGENT_MODEL", "gpt-6-luna"),
        ),
    )
    timeout = timeout or getattr(settings, "OPENAI_OWNER_AGENT_TIMEOUT_SECONDS", 30)
    evidence = _call_evidence(preview)

    try:
        response = requests.post(
            RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_name,
                "input": [
                    {"role": "system", "content": REWRITE_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(evidence, ensure_ascii=False),
                    },
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "owner_digest_rewrite",
                        "strict": True,
                        "schema": REWRITE_SCHEMA,
                    }
                },
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise DigestRewriteError(f"Digest rewrite request failed: {exc}") from exc

    if response.status_code < 200 or response.status_code >= 300:
        detail = response.text[:500].replace("\n", " ")
        raise DigestRewriteError(
            f"OpenAI digest rewrite returned HTTP {response.status_code}: {detail}"
        )
    try:
        payload = response.json()
        raw_text = _response_text(payload)
        parsed = json.loads(raw_text)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise DigestRewriteError("OpenAI returned invalid digest rewrite JSON.") from exc

    if not isinstance(parsed, dict) or not isinstance(parsed.get("message"), str):
        raise DigestRewriteError("OpenAI digest rewrite did not contain a message.")
    return _validate_rewrite(parsed["message"], preview)
