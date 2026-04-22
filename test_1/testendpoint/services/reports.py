from ..models import Call
from datetime import datetime, time, timedelta
from django.db.models import Avg, Count, F, ExpressionWrapper, DurationField, Q
from django.utils import timezone
from django.db.models.functions import TruncHour

# ========== Handlers ===========================
def _get_handled_by_display(call):
    first_name = call.get("handled_by_user__first_name")
    last_name = call.get("handled_by_user__last_name")
    username = call.get("handled_by_user__username")
    legacy_handler = call.get("handled_by")

    full_name = " ".join(part for part in (first_name, last_name) if part)

    return first_name or full_name or username or (
        legacy_handler.title() if legacy_handler else None
    )


def _get_report_window(report_date=None):
    local_now = timezone.localtime()
    # for now if no date is passed to function, it will return report date as previous day
    if report_date is None:
        report_date = (local_now - timedelta(days=1)).date()

    start_of_day = timezone.make_aware(datetime.combine(report_date, time.min))
    end_of_day = start_of_day + timedelta(days=1)

    return report_date, start_of_day, end_of_day

def _format_choice_counts(raw_counts, field_name, choices):
    choice_map = dict(choices)

    return [
        {
            "value": row[field_name],
            "label": choice_map.get(row[field_name], row[field_name]),
            "count": row["count"],
        }
        for row in raw_counts
    ]

def _format_handler_counts(raw_counts):
    grouped_counts = {}

    for row in raw_counts:
        label = _get_handled_by_display(row)

        if not label:
            continue

        if label not in grouped_counts:
            grouped_counts[label] = {
                "value": label,
                "label": label,
                "count": 0,
            }

        grouped_counts[label]["count"] += row["count"]

    return sorted(
        grouped_counts.values(),
        key=lambda handler: handler["count"],
        reverse=True,
    )


def _group_handled_calls_by_person(calls, category_choices, disposition_choices):
    category_map = dict(category_choices)
    disposition_map=dict(disposition_choices)

    grouped = {}

    for call in calls:
        handler = call.get("handled_by_label")
        if not handler:
            continue
        
        if handler not in grouped:
            grouped[handler] = {
                "value": handler,
                "label": handler,
                "count": 0,
                "calls": [],
            }

        grouped[handler]["calls"].append(
            {
                "id":call["id"],
                "bland_call_id": call["bland_call_id"],
                "user_name": call["user_name"],
                "from_number":call["from_number"],
                "created_at":call["created_at"],
                "handled_at":call["handled_at"],
                "display_category":call["display_category"],
                "display_category_label":category_map.get(
                    call["display_category"], call["display_category"]
                ),
                "disposition":call["disposition"],
                "disposition_label": disposition_map.get(
                    call["disposition"], call["disposition"]
                ) if call["disposition"] else None,
                "summary": call["summary"],
                "notes": call["notes"],
            }
        )

        grouped[handler]["count"] +=1
    return sorted(
    grouped.values(),
    key=lambda person: person["count"],
    reverse=True,
    )   

def _format_calls_for_display(calls, category_choices, disposition_choices):
    category_map = dict(category_choices)
    disposition_map=dict(disposition_choices)

    formatted = []

    for call in calls:
        formatted.append({
            **call,
            "display_category_label": category_map.get(
                call.get("display_category"),
                call.get("display_category"),
            ),
            "disposition_label": disposition_map.get(
                call.get("disposition"),
                call.get("disposition"),
            ) if call.get("disposition") else None,
            "handled_by_label": _get_handled_by_display(call),
        })
    return formatted

def _build_call_report_section(calls_qs):
    total_calls = calls_qs.count()
    resolved_calls = calls_qs.filter(host_status="resolved").count()
    unresolved_calls = calls_qs.exclude(host_status="resolved").count()

    raw_category_counts = list(
        calls_qs.values("display_category")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    raw_disposition_counts = list(
        calls_qs.exclude(disposition__isnull=True)
        .exclude(disposition__exact="")
        .values("disposition")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    raw_handler_counts = list(
        calls_qs.filter(host_status="resolved")
        .filter(
            Q(handled_by_user__isnull=False)
            | (Q(handled_by__isnull=False) & ~Q(handled_by__exact=""))
        )
        .values(
            "handled_by_user__first_name",
            "handled_by_user__last_name",
            "handled_by_user__username",
            "handled_by",
        )
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    by_category = _format_choice_counts(
        raw_counts=raw_category_counts,
        field_name="display_category",
        choices=Call._meta.get_field("display_category").choices,
    )

    by_disposition = _format_choice_counts(
        raw_counts=raw_disposition_counts,
        field_name="disposition",
        choices=Call._meta.get_field("disposition").choices,
    )

    by_handler = _format_handler_counts(raw_handler_counts)

    avg_duration_seconds = calls_qs.aggregate(
        avg=Avg("duration_seconds")
    )["avg"]

    resolution_qs = calls_qs.filter(
        host_status="resolved",
        handled_at__isnull=False,
        created_at__isnull=False,
    ).annotate(
        resolution_time=ExpressionWrapper(
            F("handled_at") - F("created_at"),
            output_field=DurationField(),
        )
    )

    avg_resolution_time = resolution_qs.aggregate(
        avg=Avg("resolution_time")
    )["avg"]

    avg_resolution_display = None

    if avg_resolution_time:
        days = avg_resolution_time.days
        seconds = avg_resolution_time.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60

        if days > 0:
            avg_resolution_display = f"{days}d {hours}h"
        elif hours > 0:
            avg_resolution_display = f"{hours}h {minutes}m"
        elif minutes > 0:
            avg_resolution_display = f"{minutes}m"
        else:
            avg_resolution_display = f"{seconds}s"

    needs_action = _format_calls_for_display(
        list(
            calls_qs.exclude(host_status="resolved")
            .order_by("created_at")
            .values(
                "id",
                "bland_call_id",
                "user_name",
                "from_number",
                "location__name",
                "display_category",
                "summary",
                "created_at",
                "host_status",
                "notes",
            )
        ),
        category_choices=Call._meta.get_field("display_category").choices,
        disposition_choices=Call._meta.get_field("disposition").choices,
    )

    calls_by_hour = list(
        calls_qs.annotate(hour=TruncHour("created_at"))
        .values("hour")
        .annotate(count=Count("id"))
        .order_by("hour")
    )

    detailed_calls = _format_calls_for_display(
        list(
            calls_qs.order_by("created_at").values(
                "id",
                "bland_call_id",
                "user_name",
                "from_number",
                "to_number",
                "location__name",
                "created_at",
                "started_at",
                "ended_at",
                "duration_seconds",
                "display_category",
                "host_status",
                "handled_at",
                "handled_by",
                "handled_by_user__first_name",
                "handled_by_user__last_name",
                "handled_by_user__username",
                "disposition",
                "summary",
                "notes",
            )
        ),
        category_choices=Call._meta.get_field("display_category").choices,
        disposition_choices=Call._meta.get_field("disposition").choices,
    )

    handled_calls_by_person = _group_handled_calls_by_person(
        calls=[
            call for call in detailed_calls
            if call["handled_by_label"] and call["host_status"] == "resolved"
        ],
        category_choices=Call._meta.get_field("display_category").choices,
        disposition_choices=Call._meta.get_field("disposition").choices,
    )

    return {
        "total_calls": total_calls,
        "resolved_calls": resolved_calls,
        "unresolved_calls": unresolved_calls,
        "avg_duration_seconds": avg_duration_seconds,
        "avg_resolution_time": avg_resolution_time,
        "avg_resolution_display": avg_resolution_display,
        "by_category": by_category,
        "by_disposition": by_disposition,
        "by_handler": by_handler,
        "calls_by_hour": calls_by_hour,
        "needs_action": needs_action,
        "detailed_calls": detailed_calls,
        "handled_calls_by_person": handled_calls_by_person,
    }


# ============= Main function ===================
def build_daily_call_report(account, report_date=None):
    """
    Function to orchestrate the creation of a Report based on the date of calls that were created, 
    how they were handled, and who they were handled by. 
    First implementation will be for a daily email, but same function can be later used for dashboards.
    """
    report_date, start_of_day, end_of_day = _get_report_window(report_date)

    base_qs = Call.objects.filter(
        account = account,
        created_at__gte = start_of_day,
        created_at__lt = end_of_day
    ).select_related("account", "location", "phone_number")

    summary = _build_call_report_section(base_qs)

    location_sections = []

    locations = account.locations.filter(is_active=True).order_by("name")

    for location in locations:
        location_qs = base_qs.filter(location=location)

        section = _build_call_report_section(location_qs)
        section["location"] = location
        location_sections.append(section)

    return {
        "account": account,
        "report_date": report_date,
        "start_of_day": start_of_day,
        "end_of_day": end_of_day,
        "summary": summary,
        "locations": location_sections,
    }
