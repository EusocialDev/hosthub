"""Deterministic parsing for customer-friendly time expressions."""

from datetime import datetime, time
import re

from dateutil import parser as date_parser


NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}


def _spoken_number(tokens: list[str]) -> int | None:
    if len(tokens) == 1:
        return NUMBER_WORDS.get(tokens[0])
    if len(tokens) == 2:
        tens = NUMBER_WORDS.get(tokens[0])
        units = NUMBER_WORDS.get(tokens[1])
        if tens in {20, 30, 40, 50} and units is not None and 0 <= units <= 9:
            return tens + units
    return None


def _spoken_clock_time(text: str) -> time | None:
    normalized = text.lower().strip()
    normalized = normalized.replace("-", " ")
    normalized = normalized.replace("o'clock", "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = normalized.replace("a.m.", "am").replace("p.m.", "pm")

    if normalized == "noon":
        return time(12, 0)
    if normalized == "midnight":
        return time(0, 0)

    meridiem = None
    if normalized.endswith(" am") or normalized.endswith(" pm"):
        meridiem = normalized[-2:]
        normalized = normalized[:-3].strip()
    else:
        for phrase, value in (
            ("in the morning", "am"),
            ("in the afternoon", "pm"),
            ("in the evening", "pm"),
            ("at night", "pm"),
            ("tonight", "pm"),
        ):
            if normalized.endswith(phrase):
                meridiem = value
                normalized = normalized[: -len(phrase)].strip()
                break

    tokens = normalized.split()
    if not tokens or not all(token in NUMBER_WORDS for token in tokens):
        return None

    hour = NUMBER_WORDS.get(tokens[0])
    if hour is None or not 1 <= hour <= 12:
        return None

    minute = 0
    if len(tokens) > 1:
        parsed_minute = _spoken_number(tokens[1:])
        minute = parsed_minute if parsed_minute is not None else -1
        if minute < 0 or minute > 59:
            return None

    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    return time(hour, minute)


def parse_natural_time(value) -> time | None:
    """Parse numeric and spoken times such as ``five thirty PM``."""
    if isinstance(value, datetime):
        return value.time().replace(tzinfo=None)
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    if value in (None, ""):
        return None

    text = str(value).strip()
    if not text:
        return None

    spoken = _spoken_clock_time(text)
    if spoken is not None:
        return spoken

    try:
        parsed = date_parser.parse(
            text,
            default=datetime(2000, 1, 1),
            fuzzy=True,
        )
    except (TypeError, ValueError, OverflowError):
        return None

    if parsed.tzinfo is not None:
        return None
    return parsed.time().replace(tzinfo=None)
