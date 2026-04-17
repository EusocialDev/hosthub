from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone as dj_timezone

from .forms import WorkerForm
from staff.services.permissions import get_manager_access, can_manage_target
from staff.services.services import create_worker, update_worker

from testendpoint.models import UserAccess

from testendpoint.views import get_api_headers

from testendpoint.models import PhoneNumber

from staff.services.location_hours import get_location_local_now, get_next_transition_datetime, refresh_location_schedule_state


import requests
import json

@login_required
def worker_list_view(request):
    accessible_locations = get_manager_access(request.user)
    manager_access = get_manager_access(request.user)
    if not manager_access:
        raise Http404("You do not have permission to view this page.")
    
    accessible_locations = manager_access.locations.filter(is_active=True).order_by("name")
    location_id = request.session.get('active_location_id')

    location = manager_access.locations.filter(
        id = location_id,
        is_active=True
    ).first()

    is_store_open = location.is_store_open if location else False
    
    if manager_access.role == "owner":
        workers = (
            UserAccess.objects
            .filter(account=manager_access.account)
            .select_related("user", "account")
            .prefetch_related("locations")
            .order_by("user__first_name", "user__username")
        )

    else:
        workers = (
            UserAccess.objects
            .filter(account=manager_access.account, locations__in=manager_access.locations.all(), role='host')
            .select_related("user", "account")
            .prefetch_related("locations")
            .distinct()
            .order_by("user__first_name", "user__username")
        )

    return render(request, "staff/worker_list.html", {
        "workers": workers,
        "manager_access": manager_access,
        "accessible_locations": accessible_locations,
        "location": location,
        "is_store_open": is_store_open,
        })

@login_required
def worker_create_view(request):
    manager_access = get_manager_access(request.user)
    if not manager_access:
        raise Http404("You do not have permission to view this page.")
    
    if request.method == "POST":
        form = WorkerForm(request.POST, manager_access=manager_access, editing=False)
        if form.is_valid():
            create_worker(
                manager_access=manager_access,
                display_name=form.cleaned_data["display_name"],
                role=form.cleaned_data["role"],
                locations=form.cleaned_data["locations"],
                pin=form.cleaned_data["pin"],
                is_active=form.cleaned_data["is_active"],
            )
            messages.success(request, "Worker created successfully.")
            return redirect("staff:worker_list")
    else:
        form = WorkerForm(manager_access=manager_access, editing=False)
    return render(request, "staff/worker_form.html", {
        "form": form,
        "page_title": "Create Worker",
        "submit_label": "Create Worker",
    })


@login_required
def worker_edit_view(request, access_id):
    manager_access = get_manager_access(request.user)
    if not manager_access:
        raise Http404("You do not have access to this page.")

    target_access = get_object_or_404(
        UserAccess.objects.select_related("user", "account").prefetch_related("locations"),
        id=access_id,
    )

    if not can_manage_target(manager_access, target_access):
        raise Http404("You do not have access to this worker.")

    initial = {
        "display_name": getattr(target_access.user.profile, "display_name", target_access.user.first_name or ""),
        "role": target_access.role,
        "locations": target_access.locations.all(),
        "is_active": target_access.is_active,
    }

    if request.method == "POST":
        form = WorkerForm(
            request.POST,
            manager_access=manager_access,
            editing=True,
        )
        if form.is_valid():
            update_worker(
                target_access=target_access,
                display_name=form.cleaned_data["display_name"],
                role=form.cleaned_data["role"],
                locations=form.cleaned_data["locations"],
                pin=form.cleaned_data["pin"],
                is_active=form.cleaned_data["is_active"],
            )
            messages.success(request, "Worker updated successfully.")
            return redirect("staff:worker_list")
    else:
        form = WorkerForm(
            initial=initial,
            manager_access=manager_access,
            editing=True,
        )

    return render(request, "staff/worker_form.html", {
        "form": form,
        "page_title": "Edit worker",
        "submit_label": "Save changes",
        "target_access": target_access,
    })


@login_required
@require_POST
def set_store_status(request):
    manager_access = get_manager_access(request.user)

    if not manager_access:
        return JsonResponse({"error": "You do not have permission to perform this action."}, status=403)
    
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)
    
    status_value = payload.get("status")
    location_slug = payload.get("location_slug")

    if status_value not in ["open", "closed"]:
        return JsonResponse({"error": "Invalid status value."}, status=400)
    
    if not location_slug:
        return JsonResponse({"error": "Location slug is required."}, status=400)
    
    accessible_locations = manager_access.locations.filter(
        account=manager_access.account,
        is_active=True,
    )
    
    location = accessible_locations.filter(slug=location_slug).first()
    if not location:
        return JsonResponse({"error": "Location not found or you do not have access to it."}, status=404)

    now = get_location_local_now(location)
    override_until = get_next_transition_datetime(location, now)
    if override_until is None:
        return JsonResponse({"error": "Unable to determine when the override should end."}, status=400)
    
    phone_number = PhoneNumber.objects.filter(
        account=manager_access.account, 
        location=location,
        is_active=True,
    ).first()

    if not phone_number:
        return JsonResponse({"error": "No active phone number found for this location."}, status=404)

    location.manual_override_status = status_value
    location.manual_override_until = override_until
    location.manual_override_set_at = dj_timezone.now()
    location.manual_override_set_by = request.user
    location.save(update_fields=[
        "manual_override_status",
        "manual_override_until",
        "manual_override_set_at",
        "manual_override_set_by",
    ])

    refresh_location_schedule_state(location, now)
    location.refresh_from_db()
    
    if status_value == "open":
        pathway_id = location.bland_pathway_id_open
    else:
        pathway_id = location.bland_pathway_id_closed
    if not pathway_id:
        return JsonResponse({"error": "Location does not have an expected pathway set."}, status=400)
    
    display_override_until = dj_timezone.localtime(override_until).strftime("%H:%M")

    headers = get_api_headers()
    url = f'https://api.bland.ai/v1/inbound/{phone_number.number}'

    try:
        response = requests.post(url, headers=headers, json={
            "pathway_id": pathway_id,
        }, timeout=15,)

    except requests.RequestException as e:
        return JsonResponse(
            {"error": "No active phone number found for this location."},
            status=404
        )
    
    if not response.ok:
        return JsonResponse(
            {
                "error": "Bland API rejected the request.",
                "details": response.text,
            },
            status=502
        )

    return JsonResponse({
        "message": f"{location.name} was set to {status_value} until {display_override_until}.",
        "location": location.slug,
        "status": status_value,
    })


