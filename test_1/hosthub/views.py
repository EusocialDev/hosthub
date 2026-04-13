from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.urls import reverse
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from testendpoint.models import Call, PhoneNumber, CallSession
from testendpoint.views import _normalize_phone_number
from dateutil import parser as dateparser
import requests

from testendpoint.services.access import get_visible_calls_queryset

# ---- API Helper ----
def get_api_headers():
    """Return headers with authorization token from settings."""
    # Fetch the Bland API key from Django settings (default to empty string if not found)
    return {
        "authorization": getattr(settings, "BLAND_API_KEY", ""),
        "x-bland-org-id":getattr(settings,"BLAND_ORG_ID", "")
    }


# ---- Helpers for main function (queryset, filters, counts) ----

def landing_view(request):
    return render(request, "testendpoint/landing_hosthub.html")


# Order by newest first
def accessible_calls_for_user(user):
    access = getattr(user, "hosthub_access", None)

    if not access or not access.is_active:
        return Call.objects.none()
    
    queryset = Call.objects.filter(
        account=access.account,
        location__in=access.locations.all(),
    ).select_related(
        "account",
        "location",
        "phone_number",
    ).order_by("-created_at")
    return queryset

#Filter by status: resolved or needs aciton
def filter_by_status(qs, host_status):
    if host_status in ("needs_action", "resolved"):
        call_needs_action = qs.filter(host_status=host_status)
    else:
        return qs
    return call_needs_action

    

# Filter by call tags
def filter_by_category(qs, category):
    if category in ("reservation", "carryout", "leave_message", "private_events", "other"):
        qs = qs.filter(display_category=category)

    else:
        return qs
    return qs

def filter_by_date(qs, date_filter, today, custom_date=None):
    from datetime import datetime, time as dt_time

    if not date_filter:
        date_filter = 'today'    
    # Get today's date in local timezone
    local_now = timezone.localtime(timezone.now())
    local_today = local_now.date()
    
    def get_day_range_utc(target_date):
        """Get start and end of day in UTC for a given local date"""
        local_tz = timezone.get_current_timezone()
        
        # Create naive datetime at start of day
        local_start_naive = datetime.combine(target_date, dt_time.min)
        
        # Make it timezone-aware correctly using localize or make_aware
        local_start = timezone.make_aware(local_start_naive, local_tz)
        
        # End of day is start of next day
        local_end = local_start + timezone.timedelta(days=1)
        
        # Convert to UTC
        start_utc = local_start
        end_utc = local_end
        
        return start_utc, end_utc
    
    if date_filter == "today":
        start_utc, end_utc = get_day_range_utc(local_today)
        qs = qs.filter(created_at__gte=start_utc, created_at__lt=end_utc)
    elif date_filter == "yesterday":
        yesterday = local_today - timezone.timedelta(days=1)
        start_utc, end_utc = get_day_range_utc(yesterday)
        qs = qs.filter(created_at__gte=start_utc, created_at__lt=end_utc)
    elif date_filter == "last7":
        start_date = local_today - timezone.timedelta(days=7)
        start_utc, _ = get_day_range_utc(start_date)
        qs = qs.filter(created_at__gte=start_utc)
    elif date_filter == "custom" and custom_date:
        try:
            selected_date = datetime.strptime(custom_date, "%Y-%m-%d").date()
            start_utc, end_utc = get_day_range_utc(selected_date)
            qs = qs.filter(created_at__gte=start_utc, created_at__lt=end_utc)
        except (ValueError, TypeError):
            pass

    return qs


# ---- Main view, PURELY handles the orchestration, no logic. ----
@never_cache
@login_required
def hosthub_view(request):
    """
    HostHub Main index view
    Gets data from helpers at this function and passes to the template
    (this can later be implemented in different folders like 'services/call_filters.py'; 'selectors/call_selectors.py')
    """
    # Base Order for calls
    qs = accessible_calls_for_user(request.user)
    date_filter = request.GET.get("date")
    custom_date = request.GET.get("custom_date")
    # Get today's date in local timezone (will be used in filter_by_date, but filter_by_date uses localtime)
    today = timezone.localtime(timezone.now()).date()

    # Get calls with host status = needs_action Only
    host_status = request.GET.get("host_status", "needs_action")
    qs = filter_by_status(qs, host_status)

    # Get calls by category
    category = request.GET.get("category")
    qs = filter_by_category(qs, category)

    # Filter by date
    qs = filter_by_date(qs, date_filter, today, custom_date)

    page_loaded_at = timezone.now()

    # Getting user access to show location context or not (if multiple locations, we show location in the UI, if not, user should not se location name)
    access = getattr(request.user, "hosthub_access", None)

    has_multiple_locations = False
    if access and access.is_active:
        has_multiple_locations = access.locations.count() > 1

    show_manager_button = (
        access is not None
        and access.is_active
        and access.role in ["manager", "owner"]
    )



    # Computing counts for the headers (using base queryset with date filter only)
    base_qs = accessible_calls_for_user(request.user)
    base_qs = filter_by_date(base_qs, date_filter, today, custom_date)
    counts = {
        "open": base_qs.filter(host_status="needs_action").count(),
        "resolved": base_qs.filter(host_status="resolved").count(),
    }

    context = {
        'calls': qs,
        "active_category": category,
        "active_host_status": host_status,
        "active_date_filter": date_filter or 'today',
        "custom_date": custom_date,
        "counts": counts,
        "page_loaded_at": page_loaded_at,
        "has_multiple_locations": has_multiple_locations,
        "CARRYOUT_DASHBOARD_SLUG": settings.CARRYOUT_DASHBOARD_SLUG,
        "HOSTHUB_SSE_TOKEN": settings.HOSTHUB_SSE_TOKEN,
        "show_manager_button": show_manager_button,
    }

    return render(request, "hosthub/index.html", context)

def get_handled_by_display(self):
    if not self.handled_by_user:
        return None
    return self.handled_by_user.username

@login_required
@require_http_methods(["POST"])
def mark_call_handled(request, call_id):
    """
    AJAX endpoint to mark a call as handled (resolved) or unhandled (needs_action)
    """
    try: 
        call = get_object_or_404(accessible_calls_for_user(request.user), id=call_id)
        action = request.POST.get("action", "resolve")
        
        if action == "resolve":
            disposition = request.POST.get("disposition")
            if not disposition:
                return JsonResponse({
                    "success": False,
                    "error": "Disposition is required to resolve a call"
                }, status=400)

            call.mark_resolved(handled_by_user=request.user, disposition=disposition)

            status = "resolved"
        else:
            call.host_status = "needs_action"
            call.handled_at = None
            call.handled_by_user = None
            call.disposition = None
            call.save(update_fields=["host_status", "handled_at", "handled_by_user", "disposition"])
            status = "needs_action"
        
        return JsonResponse({
            "success": True,
            "status": status,
            "handled_by_display": call.get_handled_by_display() if call.handled_by_user else None,
            "disposition": call.disposition,
            "disposition_display": call.get_disposition_display() if call.disposition else None,
            "handled_at": call.handled_at.isoformat() if call.handled_at else None,
            "message": f"Call marked as {status}"
        })
    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=400)


@login_required
def check_new_calls(request):
    """
    Lightweight endpoint to detect if a newer call exists.
    Returns last call id and total count using the same filters as the HostHub view.
    """

    if request.method !="GET":
        return JsonResponse({"ok":False, "error":"Invalid request method"}, status=405)
    
    try:

        date_filter = request.GET.get("date")
        custom_date = request.GET.get("custom_date")
        host_status = request.GET.get("host_status", "needs_action")
        category = request.GET.get("category")
        today = timezone.localtime(timezone.now()).date()

        qs = accessible_calls_for_user(user=request.user)
        qs = filter_by_status(qs, host_status)
        if category:
            qs = filter_by_category(qs, category)
        qs = filter_by_date(qs, date_filter, today, custom_date)

        last_call = qs.first()
        return JsonResponse({
            "last_call_id": last_call.id if last_call else None,
            "total_count": qs.count(),
        })
    except Exception as e:
        return JsonResponse({
            "error": str(e)
        }, status=500)

@login_required
def new_calls_for_pill(request):
    """This is a lightweight endpoint to check if new calls have been ingested since the page was loaded.
        It returns a boolean value indicating wheter new calls exist.
    """  
    try:

        access = getattr(request.user, "hosthub_access", None)
        if not access or not access.is_active:
            return JsonResponse({
            "has_new":False,
            "message":"No access to calls"
        },status=200)

        page_loaded_at_raw =request.GET.get("page_loaded_at")
        page_loaded_at = dateparser.parse(page_loaded_at_raw) if page_loaded_at_raw else None

        if not page_loaded_at:
            return JsonResponse({
                "ok": False,
                "error": "Missing or invalid page_loaded_at",
        }, status=400)

         # Ensure page_loaded_at is timezone-aware


        if timezone.is_naive(page_loaded_at):
            page_loaded_at = timezone.make_aware(page_loaded_at, timezone.get_current_timezone())

        allowed_location_ids = access.locations.filter(
            is_active=True,
        ).values_list("id", flat=True)



        has_new = Call.objects.filter(
            account=access.account,
            location_id__in=allowed_location_ids,
            ingested_at__gt=page_loaded_at,
            ).exists()

        return JsonResponse({
            "ok":True,
            "has_new": has_new,
            "message": "New calls exist since page load" if has_new else "No new calls since page load"
        }, status=200)

    except Exception as e:
        return JsonResponse({
            "error": str(e)
        }, status=500)

@login_required
def bland_live_calls(request):
    """
    Lightweight endpoint for showing list of live calls from Bland and populating CallSession phone number
    """

    url = "https://api.bland.ai/v1/calls/active"

    headers = get_api_headers()

    access = getattr(request.user, "hosthub_access", None)
    if not access or not access.is_active:
        return JsonResponse({
            "ok": True,
            "count": 0,
            "calls": []
        }, status=200)
    
    allowed_locations_ids = access.locations.filter(is_active=True).values_list("id", flat=True)

    allowed_numbers = set(
        PhoneNumber.objects.filter(
            account=access.account,
            location_id__in=allowed_locations_ids,
            is_active=True,
        ).values_list("number", flat=True)
    )


    try:
        response = requests.get(url, headers=headers)
    except  requests.RequestException as e:
        return JsonResponse({
            "ok":False,
            "error":str(e),
            "count":0,
            "calls":[]
        }, status=502)
    
    if response.status_code != 200:
        return JsonResponse({
            "ok":False,
            "error":f"Bland api returned status {response.status_code}",
            "count":0,
            "calls": []
        }, status=response.status_code)
    
    payload = response.json() or {}
    data = payload.get("data") or []

    calls = []

    for c in data:
        call_id = c.get("call_id")
        normalized_to = _normalize_phone_number(c.get("to"))
        normalized_from = _normalize_phone_number(c.get("from"))
        started_at = c.get("started_at")
        status_value = (c.get("status") or "").lower()
        if not normalized_to:
            continue
        if normalized_to not in allowed_numbers:
            continue

        # sync into callsession
        CallSession.objects.update_or_create(
            call_id=call_id,
            defaults={
                "to_number": normalized_to,
                "from_number": normalized_from,
                "status": status_value if status_value in CallSession.Status.values else CallSession.Status.ACTIVE,
                "started_at": dateparser.parse(started_at) if started_at else None,
                "last_event_at": timezone.now(),
            }
        )

        calls.append({
            "call_id":c.get("call_id"),
            "from":c.get("from"),
            "to":normalized_to,
            "started_at":c.get("started_at"),
            "status":c.get("status"),
        })

    return JsonResponse({"ok":True, "count":len(calls), "calls":calls}, status=200)

@csrf_exempt
def bland_transfer_call(request):
    call_id = request.POST.get("call_id")

    if not call_id:
        return JsonResponse({"ok": False, "error": "Missing call_id"}, status=400)

    url = "https://api.bland.ai/v1/calls/active/transfer"

    payload = {
        "call_id": call_id,
        "transfer_number": "+12487737976",  # <-- ALWAYS THIS NUMBER
    }

    try:
        r = requests.post(url, json=payload, headers=get_api_headers())
    except requests.RequestException as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=502)

    if r.status_code != 200:
        return JsonResponse({
            "ok": False,
            "error": "Bland transfer failed",
            "details": r.text,
        }, status=r.status_code)

    return JsonResponse({"ok": True})
