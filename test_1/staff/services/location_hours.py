from testendpoint.models import BusinessHour, Location
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.utils import timezone as dj_timezone


def get_location_local_now(location) -> datetime:
    try:
        tz = ZoneInfo(location.timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return datetime.now(tz)

def get_business_hour_for_day(location, weekday) -> BusinessHour | None:
    return location.business_hours.filter(day_of_week=weekday).first()

def is_location_open_now(location, now=None) -> bool:
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

    if is_location_open_now(location, now):
        return open_pathway_id
    
    else:
        return closed_pathway_id
    
def get_next_transition_datetime(location, now=None) -> datetime | None:
    now = now or get_location_local_now(location)

    for offset in range(0, 8):
        day_dt = now + timedelta(days=offset)
        weekday = day_dt.weekday()
        bh = get_business_hour_for_day(location, weekday)

        if not bh or bh.is_closed or not bh.open_time or not bh.close_time:
            continue

        open_dt = datetime.combine(day_dt.date(), bh.open_time, tzinfo=now.tzinfo)

        if bh.open_time < bh.close_time:
            close_dt = datetime.combine(day_dt.date(), bh.close_time, tzinfo=now.tzinfo)
        else:
            close_dt = datetime.combine(day_dt.date(), bh.close_time, tzinfo=now.tzinfo) + timedelta(days=1)

        candidates = [dt for dt in (open_dt, close_dt) if dt > now]
        if candidates:
            return min(candidates)
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
            "updated_at",
        ])
        return location
    
    try:
        is_open = is_location_open_now(location, now)
        desired_pathway = get_desired_pathway(location, now)
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
            "updated_at",
        ])
    except Exception as e:
        location.last_schedule_evaluated_at = dj_timezone.now()
        location.last_schedule_error = str(e) 
        location.save(update_fields=[
            "last_schedule_evaluated_at",
            "last_schedule_error",
            "updated_at",
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

    for location in due_locations:
        refresh_location_schedule_state(location, now)