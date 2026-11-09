"""GoHighLevel delivery adapter for owner-agent SMS messages."""

from dataclasses import dataclass
from datetime import date
from typing import Any

import requests
from django.conf import settings

from testendpoint.utils.phone import _normalize_phone_number


class GHLOwnerSMSDeliveryError(RuntimeError):
    """Raised when the owner SMS could not be accepted by GoHighLevel."""


@dataclass(frozen=True)
class GHLOwnerSMSResult:
    message_id: str
    response_payload: dict[str, Any]


def _response_payload(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {"status_code": response.status_code, "body": response.text[:500]}
    return payload if isinstance(payload, dict) else {"data": payload}


def _message_id(payload: dict[str, Any]) -> str:
    for key in ("message_id", "messageId", "id"):
        value = payload.get(key)
        if value:
            return str(value)

    for container_key in ("message", "data", "result"):
        container = payload.get(container_key)
        if isinstance(container, dict):
            nested = _message_id(container)
            if nested:
                return nested
    return ""


def build_owner_sms_payload(
    *,
    account_id: int,
    digest_id: int,
    report_date: date,
    owner_phone_number: str,
    message_body: str,
    ghl_contact_id: str = "",
    ghl_location_id: str = "",
) -> dict[str, Any]:
    phone_number = _normalize_phone_number(owner_phone_number)
    if not phone_number:
        raise GHLOwnerSMSDeliveryError("Owner phone number is missing or invalid.")

    return {
        "source": "hosthub_owner_agent",
        "account_id": account_id,
        "digest_id": digest_id,
        "report_date": report_date.isoformat(),
        "phone": phone_number,
        "owner_phone_number": phone_number,
        "message": message_body,
        "body": message_body,
        "ghl_contact_id": ghl_contact_id or "",
        "ghl_location_id": ghl_location_id or "",
    }


def send_owner_sms(payload: dict[str, Any]) -> GHLOwnerSMSResult:
    webhook_url = getattr(settings, "GHL_OWNER_AGENT_SMS_WEBHOOK_URL", "")
    if not webhook_url:
        raise GHLOwnerSMSDeliveryError(
            "GHL_OWNER_AGENT_SMS_WEBHOOK_URL is not configured."
        )

    timeout = int(getattr(settings, "GHL_OWNER_AGENT_SMS_TIMEOUT_SECONDS", 10))
    try:
        response = requests.post(webhook_url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise GHLOwnerSMSDeliveryError(f"GoHighLevel request failed: {exc}") from exc

    response_payload = _response_payload(response)
    if response.status_code < 200 or response.status_code >= 300:
        raise GHLOwnerSMSDeliveryError(
            f"GoHighLevel returned HTTP {response.status_code}: {response_payload}"
        )

    return GHLOwnerSMSResult(
        message_id=_message_id(response_payload),
        response_payload=response_payload,
    )
