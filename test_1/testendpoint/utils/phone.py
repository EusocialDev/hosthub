import re
def _normalize_phone_number(value): 
    """ 
    Basic canonicalization to US phone numbers for consistent comparison.
     It simply strips non-digit characters and ensures the number starts with +1 for US numbers.
    """

    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    digits = digits if digits.startswith("1") else "1" + digits  # Ensure it starts with USA country code
    return f"+{digits}" or None
