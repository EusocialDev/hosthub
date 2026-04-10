from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import Http404

from .forms import WorkerForm
from staff.services.permissions import get_manager_access, can_manage_target
from staff.services.services import create_worker, update_worker

from testendpoint.models import UserAccess

@login_required
def worker_list_view(request):
    manager_access = get_manager_access(request.user)
    if not manager_access:
        raise Http404("You do not have permission to view this page.")
    
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
            .filter(account=manager_access.account, locations__in=manager_access.locations.all())
            .select_related("user", "account")
            .prefetch_related("locations")
            .distinct()
            .order_by("user__first_name", "user__username")
        )

    return render(request, "staff/worker_list.html", {
        "workers": workers,
        "manager_access": manager_access,
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





