"""Build, persist, and deliver one owner-agent daily digest."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone as django_timezone

from testendpoint.models import Account, Call

from ..models import (
    OwnerAgentAnalysis,
    OwnerAgentAssessment,
    OwnerAgentDigest,
    OwnerAgentDigestItem,
    OwnerAgentMessage,
    OwnerAgentSettings,
)
from .assessment import assess_and_save_call
from .digest_preview import DigestPreview, build_digest_preview
from .ghl_owner_sms import (
    GHLOwnerSMSResult,
    build_owner_sms_payload,
    send_owner_sms,
)
from .openai_analysis import OpenAIAnalysisError, analyze_call, save_analysis


class OwnerAgentDigestDeliveryError(RuntimeError):
    """Raised when a digest cannot be safely prepared or delivered."""


@dataclass(frozen=True)
class DigestDeliveryResult:
    digest: OwnerAgentDigest | None
    message: OwnerAgentMessage | None
    sent: bool
    dry_run: bool
    preview: DigestPreview


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, TypeError):
        return ZoneInfo("America/Detroit")


def scheduled_for(settings: OwnerAgentSettings, report_date: date) -> datetime:
    tz = _timezone(settings.timezone_name)
    preferred_time = settings.preferred_time or time(10, 0)
    return datetime.combine(report_date + timedelta(days=1), preferred_time).replace(tzinfo=tz)


def _openai_analysis_by_call(
    preview: DigestPreview,
    *,
    max_calls: int,
    persist: bool,
) -> dict[int, Any]:
    unhandled_ids = [
        item["call_id"]
        for item in preview.call_assessments
        if item["status"] != OwnerAgentAssessment.Status.HANDLED
    ]
    if len(unhandled_ids) > max_calls:
        raise OwnerAgentDigestDeliveryError(
            f"{len(unhandled_ids)} unhandled calls require analysis, but the limit is {max_calls}."
        )

    calls = list(
        Call.objects.filter(id__in=unhandled_ids)
        .select_related("location")
        .order_by("created_at", "id")
    )
    results: dict[int, Any] = {}
    for call in calls:
        try:
            result = analyze_call(call, evaluation_time=preview.evaluation_time)
        except OpenAIAnalysisError as exc:
            raise OwnerAgentDigestDeliveryError(
                f"OpenAI analysis failed for call {call.id}: {exc}"
            ) from exc
        results[call.id] = save_analysis(call, result) if persist else result
    return results


def _save_assessments(
    preview: DigestPreview,
    *,
    analysis_by_call_id: dict[int, Any],
) -> None:
    call_ids = [item["call_id"] for item in preview.call_assessments]
    calls = Call.objects.filter(id__in=call_ids).select_related("location")
    for call in calls:
        analysis = analysis_by_call_id.get(call.id)
        assess_and_save_call(
            call,
            evaluation_time=preview.evaluation_time,
            evaluated_for_date=preview.evaluation_time.date(),
            timezone_name=preview.timezone_name,
            analysis=analysis,
        )


def _snapshot_digest(
    account: Account,
    settings: OwnerAgentSettings,
    preview: DigestPreview,
    *,
    analysis_by_call_id: dict[int, Any],
) -> OwnerAgentDigest:
    scheduled_time = scheduled_for(settings, preview.report_date)
    with transaction.atomic():
        digest, _ = OwnerAgentDigest.objects.select_for_update().get_or_create(
            account=account,
            local_date=preview.report_date,
            defaults={"scheduled_for": scheduled_time},
        )
        if digest.status == OwnerAgentDigest.Status.SENT:
            return digest

        digest.scheduled_for = scheduled_time
        digest.status = OwnerAgentDigest.Status.DRAFT
        digest.sent_at = None
        digest.message_body = preview.message_body
        digest.error_message = ""
        digest.total_calls = preview.total_calls
        digest.handled_calls = preview.handled_calls
        digest.unhandled_calls = preview.unhandled_calls
        digest.attention_calls = preview.attention_calls
        digest.context_calls = preview.context_calls
        digest.save()

        digest.items.all().delete()
        for position, item in enumerate(preview.attention_items, start=1):
            call = Call.objects.get(id=item["call_id"])
            OwnerAgentDigestItem.objects.create(
                digest=digest,
                call=call,
                section=OwnerAgentDigestItem.Section.ATTENTION,
                position=position,
                reason=item["reason"],
                summary=item["summary"],
                source_snapshot=item,
            )
        for position, item in enumerate(preview.context_items, start=1):
            call = Call.objects.get(id=item["call_id"])
            OwnerAgentDigestItem.objects.create(
                digest=digest,
                call=call,
                section=OwnerAgentDigestItem.Section.CONTEXT,
                position=position,
                reason=item["reason"],
                summary=item["summary"],
                source_snapshot=item,
            )

        _save_assessments(preview, analysis_by_call_id=analysis_by_call_id)
        return digest


def build_delivery_preview(
    account: Account,
    settings: OwnerAgentSettings,
    *,
    report_date: date,
    use_openai: bool,
    max_openai_calls: int,
    persist_analysis: bool,
) -> tuple[DigestPreview, dict[int, Any]]:
    scheduled_time = scheduled_for(settings, report_date)
    baseline = build_digest_preview(
        account,
        report_date=report_date,
        timezone_name=settings.timezone_name,
        evaluation_time=scheduled_time,
    )
    if not use_openai:
        return baseline, {}

    analysis_by_call_id = _openai_analysis_by_call(
        baseline,
        max_calls=max_openai_calls,
        persist=persist_analysis,
    )
    enhanced = build_digest_preview(
        account,
        report_date=report_date,
        timezone_name=settings.timezone_name,
        evaluation_time=scheduled_time,
        analysis_by_call_id=analysis_by_call_id,
    )
    return enhanced, analysis_by_call_id


def deliver_owner_digest(
    account: Account,
    settings: OwnerAgentSettings,
    *,
    report_date: date,
    use_openai: bool = True,
    max_openai_calls: int = 100,
    dry_run: bool = False,
) -> DigestDeliveryResult:
    if not settings.owner_phone_number:
        raise OwnerAgentDigestDeliveryError("Owner phone number is not configured.")
    if not dry_run and not settings.enabled:
        raise OwnerAgentDigestDeliveryError("Owner agent is disabled for this account.")

    preview, analysis_by_call_id = build_delivery_preview(
        account,
        settings,
        report_date=report_date,
        use_openai=use_openai,
        max_openai_calls=max_openai_calls,
        persist_analysis=not dry_run,
    )

    if dry_run:
        return DigestDeliveryResult(
            digest=None,
            message=None,
            sent=False,
            dry_run=True,
            preview=preview,
        )

    digest = _snapshot_digest(
        account,
        settings,
        preview,
        analysis_by_call_id=analysis_by_call_id,
    )
    if digest.status == OwnerAgentDigest.Status.SENT:
        return DigestDeliveryResult(
            digest=digest,
            message=digest.messages.filter(
                direction=OwnerAgentMessage.Direction.OUTBOUND,
                status__in=[
                    OwnerAgentMessage.Status.SENT,
                    OwnerAgentMessage.Status.DELIVERED,
                ],
            ).order_by("-created_at").first(),
            sent=False,
            dry_run=False,
            preview=preview,
        )

    payload = build_owner_sms_payload(
        account_id=account.id,
        digest_id=digest.id,
        report_date=preview.report_date,
        owner_phone_number=settings.owner_phone_number,
        message_body=preview.message_body,
        ghl_contact_id=settings.ghl_contact_id,
        ghl_location_id=settings.ghl_location_id,
    )
    message = OwnerAgentMessage.objects.create(
        account=account,
        digest=digest,
        direction=OwnerAgentMessage.Direction.OUTBOUND,
        channel="sms",
        status=OwnerAgentMessage.Status.QUEUED,
        owner_phone_number=payload["phone"],
        ghl_contact_id=settings.ghl_contact_id,
        body=preview.message_body,
        provider_payload=payload,
    )

    try:
        provider_result: GHLOwnerSMSResult = send_owner_sms(payload)
    except Exception as exc:
        message.status = OwnerAgentMessage.Status.FAILED
        message.provider_payload = {**payload, "error": str(exc)}
        message.save(update_fields=["status", "provider_payload"])
        digest.status = OwnerAgentDigest.Status.FAILED
        digest.error_message = str(exc)
        digest.save(update_fields=["status", "error_message", "updated_at"])
        raise

    now = django_timezone.now()
    message.status = OwnerAgentMessage.Status.SENT
    message.ghl_message_id = provider_result.message_id
    message.provider_payload = provider_result.response_payload
    message.sent_at = now
    message.save(
        update_fields=[
            "status",
            "ghl_message_id",
            "provider_payload",
            "sent_at",
        ]
    )

    digest.status = OwnerAgentDigest.Status.SENT
    digest.sent_at = now
    digest.ghl_message_id = provider_result.message_id
    digest.provider_response = provider_result.response_payload
    digest.error_message = ""
    digest.save(
        update_fields=[
            "status",
            "sent_at",
            "ghl_message_id",
            "provider_response",
            "error_message",
            "updated_at",
        ]
    )
    return DigestDeliveryResult(
        digest=digest,
        message=message,
        sent=True,
        dry_run=False,
        preview=preview,
    )
