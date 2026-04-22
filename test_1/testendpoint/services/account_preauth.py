from django.utils import timezone
from testendpoint.models import Account, Location

PREAUTH_ACCOUNT_ID = "preauth_account_id"
PREAUTH_LOCATION_IDS = "preauth_location_ids"
PREAUTH_STARTED_AT = "preauth_started_at"
ACTIVE_ACCOUNT_ID = "active_account_id"
ACTIVE_LOCATION_ID = "active_location_id"

def set_account_preauth(request, *, account, locations):
    request.session[PREAUTH_ACCOUNT_ID] = account.id
    request.session[PREAUTH_LOCATION_IDS] = list(
        locations.values_list("id", flat=True)
        if hasattr(locations, "values_list")
        else [location.id for location in locations]
    )
    request.session[PREAUTH_STARTED_AT] =timezone.now().isoformat()

def clear_account_preauth(request):
    request.session.pop(PREAUTH_ACCOUNT_ID, None)
    request.session.pop(PREAUTH_LOCATION_IDS, None)
    request.session.pop(PREAUTH_STARTED_AT, None)

def set_active_location(request, *, account, location):
    request.session[ACTIVE_ACCOUNT_ID] = account.id
    request.session[ACTIVE_LOCATION_ID] = location.id

def get_preauth_account(request):
    account_id = request.session.get(PREAUTH_ACCOUNT_ID)
    if not account_id:
        return None
    
    return Account.objects.filter(id=account_id, is_active=True).first()
    
def get_preauth_location_ids(request):
    return request.session.get(PREAUTH_LOCATION_IDS, [])
    

def has_account_preauth(request, *, account):
    return request.session.get(PREAUTH_ACCOUNT_ID) == account.id

def get_preauth_locations(request, *, account):
    location_ids = get_preauth_location_ids(request)

    return account.locations.filter(
        id__in = location_ids,
        is_active=True,
    ).order_by("name")

def get_preauth_location(request, *, account, location_slug):
    if not has_account_preauth(request, account=account):
        return None
    
    return get_preauth_locations(request, account=account).filter(
        slug=location_slug,
    ).first()