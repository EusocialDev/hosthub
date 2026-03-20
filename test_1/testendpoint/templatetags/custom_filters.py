from django import template
from datetime import datetime

register = template.Library()

@register.filter
def unique_names(tags):
    """
    Accepts:
      - list[dict] like [{"name": "Carryout"}, ...]
      - list[str]  like ["Carryout", "Reservation"]
    Returns a list of unique display names in original order.
    """
    if not tags:
        return []

    seen = set()
    out = []

    for t in tags:
        # dict form
        if isinstance(t, dict):
            name = t.get("name") or t.get("tag") or ""
        # string form
        elif isinstance(t, str):
            name = t
        else:
            continue

        name = str(name).strip()
        if not name:
            continue

        key = name.lower()
        if key in seen:
            continue

        seen.add(key)
        out.append(name)

    return out

@register.filter
def get_item(dictionary, key):
    if isinstance(dictionary, dict):
        return dictionary.get(key, "")
    return ""


@register.filter
def phone_format(value):
    """
    Format a phone number like +17402088961 -> (740) 208-8961
    Assumes US numbers in E.164 format.
    """
    if not value:
        return ""

    # Remove + if present
    digits = str(value).replace("+", "")

    # If US number (11 digits, starting with 1)
    if len(digits) == 11 and digits.startswith("1"):
        area = digits[1:4]
        prefix = digits[4:7]
        line = digits[7:]
        return f"({area}) {prefix}-{line}"

    # If already 10 digits
    if len(digits) == 10:
        area = digits[0:3]
        prefix = digits[3:6]
        line = digits[6:]
        return f"({area}) {prefix}-{line}"

    # Fallback (just return as-is)
    return value

@register.filter
def datetime_format(value, fmt="%b %d, %Y %I:%M %p"):
    """
    Format an ISO 8601 datetime string into something human-friendly.
    Default: 'Aug 21, 2025 12:05 AM'
    """
    if not value:
        return ""

    try:
        # Parse the ISO string
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime(fmt)
    except Exception:
        return value
    
@register.filter
def date_format(value, fmt="%b %d, %Y"):
    """
    Format an ISO 8601 datetime string into something human-friendly.
    Default: 'Aug 21, 2025 12:05 AM'
    """
    if not value:
        return ""

    try:
        # Parse the ISO string
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime(fmt)
    except Exception:
        return value