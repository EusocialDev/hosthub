"""Utilities for respecting SMS provider body limits."""


DEFAULT_SMS_BODY_LIMIT = 1600


def split_sms_body(text: str, *, max_chars: int = DEFAULT_SMS_BODY_LIMIT) -> list[str]:
    """Split an SMS body without exceeding the provider character limit."""

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    remaining = str(text or "").strip()
    if not remaining:
        return []
    if len(remaining) <= max_chars:
        return [remaining]

    chunks: list[str] = []
    while len(remaining) > max_chars:
        cut = remaining.rfind("\n\n", 0, max_chars + 1)
        if cut < max_chars // 2:
            cut = remaining.rfind("\n", 0, max_chars + 1)
        if cut < max_chars // 2:
            cut = remaining.rfind(" ", 0, max_chars + 1)
        if cut <= 0:
            cut = max_chars

        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()

    if remaining:
        chunks.append(remaining)
    return chunks
