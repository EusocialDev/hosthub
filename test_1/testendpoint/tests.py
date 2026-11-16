from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import date, datetime, time

from .models import Account, BusinessHour, Call, DateOverride, Location
from .services.reports import build_daily_call_report


class DailyCallReportTests(TestCase):
    def test_handled_by_label_uses_handled_by_user_first_name(self):
        account = Account.objects.create(name="Test Account", slug="test-account")
        location = Location.objects.create(
            account=account,
            name="Main Location",
            slug="main-location",
        )
        user = get_user_model().objects.create_user(
            username="alice@example.com",
            password="password",
            first_name="Alice",
        )
        created_at = timezone.make_aware(datetime(2026, 4, 21, 10, 0))

        Call.objects.create(
            account=account,
            location=location,
            bland_call_id="call-1",
            created_at=created_at,
            host_status="resolved",
            handled_at=created_at,
            handled_by_user=user,
            handled_by=None,
        )

        report = build_daily_call_report(account, report_date=created_at.date())
        section = report["locations"][0]

        self.assertEqual(section["detailed_calls"][0]["handled_by_label"], "Alice")
        self.assertEqual(section["by_handler"][0]["label"], "Alice")
        self.assertEqual(section["handled_calls_by_person"][0]["label"], "Alice")


class LocationHoursStatusTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            name="Hours Test Account",
            slug="hours-test-account",
        )
        self.location = Location.objects.create(
            account=self.account,
            name="Main Location",
            slug="hours-main",
            timezone="America/Detroit",
        )

    def test_status_uses_regular_hours(self):
        BusinessHour.objects.create(
            location=self.location,
            day_of_week=3,
            open_time=time(9, 0),
            close_time=time(17, 0),
        )

        response = self.client.get(
            "/test/api/hours/hours-main/status/",
            {"date": "2026-11-19", "time": "10:00"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_open"])
        self.assertEqual(response.json()["reason_code"], "regular_hours")
        self.assertEqual(response.json()["hours"], {"open": "09:00", "close": "17:00"})

    def test_status_uses_special_date_override(self):
        BusinessHour.objects.create(
            location=self.location,
            day_of_week=3,
            open_time=time(9, 0),
            close_time=time(17, 0),
        )
        DateOverride.objects.create(
            location=self.location,
            name="Thanksgiving early opening",
            start_date=date(2026, 11, 19),
            end_date=date(2026, 11, 19),
            is_closed=False,
            open_time=time(10, 0),
            close_time=time(22, 0),
        )

        response = self.client.get(
            "/test/api/hours/hours-main/status/",
            {"date": "2026-11-19", "time": "09:30"},
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload["is_open"])
        self.assertEqual(payload["reason_code"], "date_override")
        self.assertEqual(payload["reason"], "Outside special hours: Thanksgiving early opening")

    def test_status_rejects_missing_or_invalid_inputs(self):
        missing = self.client.get("/test/api/hours/hours-main/status/")
        invalid = self.client.get(
            "/test/api/hours/hours-main/status/",
            {"date": "not-a-date", "time": "not-a-time"},
        )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(invalid.status_code, 400)

    def test_status_accepts_natural_language_and_am_pm_inputs(self):
        BusinessHour.objects.create(
            location=self.location,
            day_of_week=3,
            open_time=time(9, 0),
            close_time=time(17, 0),
        )

        natural_response = self.client.get(
            "/test/api/hours/hours-main/status/",
            {"date": "November 19th, 2026", "time": "10 AM"},
        )
        numeric_response = self.client.get(
            "/test/api/hours/hours-main/status/",
            {"date": "11/19/2026", "time": "10:00"},
        )

        self.assertTrue(natural_response.json()["is_open"])
        self.assertEqual(natural_response.json()["reservation_date"], "11/19/2026")
        self.assertEqual(natural_response.json()["reservation_time"], "10:00 AM")
        self.assertTrue(numeric_response.json()["is_open"])

    def test_status_handles_the_after_midnight_part_of_overnight_hours(self):
        BusinessHour.objects.create(
            location=self.location,
            day_of_week=2,
            open_time=time(22, 0),
            close_time=time(2, 0),
        )

        response = self.client.get(
            "/test/api/hours/hours-main/status/",
            {"date": "2026-11-19", "time": "01:00"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_open"])
        self.assertEqual(response.json()["reason_code"], "regular_hours")
