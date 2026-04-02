from testendpoint.models import Call

def get_visible_calls_queryset(user):
    access = getattr(user, "hosthub_access", None)

    if not access or not access.is_active:
        return Call.objects.none()
    
    return Call.objects.filter(
        account=access.account,
        location__in=access.locations.all(),
    ).select_related(
        "account",
        "location",
        "phone_number",
    )