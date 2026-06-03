from django.utils import timezone
from .ghl_service import send_reservation_confirmation

def confirm_reservation_and_notify(call ,user):
    if call.display_category != 'reservation':
        raise ValueError("This call is not a reservation.")
    
    if call.host_status == 'resolved':
        raise ValueError("This call has already been resolved.")
    
    if not call.from_number:
        raise ValueError("Call does not have a valid phone number.")
    
    variables = call.variables or {}

    reservation_date = variables.get('date')
    reservation_time = variables.get('time')
    reservation_guests = variables.get('guest')


    # Send reservation confirmation to GHL
    payload = {
        "call_id": call.id,
        "guest_name": call.user_name or 'Guest',
        "guest_phone": call.from_number,
        "reservation_date": reservation_date,
        "reservation_time": reservation_time,
        "reservation_guests": reservation_guests,
        "restaurant_name": call.location.name if call.location else 'Restaurant',
    }
    success, error = send_reservation_confirmation(payload)

    if not success:
        return False, f"Failed to send reservation confirmation: {error}"
    
    call.mark_resolved(
        handled_by_user=user,
        disposition='reservation_confirmed',
    )

    return True, None