"""Digest-scoped read-only context for owner conversations."""

import re
from typing import Any

from django.core.exceptions import ObjectDoesNotExist

from testendpoint.utils.phone import _normalize_phone_number

from ..models import OwnerAgentDigest, OwnerAgentMessage


class OwnerAgentContextError(RuntimeError):
    """Raised when a requested conversation context is unavailable."""


SEARCH_STOPWORDS = {
    "a",
    "about",
    "call",
    "did",
    "for",
    "how",
    "is",
    "me",
    "of",
    "the",
    "that",
    "their",
    "what",
    "was",
}


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _transcript_text(call: Any) -> str:
    full_transcript = str(getattr(call, "full_transcript", "") or "").strip()
    if full_transcript:
        return full_transcript

    rows = getattr(call, "transcripts", None)
    if not isinstance(rows, list):
        return ""

    parts = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        speaker = row.get("user") or row.get("role") or "unknown"
        text = str(row.get("text") or "").strip()
        if text:
            parts.append(f"{speaker}: {text}")
    return "\n".join(parts)


def _item_call_context(item: Any) -> dict[str, Any]:
    call = item.call
    return {
        "call_id": call.id,
        "bland_call_id": call.bland_call_id,
        "user_name": call.user_name or "",
        "phone_number": _normalize_phone_number(call.from_number) or "",
        "display_category": call.display_category,
        "call_created_at": _iso(call.created_at),
        "summary": item.summary or call.summary or "",
        "digest_section": item.section,
        "assessment_reason": item.reason,
        "assessment_status": (
            (item.source_snapshot or {}).get("status")
            or ("needs_attention" if item.section == "attention" else "context_only")
        ),
        "assessment_explanation": (item.source_snapshot or {}).get("explanation", ""),
        "host_status": call.host_status,
        "handled_at": _iso(call.handled_at),
        "transcript_available": bool(_transcript_text(call)),
    }


def _message_context(message: Any) -> dict[str, Any]:
    return {
        "message_id": message.id,
        "direction": message.direction,
        "body": message.body,
        "created_at": _iso(message.created_at),
    }


def _ensure_sent_digest(digest: Any) -> None:
    if digest is None or digest.status != OwnerAgentDigest.Status.SENT:
        raise OwnerAgentContextError("Conversation context requires a sent owner digest.")


def build_digest_context(
    digest: OwnerAgentDigest,
    *,
    message_limit: int = 12,
) -> dict[str, Any]:
    """Return the latest digest and its calls without loading transcripts."""

    _ensure_sent_digest(digest)
    items = list(
        digest.items.select_related("call").order_by("section", "position", "id")
    )
    messages = list(
        digest.messages.order_by("-created_at", "-id")[:message_limit]
    )
    messages.reverse()

    return {
        "scope": "owner_daily_digest",
        "account_id": digest.account_id,
        "digest_id": digest.id,
        "report_date": digest.local_date.isoformat(),
        "digest_message": digest.message_body,
        "counts": {
            "total_calls": digest.total_calls,
            "handled_calls": digest.handled_calls,
            "unhandled_calls": digest.unhandled_calls,
            "attention_calls": digest.attention_calls,
            "context_calls": digest.context_calls,
        },
        "calls": [_item_call_context(item) for item in items],
        "conversation_messages": [_message_context(message) for message in messages],
        "transcripts_loaded": False,
    }


def build_message_context(message: OwnerAgentMessage, *, message_limit: int = 12) -> dict[str, Any]:
    """Build context anchored to the digest associated with an owner reply."""

    if not message.digest_id:
        raise OwnerAgentContextError("Owner message is not attached to a digest.")
    try:
        digest = message.digest
    except ObjectDoesNotExist as exc:
        raise OwnerAgentContextError("Owner message digest could not be loaded.") from exc
    return build_digest_context(digest, message_limit=message_limit)


def context_call_matches(call_context: dict[str, Any], query: str) -> bool:
    """Match an owner query against only calls in the active digest."""

    normalized_query = " ".join(str(query or "").lower().split())
    if not normalized_query:
        return False

    searchable = " ".join(
        str(call_context.get(key) or "").lower()
        for key in (
            "call_id",
            "bland_call_id",
            "user_name",
            "phone_number",
            "display_category",
            "summary",
            "assessment_reason",
        )
    )
    if normalized_query in searchable:
        return True

    query_digits = re.sub(r"\D", "", normalized_query)
    phone_digits = re.sub(r"\D", "", str(call_context.get("phone_number") or ""))
    if query_digits and len(query_digits) >= 4 and query_digits in phone_digits:
        return True

    terms = [
        term
        for term in re.findall(r"[a-z0-9]+", normalized_query)
        if term not in SEARCH_STOPWORDS and len(term) > 1
    ]
    return bool(terms) and any(term in searchable for term in terms)


def search_digest_calls(
    digest_context: dict[str, Any],
    query: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search the active digest's call cards without searching older calls."""

    matches = [
        call
        for call in digest_context.get("calls", [])
        if context_call_matches(call, query)
    ]
    return matches[:limit]


def get_call_transcript(
    digest: OwnerAgentDigest,
    call_id: int,
) -> dict[str, Any]:
    """Load a transcript only when the call belongs to the active digest."""

    _ensure_sent_digest(digest)
    item = (
        digest.items.select_related("call")
        .filter(call_id=call_id)
        .first()
    )
    if item is None:
        raise OwnerAgentContextError(
            "That call is not part of the active owner digest."
        )

    call = item.call
    return {
        "call_id": call.id,
        "bland_call_id": call.bland_call_id,
        "user_name": call.user_name or "",
        "phone_number": _normalize_phone_number(call.from_number) or "",
        "display_category": call.display_category,
        "summary": item.summary or call.summary or "",
        "transcript": _transcript_text(call),
    }
