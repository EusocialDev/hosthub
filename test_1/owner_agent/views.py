import json

from django.conf import settings
from django.http import HttpResponseNotAllowed, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .services.owner_inbox import (
    OwnerAgentInboundMessageError,
    ingest_owner_reply,
    valid_inbound_token,
)
from .services.owner_conversation import process_owner_message


@csrf_exempt
def owner_agent_inbound_webhook(request, token: str):
    """Receive an owner SMS forwarded by a GoHighLevel workflow."""

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    expected_token = getattr(settings, "GHL_OWNER_AGENT_INBOUND_WEBHOOK_TOKEN", "")
    if not valid_inbound_token(token, expected_token):
        return JsonResponse({"ok": False, "error": "Invalid webhook token."}, status=403)

    content_type = (request.headers.get("Content-Type") or "").lower()
    if "application/json" not in content_type:
        return JsonResponse(
            {"ok": False, "error": "Expected application/json."},
            status=415,
        )

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return JsonResponse(
            {"ok": False, "error": f"Invalid JSON payload: {exc}"},
            status=400,
        )

    try:
        result = ingest_owner_reply(payload)
    except OwnerAgentInboundMessageError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    try:
        answer, response_messages = process_owner_message(result.message)
    except Exception as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": str(exc),
                "message_id": result.message.id,
            },
            status=500,
        )

    return JsonResponse(
        {
            "ok": True,
            "duplicate": result.duplicate,
            "message_id": result.message.id,
            "digest_id": result.message.digest_id,
            "account_id": result.message.account_id,
            "response_message_id": response_messages[0].id if response_messages else None,
            "response_message_ids": [message.id for message in response_messages],
            "response_body": answer.text,
        }
    )
