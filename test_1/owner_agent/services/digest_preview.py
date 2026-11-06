"""Read-only daily owner digest preview."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import QuerySet
from django.utils import timezone as django_timezone

from testendpoint.models import Account, Call
from testendpoint.utils.phone import _normalize_phone_number

from .assessment import assess_call


@dataclass(frozen=True)
class DigestPreview:
    account_id: int
    account_name: str
    report_date: date
    timezone_name: str
    evaluation_time: datetime
    total_calls: int
    handled_calls: int
    unhandled_calls: int
    attention_calls: int
    context_calls: int
    attention_items: list[dict[str, Any]]
    context_items: list[dict[str, Any]]
    call_assessments: list[dict[str, Any]]
    message_body: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get_timezone(account: Account, timezone_name: str | None = None) -> ZoneInfo:
    candidate = timezone_name
    if not candidate:
        candidate = (
            account.locations.filter(is_active=True)
            .order_by("id")
            .values_list("timezone", flat=True)
            .first()
        )
    try:
        return ZoneInfo(candidate or "America/Detroit")
    except (ZoneInfoNotFoundError, TypeError):
        return ZoneInfo("America/Detroit")


def _default_report_date(tz: ZoneInfo) -> date:
    return django_timezone.localtime(django_timezone.now(), tz).date() - timedelta(days=1)


def _local_window(report_date: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(report_date, time.min).replace(tzinfo=tz)
    return start, start + timedelta(days=1)


def _digest_evaluation_time(report_date: date, tz: ZoneInfo) -> datetime:
    """Use the default 10 AM local digest time for deterministic previews."""

    return datetime.combine(report_date + timedelta(days=1), time(10, 0)).replace(tzinfo=tz)


def _clean_summary(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _display_summary(call: Call, analysis: Any | None = None) -> str:
    analysis_summary = getattr(analysis, "normalized_summary", "") if analysis else ""
    summary = _clean_summary(analysis_summary or call.summary)
    if not summary:
        return f"Call categorized as {call.get_display_category_display()} with no summary available."

    name = _clean_summary(call.user_name)
    if name:
        summary = re.sub(r"^(the )?caller\b", name, summary, flags=re.IGNORECASE)
    return summary


def _short_summary(call: Call, analysis: Any | None = None, max_length: int = 240) -> str:
    summary = _display_summary(call, analysis=analysis)
    if len(summary) <= max_length:
        return summary
    return summary[: max_length - 1].rstrip() + "…"


def _format_phone_number(value: str | None) -> str | None:
    normalized = _normalize_phone_number(value)
    if not normalized:
        return None

    digits = normalized.lstrip("+")
    if len(digits) == 11 and digits.startswith("1"):
        return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    return normalized


def _item(
    call: Call,
    result: Any,
    *,
    include_phone: bool = False,
    analysis: Any | None = None,
) -> dict[str, Any]:
    item = {
        "call_id": call.id,
        "bland_call_id": call.bland_call_id,
        "user_name": call.user_name,
        "from_last_four": (call.from_number or "")[-4:] or None,
        "display_category": call.display_category,
        "summary": _short_summary(call, analysis=analysis),
        "status": result.status,
        "reason": result.reason,
        "explanation": result.explanation,
        "basis": result.basis,
    }
    if include_phone:
        item["phone_number"] = _format_phone_number(call.from_number)
    return item


def _count_phrase(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def _context_lines(context_items: list[dict[str, Any]]) -> list[str]:
    grouped: dict[str, int] = {}
    for item in context_items:
        grouped[item["reason"]] = grouped.get(item["reason"], 0) + 1

    lines = []
    for reason, count in grouped.items():
        if reason == "silent_call":
            lines.append(
                f"{_count_phrase(count, 'unhandled call')} contained no meaningful customer conversation."
            )
        elif reason in {"past_reservation", "past_commitment"}:
            lines.append(
                f"{_count_phrase(count, 'unhandled call')} was about a commitment whose requested date had passed."
            )
        else:
            lines.append(
                f"{_count_phrase(count, 'other unhandled call')} did not have an identifiable future commitment."
            )
    return lines


def _compose_message(
    *,
    total_calls: int,
    handled_calls: int,
    unhandled_calls: int,
    attention_items: list[dict[str, Any]],
    context_items: list[dict[str, Any]],
) -> str:
    lines = [
        f"Yesterday you received {total_calls} calls.",
        f"{handled_calls} were marked handled in HostHub.",
    ]

    if not unhandled_calls:
        lines.append("There were no unhandled calls.")
        return "\n".join(lines)

    if attention_items:
        lines.append(
            f"{unhandled_calls} were not marked handled, but only {len(attention_items)} may need attention:"
        )
        lines.append("")
        for index, item in enumerate(attention_items, start=1):
            summary = item["summary"]
            name = _clean_summary(item.get("user_name"))
            phone_number = item.get("phone_number")
            if phone_number:
                if name and summary.lower().startswith(name.lower()):
                    summary = f"{name} {phone_number}{summary[len(name):]}"
                elif name:
                    summary = f"{name} {phone_number} — {summary}"
                else:
                    summary = f"{phone_number} — {summary}"
            lines.append(f"{index}. {summary}")
    else:
        lines.append(
            f"{unhandled_calls} were not marked handled, but none may need attention."
        )

    if context_items:
        lines.append("")
        lines.append(
            f"For context, the other {len(context_items)} unhandled calls:"
        )
        lines.extend(f"- {line}" for line in _context_lines(context_items))

    return "\n".join(lines)


def build_digest_preview(
    account: Account,
    *,
    report_date: date | None = None,
    timezone_name: str | None = None,
    evaluation_time: datetime | None = None,
    calls_qs: QuerySet | None = None,
    analysis_by_call_id: dict[int, Any] | None = None,
) -> DigestPreview:
    """Build a digest preview without saving or sending anything."""

    tz = _get_timezone(account, timezone_name=timezone_name)
    report_date = report_date or _default_report_date(tz)
    start_local, end_local = _local_window(report_date, tz)
    evaluation_time = evaluation_time or _digest_evaluation_time(report_date, tz)
    if django_timezone.is_naive(evaluation_time):
        evaluation_time = django_timezone.make_aware(evaluation_time, timezone=tz)
    else:
        evaluation_time = evaluation_time.astimezone(tz)

    if calls_qs is None:
        calls_qs = Call.objects.filter(
            account=account,
            created_at__gte=start_local,
            created_at__lt=end_local,
        )

    calls = list(calls_qs.select_related("location").order_by("created_at", "id"))
    attention_items: list[dict[str, Any]] = []
    context_items: list[dict[str, Any]] = []
    call_assessments: list[dict[str, Any]] = []
    handled_calls = 0

    for call in calls:
        analysis = (analysis_by_call_id or {}).get(call.id)
        result = assess_call(
            call,
            evaluation_time=evaluation_time,
            evaluated_for_date=evaluation_time.astimezone(tz).date(),
            timezone_name=tz.key,
            analysis=analysis,
        )

        assessment_item = _item(
            call,
            result,
            include_phone=result.status == "needs_attention",
            analysis=analysis,
        )
        call_assessments.append(assessment_item)

        if result.status == "handled":
            handled_calls += 1
        elif result.status == "needs_attention":
            attention_items.append(assessment_item)
        else:
            context_items.append(assessment_item)

    unhandled_calls = len(calls) - handled_calls
    message_body = _compose_message(
        total_calls=len(calls),
        handled_calls=handled_calls,
        unhandled_calls=unhandled_calls,
        attention_items=attention_items,
        context_items=context_items,
    )

    return DigestPreview(
        account_id=account.id,
        account_name=account.name,
        report_date=report_date,
        timezone_name=tz.key,
        evaluation_time=evaluation_time,
        total_calls=len(calls),
        handled_calls=handled_calls,
        unhandled_calls=unhandled_calls,
        attention_calls=len(attention_items),
        context_calls=len(context_items),
        attention_items=attention_items,
        context_items=context_items,
        call_assessments=call_assessments,
        message_body=message_body,
    )
