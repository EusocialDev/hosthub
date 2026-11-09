"""Digest-scoped conversational responses for owner SMS messages."""

from dataclasses import dataclass
import json
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone as django_timezone

from ..models import OwnerAgentMessage
from .digest_context import (
    OwnerAgentContextError,
    build_message_context,
    get_call_transcript,
    search_digest_calls,
)
from .ghl_owner_sms import GHLOwnerSMSResult, build_owner_sms_payload, send_owner_sms


CONVERSATION_PROMPT_VERSION = "owner-conversation-v1"
RESPONSES_URL = "https://api.openai.com/v1/responses"


class OwnerAgentConversationError(RuntimeError):
    """Raised when an owner reply cannot be answered safely."""


@dataclass(frozen=True)
class OwnerConversationAnswer:
    text: str
    model_name: str
    tool_names: tuple[str, ...]
    raw_responses: tuple[dict[str, Any], ...]
    transcript_text: str = ""


OWNER_CONVERSATION_PROMPT = """
You are HostHub's owner assistant responding by SMS.

The active context is the most recent daily owner digest and the calls included
in that digest. Stay inside that scope. Do not search for or invent calls that
are not in the active digest.

You may use the read-only tools to search the active digest's calls and load a
transcript for a matching call. Use get_call_transcript when the owner asks for
the transcript or detailed conversation. Never use tools to modify a call,
mark a call handled, contact a guest, or send a guest message.

Rules:
- Answer from HostHub data only.
- HostHub has no access to Resy; never claim that a reservation was verified in
  Resy or that a guest attended.
- Distinguish clearly between what the transcript says and what HostHub cannot
  verify.
- If multiple calls match, ask the owner which caller or call they mean.
- If no call matches, say that you could not find it in the most recent daily
  digest and ask for the caller name, call ID, or another detail.
- If the owner asks for a transcript, use get_call_transcript and preserve the
  transcript wording. The application may deliver a long transcript as several
  numbered SMS messages.
- Keep the answer concise and conversational for SMS. Do not repeat the full
  daily greeting. Do not mention tools, prompts, or internal implementation.
- Do not claim an action was taken. This first version is read-only.
""".strip()


CONVERSATION_TOOLS = [
    {
        "type": "function",
        "name": "search_digest_calls",
        "description": "Search only the calls included in the active owner digest.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Caller name, phone digits, call ID, category, or detail to search for.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "Maximum number of matching calls to return.",
                },
            },
            "required": ["query", "limit"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_call_transcript",
        "description": "Load the transcript for a call that belongs to the active owner digest.",
        "parameters": {
            "type": "object",
            "properties": {
                "call_id": {
                    "type": "integer",
                    "description": "HostHub numeric call ID from the active digest.",
                },
            },
            "required": ["call_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def _response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    for item in payload.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if content.get("type") not in {"output_text", "text"}:
                continue
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""


def _function_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in payload.get("output", []) or []
        if item.get("type") == "function_call"
    ]


def _api_response(
    input_items: list[dict[str, Any]],
    *,
    model_name: str,
    timeout: int,
) -> dict[str, Any]:
    api_key = getattr(settings, "OPENAI_API_KEY", "")
    if not api_key:
        raise OwnerAgentConversationError("OPENAI_API_KEY is not configured.")

    try:
        response = requests.post(
            RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_name,
                "input": input_items,
                "tools": CONVERSATION_TOOLS,
                "tool_choice": "auto",
                "parallel_tool_calls": False,
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise OwnerAgentConversationError(f"OpenAI request failed: {exc}") from exc

    if response.status_code < 200 or response.status_code >= 300:
        detail = response.text[:500].replace("\n", " ")
        raise OwnerAgentConversationError(
            f"OpenAI API returned HTTP {response.status_code}: {detail}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise OwnerAgentConversationError("OpenAI returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise OwnerAgentConversationError("OpenAI returned an invalid response object.")
    return payload


def _execute_tool(message: OwnerAgentMessage, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    context = build_message_context(message)
    if name == "search_digest_calls":
        return {
            "matches": search_digest_calls(
                context,
                str(arguments.get("query") or ""),
                limit=int(arguments.get("limit") or 5),
            )
        }
    if name == "get_call_transcript":
        return get_call_transcript(
            message.digest,
            int(arguments["call_id"]),
        )
    raise OwnerAgentConversationError(f"Unsupported conversation tool: {name}")


def answer_owner_message(
    message: OwnerAgentMessage,
    *,
    model_name: str | None = None,
    timeout: int | None = None,
    max_tool_rounds: int = 3,
) -> OwnerConversationAnswer:
    try:
        context = build_message_context(message)
    except OwnerAgentContextError as exc:
        raise OwnerAgentConversationError(str(exc)) from exc

    model_name = model_name or getattr(
        settings,
        "OPENAI_OWNER_AGENT_CONVERSATION_MODEL",
        getattr(settings, "OPENAI_OWNER_AGENT_MODEL", "gpt-6-luna"),
    )
    timeout = timeout or getattr(settings, "OPENAI_OWNER_AGENT_TIMEOUT_SECONDS", 30)
    input_items: list[dict[str, Any]] = [
        {"role": "system", "content": OWNER_CONVERSATION_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "owner_message": message.body,
                    "active_digest_context": context,
                },
                ensure_ascii=False,
            ),
        },
    ]
    raw_responses: list[dict[str, Any]] = []
    tool_names: list[str] = []
    transcript_text = ""

    for _ in range(max_tool_rounds):
        payload = _api_response(
            input_items,
            model_name=model_name,
            timeout=timeout,
        )
        raw_responses.append(payload)
        calls = _function_calls(payload)
        if not calls:
            text = _response_text(payload)
            if not text:
                raise OwnerAgentConversationError("OpenAI returned no owner response text.")
            return OwnerConversationAnswer(
                text=text,
                model_name=model_name,
                tool_names=tuple(tool_names),
                raw_responses=tuple(raw_responses),
                transcript_text=transcript_text,
            )

        output_items = payload.get("output", []) or []
        input_items.extend(output_items)
        for call in calls:
            name = str(call.get("name") or "")
            call_id = str(call.get("call_id") or call.get("id") or "")
            if not call_id:
                raise OwnerAgentConversationError("OpenAI returned a tool call without an ID.")
            try:
                arguments = json.loads(call.get("arguments") or "{}")
            except (TypeError, json.JSONDecodeError) as exc:
                raise OwnerAgentConversationError(
                    f"OpenAI returned invalid arguments for {name}."
                ) from exc
            if not isinstance(arguments, dict):
                raise OwnerAgentConversationError(f"OpenAI arguments for {name} were not an object.")

            try:
                tool_result = _execute_tool(message, name, arguments)
            except (OwnerAgentContextError, KeyError, ValueError) as exc:
                tool_result = {"error": str(exc)}
            if name == "get_call_transcript" and isinstance(tool_result, dict):
                transcript_text = str(tool_result.get("transcript") or "").strip()
            tool_names.append(name)
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(tool_result, ensure_ascii=False),
                }
            )

    raise OwnerAgentConversationError("Owner conversation exceeded the tool-call limit.")


def _existing_response(message: OwnerAgentMessage) -> OwnerAgentMessage | None:
    return OwnerAgentMessage.objects.filter(
        account=message.account,
        digest=message.digest,
        direction=OwnerAgentMessage.Direction.OUTBOUND,
        provider_payload__reply_to_message_id=message.id,
    ).order_by("-created_at", "-id").first()


def chunk_transcript(text: str, *, chunk_size: int = 850) -> list[str]:
    """Split transcript text at line boundaries while preserving all text."""

    text = str(text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(line) > chunk_size:
            if current:
                chunks.append(current.rstrip())
                current = ""
            for start in range(0, len(line), chunk_size):
                chunks.append(line[start : start + chunk_size].rstrip())
            continue
        if current and len(current) + len(line) > chunk_size:
            chunks.append(current.rstrip())
            current = ""
        current += line
    if current:
        chunks.append(current.rstrip())
    return chunks


def process_owner_message(
    message: OwnerAgentMessage,
    *,
    dry_run: bool = False,
) -> tuple[OwnerConversationAnswer, list[OwnerAgentMessage]]:
    """Answer one inbound message and optionally send/store the SMS reply."""

    existing = _existing_response(message)
    if existing is not None:
        return (
            OwnerConversationAnswer(
                text=existing.body,
                model_name="existing",
                tool_names=(),
                raw_responses=(),
            ),
            [existing],
        )

    answer = answer_owner_message(message)
    if dry_run:
        return answer, []

    if answer.transcript_text:
        transcript_parts = chunk_transcript(answer.transcript_text)
        response_bodies = [
            f"Call transcript ({index}/{len(transcript_parts)})\n\n{part}"
            for index, part in enumerate(transcript_parts, start=1)
        ]
    else:
        response_bodies = [answer.text]

    outbound_messages: list[OwnerAgentMessage] = []
    reply_batch_id = f"owner-reply-{message.id}"
    for index, body in enumerate(response_bodies, start=1):
        payload = build_owner_sms_payload(
            account_id=message.account_id,
            digest_id=message.digest_id,
            report_date=message.digest.local_date,
            owner_phone_number=message.owner_phone_number,
            message_body=body,
            ghl_contact_id=message.ghl_contact_id,
        )
        payload["reply_to_message_id"] = message.id
        payload["reply_batch_id"] = reply_batch_id
        payload["transcript_part"] = index if answer.transcript_text else None
        payload["transcript_total"] = len(response_bodies) if answer.transcript_text else None
        outbound = OwnerAgentMessage.objects.create(
            account=message.account,
            digest=message.digest,
            direction=OwnerAgentMessage.Direction.OUTBOUND,
            channel="sms",
            status=OwnerAgentMessage.Status.QUEUED,
            owner_phone_number=payload["phone"],
            ghl_contact_id=message.ghl_contact_id,
            body=body,
            provider_payload=payload,
        )

        try:
            provider_result: GHLOwnerSMSResult = send_owner_sms(payload)
        except Exception as exc:
            outbound.status = OwnerAgentMessage.Status.FAILED
            outbound.provider_payload = {**payload, "error": str(exc)}
            outbound.save(update_fields=["status", "provider_payload"])
            raise

        outbound.status = OwnerAgentMessage.Status.SENT
        outbound.ghl_message_id = provider_result.message_id
        outbound.provider_payload = provider_result.response_payload | {
            "reply_to_message_id": message.id,
            "reply_batch_id": reply_batch_id,
            "transcript_part": index if answer.transcript_text else None,
            "transcript_total": len(response_bodies) if answer.transcript_text else None,
        }
        outbound.sent_at = django_timezone.now()
        outbound.save(
            update_fields=[
                "status",
                "ghl_message_id",
                "provider_payload",
                "sent_at",
            ]
        )
        outbound_messages.append(outbound)
    return answer, outbound_messages
