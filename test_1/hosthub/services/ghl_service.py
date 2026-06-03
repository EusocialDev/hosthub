import requests
from django.conf import settings


def send_reservation_confirmation(payload):
    webhook_url = getattr(settings, 'GHL_RESERVATION_CONFIRMATION_WEBHOOK_URL', None)

    if not webhook_url:
        return False, "GHL reservation confirmation webhook URL is not configured."
    
    try:
        response = requests.post(
            webhook_url, 
            json=payload, 
            timeout=10
        )

        if response.status_code < 200 or response.status_code >= 300:
            return False, f"GHL API returned status code {response.status_code}"
        
        return True, None
    except requests.RequestException as e:
        return False, f"Error sending reservation confirmation to GHL: {str(e)}"
        
