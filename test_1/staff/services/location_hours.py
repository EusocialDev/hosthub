from testendpoint.models import BusinessHour, Location
from datetime import datetime, timedelta
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
        location.manual_override_set_at = None
        location.manual_override_set_by = None
        location.save(update_fields=[
            "manual_override_status",
            "manual_override_until",
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
    weekday = now.weekday()

    current_time = now.time()


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

        # Yesterday spills into today
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
        future_weekday = future_day.weekday()
        bh = get_business_hour_for_day(location, future_weekday)

        if not bh or bh.is_closed or not bh.open_time or not bh.close_time:
            continue
        
        return datetime.combine(future_day.date(), bh.open_time, tzinfo=tz)
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
    
