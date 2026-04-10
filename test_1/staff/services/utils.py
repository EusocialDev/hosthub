import secrets
import string
from django.contrib.auth.models import User

def generate_unique_username(prefix: str = "worker") -> str:
    alphabet = string.ascii_lowercase + string.digits

    while True:
        suffix = ''.join(secrets.choice(alphabet) for _ in range(8))
        username = f"{prefix}_{suffix}"
        if not User.objects.filter(username=username).exists():
            return username