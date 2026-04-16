from django.contrib.auth.models import User
from django.db import transaction

from staff.models import UserProfile 
from staff.services.utils import generate_unique_username
from testendpoint.models import UserAccess
from django.http import Http404, JsonResponse

@transaction.atomic
def create_worker(*, manager_access, display_name, role, locations, pin, is_active):
    username = generate_unique_username()

    user = User.objects.create_user(
        username=username,
        password=None,
        first_name = display_name,
        is_active=is_active,
        )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.display_name = display_name
    profile.save()

    access = UserAccess.objects.create(
        user=user,
        account=manager_access.account,
        role=role,
        is_active=is_active
    )
    if pin:
        access.set_pin(pin)
        access.save(update_fields=["pin_hash", "updated_at"])

    access.locations.set(locations)
    return user, access

@transaction.atomic
def update_worker(*, target_access, display_name, role, locations, pin, is_active):
    user = target_access.user

    user.first_name = display_name
    user.is_active = is_active
    user.save(update_fields=["first_name", "is_active"])

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.display_name = display_name
    profile.save()

    target_access.role = role
    target_access.is_active = is_active

    if pin:
        target_access.set_pin(pin)
    target_access.save()
    target_access.locations.set(locations)

    return user, target_access

    
    
