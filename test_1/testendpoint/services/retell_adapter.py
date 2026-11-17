"""Translate Retell post-call payloads into the existing Bland call shape.

This module deliberately does not write to the database. The Retell webhook
uses the existing ``upsert_call_from_bland_json`` path after normalization so
the current HostHub behavior remains unchanged.
"""

from datetime import datetime, timezone as datetime_timezone
import hashlib
import hmac
import re
import time

from dateutil import parser as dateparser


CATEGORY_ALIASES = {
    "reservation": "reservation",
    "reservations": "reservation",
    "carryout": "carryout",
    "carry_out": "carryout",
    "carry out": "carryout",
    "private_event": "private_events",
    "private_events": "private_events",
    "private event": "private_events",
    "private events": "private_events",
    "leave_message": "leave_message",
    "leave message": "leave_message",
    "message": "leave_message",
    "other": "other",
}


def verify_retell_signature(raw_body: bytes, signature: str | None, api_key: str) -> bool:
    """Verify Retell's ``X-Retell-Signature`` without re-serializing JSON."""
    if not raw_body or not signature or not api_key:
        return False

    match = re.fullmatch(r"v=(\d+),d=([0-9a-fA-F]+)", signature.strip())
    if not match:
        return False

    timestamp_text, provided_digest = match.groups()
    try:
        timestamp_ms = int(timestamp_text)
    except ValueError:
        return False

    # Retell signatures are short-lived and use milliseconds.
    if abs(int(time.time() * 1000) - timestamp_ms) > 5 * 60 * 1000:
        return False

    expected_digest = hmac.new(
        api_key.encode("utf-8"),
        raw_body + timestamp_text.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_digest, provided_digest)


def _timestamp_to_iso(value):
    if value in (None, ""):
        return None

    if isinstance(value, (int, float)):
        # Retell timestamps are milliseconds since Unix epoch.
        return datetime.fromtimestamp(
            float(value) / 1000,
            tz=datetime_timezone.utc,
        ).isoformat()

    try:
        parsed = dateparser.parse(str(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed.isoformat() if parsed else None


def _timestamp_to_datetime(value):
    iso_value = _timestamp_to_iso(value)
    if not iso_value:
        return None
    try:
        return dateparser.parse(iso_value)
    except (TypeError, ValueError, OverflowError):
        return None


def _duration_seconds(call: dict) -> int:
    started = _timestamp_to_datetime(call.get("start_timestamp"))
    ended = _timestamp_to_datetime(call.get("end_timestamp"))
    if started and ended:
        return max(0, int((ended - started).total_seconds()))

    for key in ("duration_seconds", "duration"):
        value = call.get(key)
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            continue
    return 0


def _analysis_data(call: dict) -> dict:
    analysis = call.get("call_analysis") or {}
    if not isinstance(analysis, dict):
        return {}
    custom = analysis.get("custom_analysis_data") or {}
    return custom if isinstance(custom, dict) else {}


def _extracted_values(call: dict, args: dict) -> dict:
    values = _analysis_data(call).copy()
    if isinstance(args, dict):
        values.update(args)
    return values


def _normalize_category(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("value") or value.get("name") or value.get("label")
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_")
    return CATEGORY_ALIASES.get(normalized)


def _transcript_turns(call: dict) -> list:
    raw_turns = call.get("transcript_object") or []
    if not isinstance(raw_turns, list):
        return []

    turns = []
    for index, turn in enumerate(raw_turns):
        if not isinstance(turn, dict):
            continue
        text = turn.get("content") or turn.get("text") or ""
        if not isinstance(text, str) or not text.strip():
            continue

        role = str(turn.get("role") or turn.get("speaker") or "").lower()
        user = "agent" if role in {"agent", "assistant"} else "user"
        created_at = _timestamp_to_iso(
            turn.get("start_timestamp") or turn.get("timestamp")
        )
        turns.append({
            "id": turn.get("id") or index,
            "text": text.strip(),
            "user": user,
            "created_at": created_at,
        })
    return turns


def normalize_retell_to_bland(payload: dict) -> dict:
    """Convert a Retell post-call body into Bland-compatible call data."""
    if not isinstance(payload, dict):
        raise ValueError("Retell payload must be a JSON object")

    call = payload.get("call")
    if not isinstance(call, dict):
        # Also support a direct call object for easier replay/testing.
        call = payload

    retell_call_id = call.get("call_id")
    if not retell_call_id:
        raise ValueError("Retell payload is missing call.call_id")

    args = payload.get("args") or {}
    extracted = _extracted_values(call, args)
    collected_variables = call.get("collected_dynamic_variables") or {}
    if not isinstance(collected_variables, dict):
        collected_variables = {}
    analysis = call.get("call_analysis") or {}
    if not isinstance(analysis, dict):
        analysis = {}

    category = _normalize_category(
        extracted.get("hosthub_category")
        or extracted.get("category")
        or extracted.get("call_category")
    )
    user_name = (
        extracted.get("user_name")
        or collected_variables.get("user_name")
        or extracted.get("caller_name")
        or extracted.get("name")
        or (call.get("retell_llm_dynamic_variables") or {}).get("user_name")
    )
    if not user_name:
        user_name = (
            collected_variables.get("caller_name")
            or collected_variables.get("name")
        )

    started_at = _timestamp_to_iso(call.get("start_timestamp"))
    ended_at = _timestamp_to_iso(call.get("end_timestamp"))
    status = call.get("call_status") or call.get("status") or "ended"
    completed = bool(ended_at or status in {"ended", "completed"})
    summary = (
        analysis.get("call_summary")
        or extracted.get("call_summary")
        or extracted.get("summary")
        or ""
    )

    variables = {}
    dynamic_variables = call.get("retell_llm_dynamic_variables") or {}
    if isinstance(dynamic_variables, dict):
        variables.update(dynamic_variables)
    # These are the values extracted during the Retell conversation. They are
    # distinct from the inbound variables supplied before the call and must
    # be retained for HostHub's existing dashboard and assessment logic.
    variables.update(collected_variables)
    variables.update(extracted)
    if user_name and not variables.get("user_name"):
        variables["user_name"] = user_name

    metadata = {
        "provider": "retell",
        "retell_call_id": retell_call_id,
        "retell_event": payload.get("event"),
        "retell_metadata": call.get("metadata") or {},
        "call_analysis": analysis,
    }

    return {
        # Keep the existing database schema and Bland upsert path unchanged.
        "call_id": f"retell_{retell_call_id}",
        "from": call.get("from_number"),
        "to": call.get("to_number"),
        "created_at": started_at,
        "started_at": started_at,
        "ended_at": ended_at,
        "corrected_duration": _duration_seconds(call),
        "queue_status": "complete" if completed else status,
        "status": status,
        "completed": completed,
        "summary": summary,
        "concatenated_transcript": call.get("transcript") or "",
        "transcripts": _transcript_turns(call),
        "pathway_tags": [category] if category else [],
        "variables": variables,
        "metadata": metadata,
    }
