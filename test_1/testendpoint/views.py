from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseNotAllowed
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from dateutil import parser as dateparser
from .models import Call, PhoneNumber, Account, UserAccess, Location
from testendpoint.services.bland_ingest import ingest_bland_webhook_event
from django.views.decorators.cache import never_cache
from django.http import Http404
from testendpoint.utils.phone import _normalize_phone_number
import requests
import json
from testendpoint.services.account_preauth import *
from testendpoint.forms import AccountLoginForm





# Utility function to get API headers
def get_api_headers():
    """Return headers with authorization token from settings."""
    # Fetch the Bland API key from Django settings (default to empty string if not found)
    return {
        "authorization": getattr(settings, "BLAND_API_KEY", ""),
    }




def get_call_stats_from_db():
    """
    Return (completed_count, abandoned_count, in_progress_count)
    computed purely from the database.
    """

    abandoned_q = Q(duration_seconds__gt=0, duration_seconds__lt=20)

    completed_q = (
        Q(queue_status__in=["complete", "completed"])
        & ~abandoned_q
    )

    in_progress_q = Q(queue_status="started")

    completed_count = Call.objects.filter(completed_q).count()
    abandoned_count = Call.objects.filter(abandoned_q).count()
    in_progress_count = Call.objects.filter(in_progress_q).count()

    return completed_count, abandoned_count, in_progress_count

@csrf_exempt
def bland_calls_webhook(request, token:str):

    # Only allow POST requests
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"]) 
    
    #IMPORTANT!
    """"This needs to be update, Bland does offer a Auth token now"""
    # Secret Token Validation (URL based auth) Bland does not offer this security set up
    expected = getattr(settings, "BLAND_WEBHOOK_TOKEN", "")
    if not expected or token != expected:
        return JsonResponse ({"ok": False}, status=403)
    
    # Content-Type sanity check, super simple just to be careful
    content_type = (request.headers.get("Content-Type") or "").lower()
    if "application/json" not in content_type:
        return JsonResponse({"ok": False, "error":"Expected application/json"}, status=415)
    
    # Parse Json body
    try:
        raw_body = request.body
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok":False, "error": "Invalid JSON"}, status=400)
    
    try:
        if "message" in payload and payload.get("category") == "call":
            ingest_bland_webhook_event(payload)
        else:
            upsert_call_from_bland_json(payload)

    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=500)
    
    return JsonResponse({"ok":True}, status=200)



# --------- Django Views ---------

def live_transcript_view(request, call_id):
    """API endpoint to fetch live transcripts for in-progress calls."""
    headers = get_api_headers()
    url = f"https://api.bland.ai/v1/calls/{call_id}"

    try:
        # Fetch call details
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        call_data = response.json()
        
        # Check if call is in progress
        status = call_data.get("status", "")
        queue_status = call_data.get("queue_status", "")
        
        # Return transcripts and status info
        return JsonResponse({
            "call_id": call_id,
            "status": status,
            "queue_status": queue_status,
            "transcripts": call_data.get("transcripts", []),
            "full_transcript": call_data.get("concatenated_transcript", ""),
            "is_live": status in ["started", "queued", "allocated"] or queue_status == "started"
        })
        
    except requests.RequestException as e:
        return JsonResponse({"error": f"Error fetching call data: {e}"}, status=500)


def live_calls_data_view(request):
    """API endpoint to fetch live calls data for AJAX updates (DB is source of truth)."""
    try:
        # Pull recent calls from DB (limit to keep payload small)
        calls_qs = Call.objects.all().order_by("-started_at")[:200]

        completed_count, abandoned_count, in_progress_count = get_call_stats_from_db()

        # Convert to JSON-safe dicts (include only what the JS needs)
        calls = []
        for c in calls_qs:
            calls.append({
                "call_id": c.bland_call_id,          # JS expects call.call_id in the URL
                "from": c.from_number,               # JS expects call.from
                "to": c.to_number,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "started_at": c.started_at.isoformat() if c.started_at else None,
                "end_at": c.ended_at.isoformat() if c.ended_at else None,
                "queue_status": c.queue_status,
                "status": c.bland_status,
                "corrected_duration": c.duration_seconds,  # JS checks corrected_duration
                "summary": c.summary,
                "concatenated_transcript": c.full_transcript,
                "pathway_tags": c.pathway_tags or [],
                "variables": c.variables or {},
                "metadata": c.metadata or {},
                # Optional: send this so JS doesn’t recompute
                "computed_status": c.computed_status if hasattr(c, "computed_status") else None,
            })

        return JsonResponse({
            "calls": calls,
            "completed_count": completed_count,
            "abandoned_count": abandoned_count,
            "in_progress_count": in_progress_count,
            "total_calls": len(calls),
        })

    except Exception as e:
        return JsonResponse({"error": f"Error fetching calls data: {e}"}, status=500)
    

def account_login_view(request):
    preauth_account = get_preauth_account(request)

    if preauth_account:
        preauth_locations = get_preauth_locations(request, account=preauth_account)
        preauth_location_count = preauth_locations.count()

        if preauth_location_count > 1:
            return redirect(
                "testendpoint:location_picker",
                account_slug=preauth_account.slug,
            )
        elif preauth_location_count == 1:
            location = preauth_locations.first()
            set_active_location(request, account=preauth_account, location=location)
            return redirect(
                "testendpoint:worker_login",
                account_slug=preauth_account.slug,
                location_slug=location.slug
            )
        
        else:
            clear_account_preauth(request)
    if request.method == 'POST':
        form = AccountLoginForm(request.POST)

        if form.is_valid():
            username = form.cleaned_data["username"].strip()
            password = form.cleaned_data['password']

            account = Account.objects.filter(
                login_username=username,
                is_active = True,
            ).first()

            if not account or not account.check_login_password(password):
                messages.error(request, "Invalid account username or password.")
            else:
                locations = account.locations.filter(is_active=True)
                location_count = locations.count()

                if location_count == 0:
                    messages.error(request, "No Active locations are avaiable for this account.")

                else:
                    set_account_preauth(
                        request,
                        account=account,
                        locations=locations,
                    )

                    if location_count > 1:
                        return redirect(
                            "testendpoint:location_picker",
                            account_slug=account.slug,
                        )
                    
                    location = locations.first()
                    set_active_location(
                        request,
                        account=account,
                        location=location,
                    )

                    return redirect(
                        "testendpoint:location_picker",
                        account_slug=account.slug
                    )
    else:
        form = AccountLoginForm()

    return render(request, "testendpoint/account_login.html", {
        "form": form,
    })
    

    
def location_picker_view(request, account_slug):
    account = get_object_or_404(Account, slug=account_slug, is_active=True)

    if not has_account_preauth(request, account=account):
        return redirect("testendpoint:account_login")
    
    locations = get_preauth_locations(request, account=account)

    if not locations.exists():
        raise Http404("No active locations found for this account.")
    
    if locations.count() == 1:
        location = locations.first()
        set_active_location(request, account=account, location=location)

        return redirect(
            "testendpoint:location_login",
            account_slug=account.slug,
            location_slug = location.slug,
        )
    return render(request, "testendpoint/location_picker.html", {
        "account": account,
        "locations": locations,
    })




# Authentication Views
@never_cache
def worker_login(request, account_slug, location_slug):
    account = get_object_or_404(Account, slug=account_slug, is_active=True)

    location = get_preauth_location(
        request,
        account=account,
        location_slug=location_slug
    )

    if not location:
        return redirect("testendpoint:account_login")
    
    
    set_active_location(request, account=account, location=location)

    accesses = UserAccess.objects.filter(
        account=account,
        locations=location,
        is_active=True,
        user__is_active=True,
    ).select_related("user")

    employees = [ua.user for ua in accesses]

    location_count = Location.objects.filter(
        account=account,
        is_active=True,
    ).count()

    
    if request.method == "POST":
        user_id = request.POST.get("user_id", "")
        pin = request.POST.get("pin", "").strip()

        access = accesses.filter(user__id=user_id).first()
        if not access:
            messages.error(request, "Invalid user or PIN.")

        elif not access.check_pin(pin):
            messages.error(request, "Invalid PIN.")

        else:
            preauth_account_id = request.session.get("preauth_account_id")
            preauth_location_ids = request.session.get("preauth_location_ids", [])
            preauth_started_at = request.session.get("preauth_started_at")


            login(request, access.user)

            restore_account_preauth(
                request,
                preauth_account_id=preauth_account_id or account.id,
                preauth_location_ids=preauth_location_ids or [location.id],
                preauth_started_at=preauth_started_at,
            )

            set_active_location(request, account=account, location=location)

            return redirect("hosthub:hosthub_dashboard")
        
    return render(request, "testendpoint/login.html", {
        "account": account, 
        "location": location,
        "employees": employees,
        "has_multiple_locations": location_count > 1,
    })


@never_cache
def worker_logout_view(request):
    preauth_account_id = request.session.get("preauth_account_id")
    preauth_location_ids = request.session.get("preauth_location_ids", [])
    preauth_started_at = request.session.get("preauth_started_at")

    active_account_id = request.session.get("active_account_id")
    active_location_id = request.session.get("active_location_id")

    account_slug = None
    location_slug = None

    if active_account_id and active_location_id:
        account = Account.objects.filter(
            id=active_account_id,
            is_active=True,
        ).first()

        location = None
        if account:
            location = Location.objects.filter(
                id=active_location_id,
                account=account,
                is_active=True,
            ).first()

        if account and location:
            account_slug = account.slug
            location_slug = location.slug

    logout(request)

    restore_account_preauth(
        request,
        preauth_account_id=preauth_account_id,
        preauth_location_ids=preauth_location_ids,
        preauth_started_at=preauth_started_at,
    )

    restore_active_location(
        request,
        active_account_id=active_account_id,
        active_location_id=active_location_id,
    )

    if account_slug and location_slug:
        return redirect(
            "testendpoint:location_login",
            account_slug=account_slug,
            location_slug=location_slug,
        )

    if account_slug:
        return redirect(
            "testendpoint:location_picker",
            account_slug=account_slug,
        )

    return redirect("testendpoint:account_login")

@never_cache
def account_logout_view(request):
    logout(request)
    return redirect("testendpoint:account_login")



def get_display_category_from_tags(pathway_tags):
    """
    Map Bland tags for display later on at HostHub filters.
    """
    if not pathway_tags:
        return "other"
    
    # Normalize to lower-case just in case
    normalized = []

    for t in pathway_tags:
        # Case 1, dictionary (Blad default for call lookup)
        if isinstance(t, dict):
            name = t.get("name", "")
        # Case 2: string tag (Bland Default for Post Call Webhook)
        elif isinstance(t, str):
            name = t

        else:
            continue

        normalized.append(name.lower())


    if any("reservation" in t for t in normalized):
        return "reservation"
    if any("carryout" in t for t in normalized):
        return "carryout"
    if any("leave" in t for t in normalized):
        return "leave_message"
    if any('private' in t for t in normalized):
        return "private_events"
    return "other"


def upsert_call_from_bland_json(call: dict):
    """
    Take a single Bland call JSON object (dict) and
    create/update the corresponding Call row in the database 
    designed to be idempotent for webhook retries
    """

    if not isinstance(call, dict) or not call:
        return None
    
    bland_call_id = call.get("call_id") or call.get('c_id')
    if not bland_call_id:
        return None
    
    # getting call duration in seconds
    def _get_duration_seconds(c):
        cd = c.get("corrected_duration")
        if isinstance(cd, (int, float)):
            try:
                return int(cd)
            except Exception:
                pass
        if isinstance(cd, str):
            try:
                return int(float(cd))
            except Exception:
                pass

        try:
            started = c.get("started_at")
            ended = c.get("end_at") or c.get("ended_at")
            if started and ended:
                dt_start = dateparser.parse(started)
                dt_end = dateparser.parse(ended)
                return max(0, int((dt_end - dt_start).total_seconds()))
        except Exception:
            pass

        #Fallback: call_length in minutes
        cl = c.get("call_length")
        try: 
            if isinstance(cl, (int, float)):
                return int(cl * 60)
            return int(float(cl) * 60)
        except Exception:
            return 0
        
    duration_seconds = _get_duration_seconds(call)

    if duration_seconds < 16:
        return None

    # Parse timestamps
    def _parse_dt(value):
        if not value:
            return None
        try:
            return dateparser.parse(value)
        except Exception:
            return None
        
    created_at = _parse_dt(call.get("created_at"))
    started_at = _parse_dt(call.get("started_at"))
    ended_at = _parse_dt(call.get("end_at") or call.get("ended_at"))


    # Full List of Pathway Tags each called hit
    pathway_tags = call.get("pathway_tags") or []
    if not isinstance(pathway_tags, list):
        pathway_tags = []
    
    display_category = get_display_category_from_tags(pathway_tags)
    variables = call.get("variables") or {}
    user_name = variables.get("user_name")

    # Resolve tenant context from business phone number
    raw_to_number = call.get("to")
    normalized_to_number = _normalize_phone_number(raw_to_number)

    matched_phone = None
    matched_account = None
    matched_location = None

    if normalized_to_number:
        matched_phone = PhoneNumber.objects.filter(
            number=normalized_to_number,
            is_active=True,
            ).select_related("account", "location").first()
        
    if matched_phone:
        matched_account = matched_phone.account
        matched_location = matched_phone.location
    else:
        raise ValueError("Could not match call to an active phone number in the database")

    # Now we "append" everything to the database
    
    defaults={
        "account": matched_account,
        "location": matched_location,
        "phone_number": matched_phone,
        "from_number": call.get("from"),
        "to_number": call.get("to"),
        "user_name": user_name,
        "created_at": created_at,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": duration_seconds,
        "queue_status": call.get("queue_status"),
        "bland_status": call.get("status"),
        "completed": bool(call.get("completed", False)),
        "summary": call.get("summary"),
        "full_transcript": call.get("concatenated_transcript"),
        "transcripts": call.get("transcripts", []),
        "pathway_tags": pathway_tags,
        "variables": call.get("variables"),
        "metadata": call.get("metadata"),
        "display_category": display_category,
    }

    with transaction.atomic():
        obj, _created = Call.objects.update_or_create(
            bland_call_id=bland_call_id,
            defaults=defaults
        )
    if _created and obj.ingested_at is None:
        obj.ingested_at = timezone.now()
        obj.save(update_fields=["ingested_at"])

    return obj


@login_required
def get_final_transcripts(request, call_id):
    access = getattr(request.user, "hosthub_access", None)
    if not access or not access.is_active:
        raise Http404("Call not Found")
    
    allowed_location_ids = access.locations.filter(
        is_active=True,
    ).values_list("id", flat=True)

    call = Call.objects.filter(
        id=call_id,
        account=access.account,
        location_id__in=allowed_location_ids,
        ).first()
    if not call:
        raise Http404("Call not found or access denied")
    
    return JsonResponse({
        "ok": True,
        "call_id":call_id,
        "transcripts": call.transcripts or [],
    })


def ensure_location_bland_matches_expected(location):
    expected_pathway_id = location.expected_pathway_id

    if not expected_pathway_id:
        location.last_schedule_error = "No expected pathway set"
        location.save(update_fields=["last_schedule_error"])
        return

    current_pathway_id, error = get_current_bland_pathway_for_location(location)

    if error:
        location.last_schedule_error = error
        location.save(update_fields=["last_schedule_error"])
        return

    # Already aligned
    if current_pathway_id == expected_pathway_id:
        location.last_synced_status = location.expected_status
        location.last_synced_pathway_id = expected_pathway_id
        location.last_pathway_synced_at = timezone.now()

        location.save(update_fields=[
            "last_synced_status",
            "last_synced_pathway_id",
            "last_pathway_synced_at",
        ])

        return

    phone_number = location.phone_numbers.filter(is_active=True).first()

    if not phone_number:
        location.last_schedule_error = "No active phone number found for location"
        location.save(update_fields=["last_schedule_error"])
        return
    
    headers = get_api_headers()
    url = f"https://api.bland.ai/v1/inbound/{phone_number.number}"

    try:
        response = requests.post(
            url,
            headers=headers,
            json={
                "pathway_id": expected_pathway_id,
            },
            timeout=15,
        )

    except requests.RequestException as e:
        location.last_schedule_error = f"Error syncing pathway_id to Bland: {e}"
        location.save(update_fields=["last_schedule_error"])
        return
    
    if not response.ok:
        location.last_schedule_error = f"Bland API rejected the request with status {response.status_code}: {response.text}"
        location.save(update_fields=["last_schedule_error"])
        return
    
    location.last_schedule_error = ""
    location.last_synced_status = location.expected_status
    location.last_synced_pathway_id = expected_pathway_id
    location.last_pathway_synced_at = timezone.now()

    location.save(update_fields=[
        "last_schedule_error",
        "last_synced_status",
        "last_synced_pathway_id",
        "last_pathway_synced_at",
    ])

def get_current_bland_pathway_for_location(location) -> str:
    phone_number = location.phone_numbers.filter(is_active=True).first()

    if not phone_number:
        return None, 'no active phone number'
    
    headers = get_api_headers()

    url = f"https://api.bland.ai/v1/inbound/{phone_number.number}"

    try:
        response = requests.get(url, headers=headers, timeout=15)
    
    except requests.RequestException as e:
        return None, f"Error fetching inbound config from Bland: {e}"

    if not response.ok:
        return None, (
            f"Bland rejected inbound fetch request "
            f"({response.status_code}): {response.text}"
        )

    data = response.json()

    current_pathway_id = data.get("pathway_id")

    if not current_pathway_id:
        return None, "Inbound config returned no pathway_id"

    return current_pathway_id, None