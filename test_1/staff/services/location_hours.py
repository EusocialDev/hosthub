from testendpoint.models import BusinessHour, DateOverride, Location
from datetime import date as date_type, datetime, time as time_type, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.utils import timezone as dj_timezone

from testendpoint.views import ensure_location_bland_matches_expected

# --------- Override Button logic  ---------

def clear_expired_manual_override(location, now=None):
    now = now or get_location_local_now(location)

    if (
        location.manual_override_status
        and location.manual_override_until
        and location.manual_override_until <= now
    ):
        location.manual_override_status = None
        location.manual_override_until = None
        location.manual_override_reason = None
        location.manual_override_set_at = None
        location.manual_override_set_by = None
        location.save(update_fields=[
            "manual_override_status",
            "manual_override_until",
            "manual_override_reason",
            "manual_override_set_at",
            "manual_override_set_by",
        ])

def get_active_manual_override(location, now=None) -> str | None:
    now = now or get_location_local_now(location)

    if (
        location.manual_override_status
        and location.manual_override_until
        and location.manual_override_until > now
    ):
        return location.manual_override_status

    return None
 # --------- End Clean Override Button logic ---------


def get_location_local_now(location) -> datetime:
    try:
        tz = ZoneInfo(location.timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return datetime.now(tz)

def get_business_hour_for_day(location, weekday) -> BusinessHour | None:
    return location.business_hours.filter(day_of_week=weekday).first()

def get_active_date_override(location, date) -> DateOverride | None:
    return DateOverride.objects.filter(
        location=location,
        start_date__lte=date,
        end_date__gte=date,
    ).first()


def _time_is_within_hours(open_time, close_time, requested_time) -> bool:
    """Return whether a local time falls inside an hours interval.

    A close time earlier than the open time represents an overnight interval,
    for example 22:00-02:00. When evaluating the schedule row for the
    requested date, only the evening portion belongs to that date; the
    after-midnight portion is evaluated from the previous day's schedule.
    Equal times are treated as closed because the schedule does not describe
    a usable interval.
    """
    if not open_time or not close_time or open_time == close_time:
        return False
    if open_time < close_time:
        return open_time <= requested_time < close_time
    return requested_time >= open_time


def _hours_payload(open_time, close_time):
    if not open_time or not close_time:
        return None
    return {
        "open": open_time.strftime("%H:%M"),
        "close": close_time.strftime("%H:%M"),
    }


def get_location_open_status(location, requested_date: date_type, requested_time: time_type) -> dict:
    """Resolve whether a location is open at a local date and time.

    The result is intentionally descriptive so callers such as the voice
    agent can explain *why* the location is open or closed. Date overrides
    take precedence over weekly hours, matching the existing scheduler.
    """
    override = get_active_date_override(location, requested_date)
    if override:
        hours = _hours_payload(override.open_time, override.close_time)
        if override.is_closed or not hours:
            return {
                "is_open": False,
                "reason_code": "date_override_closed",
                "reason": f"Closed: {override.name}",
                "source": "date_override",
                "override_name": override.name,
                "hours": None,
            }
        is_open = _time_is_within_hours(
            override.open_time, override.close_time, requested_time
        )
        return {
            "is_open": is_open,
            "reason_code": "date_override",
            "reason": (
                f"Special hours: {override.name}"
                if is_open
                else f"Outside special hours: {override.name}"
            ),
            "source": "date_override",
            "override_name": override.name,
            "hours": hours,
        }

    business_hour = get_business_hour_for_day(location, requested_date.weekday())
    if business_hour and not business_hour.is_closed:
        hours = _hours_payload(business_hour.open_time, business_hour.close_time)
        if hours and _time_is_within_hours(
            business_hour.open_time, business_hour.close_time, requested_time
        ):
            return {
                "is_open": True,
                "reason_code": "regular_hours",
                "reason": "Regular business hours",
                "source": "business_hours",
                "override_name": None,
                "hours": hours,
            }

    # A previous day's overnight schedule may still be active after midnight.
    previous_date = requested_date - timedelta(days=1)
    previous_override = get_active_date_override(location, previous_date)
    previous_schedule = previous_override or get_business_hour_for_day(
        location, previous_date.weekday()
    )
    if previous_schedule:
        previous_is_closed = getattr(previous_schedule, "is_closed", False)
        previous_open = getattr(previous_schedule, "open_time", None)
        previous_close = getattr(previous_schedule, "close_time", None)
        previous_hours = _hours_payload(previous_open, previous_close)
        if (
            not previous_is_closed
            and previous_hours
            and previous_open > previous_close
            and requested_time < previous_close
        ):
            if previous_override:
                reason_code = "date_override"
                reason = f"Special hours: {previous_override.name}"
                source = "date_override"
                override_name = previous_override.name
            else:
                reason_code = "regular_hours"
                reason = "Regular business hours from the previous day"
                source = "business_hours"
                override_name = None
            return {
                "is_open": True,
                "reason_code": reason_code,
                "reason": reason,
                "source": source,
                "override_name": override_name,
                "hours": previous_hours,
            }

    if business_hour and not business_hour.is_closed and business_hour.open_time and business_hour.close_time:
        closed_reason = "Outside regular business hours"
    elif business_hour and business_hour.is_closed:
        closed_reason = "Closed in the regular schedule"
    else:
        closed_reason = "No regular hours are configured"

    return {
        "is_open": False,
        "reason_code": "regular_hours_closed",
        "reason": closed_reason,
        "source": "business_hours",
        "override_name": None,
        "hours": _hours_payload(
            business_hour.open_time,
            business_hour.close_time,
        ) if business_hour and not business_hour.is_closed else None,
    }

def is_location_effectively_open(location, now=None) -> bool:
    now = now or get_location_local_now(location)

    clear_expired_manual_override(location, now)
    override = get_active_manual_override(location, now)

    if override == "open":
        return True
    
    if override == "closed":
        return False
    return is_location_open_now_by_hours(location, now)

def is_location_open_now_by_hours(location, now=None) -> bool:
    now = now or get_location_local_now(location)
    today_date = now.date()
    current_time = now.time()
    weekday = now.weekday()

    # DateOverride takes full precedence over BusinessHour
    date_override = get_active_date_override(location, today_date)
    if date_override:
        if date_override.is_closed:
            return False
        if date_override.open_time and date_override.close_time:
            open_time = date_override.open_time
            close_time = date_override.close_time
            if open_time < close_time:
                return open_time <= current_time < close_time
            return current_time >= open_time  # overnight special hours
        return False

    # No override — fall through to regular BusinessHour logic
    today = get_business_hour_for_day(location, weekday)
    if today and not today.is_closed and today.open_time and today.close_time:
        open_time = today.open_time
        close_time = today.close_time
        if open_time < close_time:
            if open_time <= current_time < close_time:
                return True
        if close_time < open_time:
            if current_time >= open_time:
                return True

    yesterday_weekday = (weekday - 1) % 7
    yesterday = get_business_hour_for_day(location, yesterday_weekday)
    if yesterday and not yesterday.is_closed and yesterday.open_time and yesterday.close_time:
        y_open = yesterday.open_time
        y_close = yesterday.close_time
        if y_close < y_open:
            if current_time < y_close:
                return True

    return False


def get_desired_pathway(location, now=None) -> str | None:
    open_pathway_id = location.bland_pathway_id_open
    closed_pathway_id = location.bland_pathway_id_closed

    if not location.scheduling_enabled:
        return None

    if is_location_effectively_open(location, now):
        return open_pathway_id
    
    else:
        return closed_pathway_id
    
def get_next_transition_datetime(location, now=None) -> datetime | None:
    now = now or get_location_local_now(location)
    tz = now.tzinfo
    weekday = now.weekday()
    current_time = now.time()
    today_date = now.date()
    midnight = datetime.min.time()

    # If a DateOverride is active today, derive the transition from it
    active_override = get_active_date_override(location, today_date)
    if active_override:
        if active_override.is_closed:
            return datetime.combine(
                active_override.end_date + timedelta(days=1), midnight, tzinfo=tz
            )
        open_time = active_override.open_time
        close_time = active_override.close_time
        if open_time and close_time:
            open_dt = datetime.combine(today_date, open_time, tzinfo=tz)
            if open_time < close_time:
                close_dt = datetime.combine(today_date, close_time, tzinfo=tz)
                if now < open_dt:
                    return open_dt
                if open_dt <= now < close_dt:
                    return close_dt
            else:  # overnight special hours
                close_dt = datetime.combine(today_date + timedelta(days=1), close_time, tzinfo=tz)
                if current_time < open_time:
                    return open_dt
                return close_dt
        # After close or no times set — wake at midnight to re-evaluate next day
        return datetime.combine(today_date + timedelta(days=1), midnight, tzinfo=tz)

    # No active DateOverride today — regular BusinessHour logic
    yesterday_weekday = (weekday - 1) % 7
    yesterday = get_business_hour_for_day(location, yesterday_weekday)
    if yesterday and not yesterday.is_closed and yesterday.open_time and yesterday.close_time:
        if yesterday.close_time < yesterday.open_time:
            spill_close_dt = datetime.combine(now.date(), yesterday.close_time, tzinfo=tz)
            if current_time < yesterday.close_time:
                return spill_close_dt

    today = get_business_hour_for_day(location, weekday)
    if today and not today.is_closed and today.open_time and today.close_time:
        open_dt = datetime.combine(now.date(), today.open_time, tzinfo=tz)
        if today.open_time < today.close_time:
            close_dt = datetime.combine(now.date(), today.close_time, tzinfo=tz)
            if now < open_dt:
                return open_dt
            if open_dt <= now < close_dt:
                return close_dt
        elif today.close_time < today.open_time:
            close_dt = datetime.combine(now.date(), today.close_time, tzinfo=tz) + timedelta(days=1)
            if current_time < today.open_time:
                return open_dt
            if current_time >= today.open_time:
                return close_dt

    for offset in range(1, 8):
        future_day = now + timedelta(days=offset)
        future_date = future_day.date()
        future_weekday = future_day.weekday()

        future_override = get_active_date_override(location, future_date)
        if future_override:
            if future_override.is_closed:
                return datetime.combine(future_override.start_date, midnight, tzinfo=tz)
            if future_override.open_time:
                return datetime.combine(future_date, future_override.open_time, tzinfo=tz)
            continue

        bh = get_business_hour_for_day(location, future_weekday)
        if not bh or bh.is_closed or not bh.open_time or not bh.close_time:
            continue
        return datetime.combine(future_date, bh.open_time, tzinfo=tz)

    return None

def refresh_location_schedule_state(location, now=None) -> Location:
    now = now or get_location_local_now(location)

    if not location.scheduling_enabled:
        location.expected_status = None
        location.expected_pathway_id = None
        location.next_transition_at = None
        location.last_schedule_evaluated_at = dj_timezone.now()
        location.last_schedule_error = ""
        location.save(update_fields=[
            "expected_status",
            "expected_pathway_id",
            "next_transition_at",
            "last_schedule_evaluated_at",
            "last_schedule_error",
        ])
        return location
    
    try:
        clear_expired_manual_override(location, now)

        is_open = is_location_effectively_open(location, now)
        desired_pathway = get_desired_pathway(location, now)
        override = get_active_manual_override(location, now)
        if override:
            next_transition = location.manual_override_until
        else:
            next_transition = get_next_transition_datetime(location, now)

        location.expected_status = "open" if is_open else "closed"
        location.expected_pathway_id = desired_pathway
        location.next_transition_at = next_transition
        location.last_schedule_evaluated_at = dj_timezone.now()
        location.last_schedule_error = ""

        location.save(update_fields=[
            "expected_status",
            "expected_pathway_id",
            "next_transition_at",
            "last_schedule_evaluated_at",
            "last_schedule_error",
        ])
    except Exception as e:
        location.last_schedule_evaluated_at = dj_timezone.now()
        location.last_schedule_error = str(e) 
        location.save(update_fields=[
            "last_schedule_evaluated_at",
            "last_schedule_error",
        ])

    return location

def process_due_location_schedules():
    now = dj_timezone.now()

    due_locations = Location.objects.filter(
        is_active=True,
        scheduling_enabled=True,
        next_transition_at__isnull=False,
        next_transition_at__lte=now
    )

    print(f"[Scheduler] Found {due_locations.count()} due locations", flush=True)

    for location in due_locations:
        print(f"[Scheduler] Processing {location.slug}", flush=True)
        refresh_location_schedule_state(location)
        location.refresh_from_db()
        print(f"[Scheduler] Syncing {location.slug} → {location.expected_status}", flush=True)
        ensure_location_bland_matches_expected(location)


def reconcile_location_bland_state():
    now = dj_timezone.now()

    locations = Location.objects.filter(
        is_active=True,
        scheduling_enabled=True,
    )

    print(f"[Reconcile] Found {locations.count()} scheduled locations", flush=True)

    for location in locations:
        try:
            print(f"[Reconcile] Checking {location.slug}", flush=True)

            refresh_location_schedule_state(location)
            location.refresh_from_db()

            if not location.expected_pathway_id:
                print(
                    f"[Reconcile] Skipping {location.slug}: no expected pathway id",
                    flush=True,
                )
                continue

            print(
                f"[Reconcile] Ensuring Bland matches {location.slug} → "
                f"{location.expected_status}",
                flush=True,
            )

            ensure_location_bland_matches_expected(location)

        except Exception as e:
            location.last_schedule_error = f"Reconciliation error: {e}"
            location.last_schedule_evaluated_at = dj_timezone.now()
            location.save(update_fields=[
                "last_schedule_error",
                "last_schedule_evaluated_at",
            ])

            print(
                f"[Reconcile] Error while checking {location.slug}: {e}",
                flush=True,
            )
    
