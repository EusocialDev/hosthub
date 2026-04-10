from testendpoint.models import UserAccess

def get_manager_access(user):
    access = getattr(user, "hosthub_access", None)

    if not access or not access.is_active:
        return None
    
    if access.role not in {"owner", "manager"}:
        return None
    
    return access

def can_manage_target(manager_access, target_access):
    if manager_access.account_id != target_access.account_id:
        return False
    
    if manager_access.role == "owner":
        return True
    
    if manager_access.role == "manager":
        if target_access.role !="host":
            return False
        
        manager_location_ids = set(manager_access.locations.values_list("id", flat=True))
        target_location_ids = set(target_access.locations.values_list("id", flat=True))
        return bool(manager_location_ids & target_location_ids)

    return False
