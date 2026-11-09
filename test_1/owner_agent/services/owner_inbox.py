"""Ingest owner replies and anchor them to the latest sent digest."""

from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone
import hashlib
import hmac
from typing import Any

from django.utils import timezone as django_timezone
from django.utils.dateparse import parse_datetime

from testendpoint.utils.phone import _normalize_phone_number

from ..models import OwnerAgentDigest, OwnerAgentMessage, OwnerAgentSettings


class OwnerAgentInboundMessageError(RuntimeError):
    """Raised when an owner reply cannot be safely associated with an account."""


@dataclass(frozen=True)
class OwnerInboundResult:
    message: OwnerAgentMessage
    duplicate: bool


def _first_value(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _nested_value(payload: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        current: Any = payload
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if current not in (None, "", [], {}):
            return current
    return None


def _extract_fields(payload: dict[str, Any]) -> dict[str, str]:
    message_value = _first_value(payload, ("message", "body", "text", "content"))
    if isinstance(message_value, dict):
        message_value = _first_value(message_value, ("body", "text", "content"))

    phone = _first_value(
        payload,
        ("phone", "from", "from_number", "sender_phone", "contact_phone"),
    )
    if isinstance(phone, dict):
        phone = _first_value(phone, ("phone", "number"))
    phone = phone or _nested_value(
        payload,
        ("contact", "phone"),
        ("contact", "phoneNumber"),
        ("sender", "phone"),
    )

    contact_id = _first_value(
        payload,
        ("contact_id", "contactId", "ghl_contact_id"),
    ) or _nested_value(payload, ("contact", "id"))
    message_id = _first_value(
        payload,
        ("message_id", "messageId", "ghl_message_id", "id"),
    )
    received_at = _first_value(
        payload,
        ("received_at", "receivedAt", "created_at", "createdAt"),
    )
    location_id = _first_value(
        payload,
        ("location_id", "locationId", "ghl_location_id"),
    )
    return {
        "body": str(message_value or "").strip(),
        "phone": str(phone or "").strip(),
        "contact_id": str(contact_id or "").strip(),
        "message_id": str(message_id or "").strip(),
        "received_at": str(received_at or "").strip(),
        "location_id": str(location_id or "").strip(),
    }


def _matching_settings(fields: dict[str, str]) -> OwnerAgentSettings | None:
    phone = _normalize_phone_number(fields["phone"]) if fields["phone"] else None
    candidates = OwnerAgentSettings.objects.filter(
        enabled=True,
        account__is_active=True,
    ).select_related("account")

    if fields["contact_id"]:
        candidates = candidates.filter(ghl_contact_id=fields["contact_id"])
    if fields["location_id"]:
        candidates = candidates.filter(ghl_location_id=fields["location_id"])

    for candidate in candidates:
        candidate_phone = _normalize_phone_number(candidate.owner_phone_number)
        if phone and candidate_phone == phone:
            return candidate
        if not phone and fields["contact_id"] and candidate.ghl_contact_id == fields["contact_id"]:
            return candidate
    return None


def _received_at(value: str) -> datetime:
    if value:
        parsed = parse_datetime(value)
        if parsed is not None:
            if django_timezone.is_naive(parsed):
                return django_timezone.make_aware(parsed, timezone=datetime_timezone.utc)
            return parsed
    return django_timezone.now()


def _stable_message_id(fields: dict[str, str]) -> str:
    if fields["message_id"]:
        return fields["message_id"]
    fingerprint = "\x1f".join(
        (
            fields["contact_id"],
            _normalize_phone_number(fields["phone"]) or fields["phone"],
            fields["body"],
            fields["received_at"],
        )
    )
    return f"inbound-{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()}"


def ingest_owner_reply(payload: dict[str, Any]) -> OwnerInboundResult:
    if not isinstance(payload, dict):
        raise OwnerAgentInboundMessageError("Webhook payload must be a JSON object.")

    fields = _extract_fields(payload)
    if not fields["body"]:
        raise OwnerAgentInboundMessageError("Owner message body is missing.")
    if not fields["phone"] and not fields["contact_id"]:
        raise OwnerAgentInboundMessageError("Owner phone or GHL contact ID is missing.")

    owner_settings = _matching_settings(fields)
    if owner_settings is None:
        raise OwnerAgentInboundMessageError("Owner reply could not be matched to an enabled account.")

    fields["message_id"] = _stable_message_id(fields)
    existing = OwnerAgentMessage.objects.filter(
        ghl_message_id=fields["message_id"],
    ).first()
    if existing is not None:
        return OwnerInboundResult(message=existing, duplicate=True)

    digest = OwnerAgentDigest.objects.filter(
        account=owner_settings.account,
        status=OwnerAgentDigest.Status.SENT,
    ).order_by("-local_date", "-sent_at", "-id").first()
    if digest is None:
        raise OwnerAgentInboundMessageError("No sent owner digest is available for this account.")

    normalized_phone = _normalize_phone_number(fields["phone"]) or owner_settings.owner_phone_number
    message = OwnerAgentMessage.objects.create(
        account=owner_settings.account,
        digest=digest,
        direction=OwnerAgentMessage.Direction.INBOUND,
        channel="sms",
        status=OwnerAgentMessage.Status.RECEIVED,
        owner_phone_number=normalized_phone,
        ghl_contact_id=fields["contact_id"] or owner_settings.ghl_contact_id,
        ghl_message_id=fields["message_id"],
        body=fields["body"],
        provider_payload=payload,
        received_at=_received_at(fields["received_at"]),
    )
    return OwnerInboundResult(message=message, duplicate=False)


def valid_inbound_token(received_token: str, expected_token: str) -> bool:
    return bool(expected_token) and hmac.compare_digest(received_token, expected_token)
