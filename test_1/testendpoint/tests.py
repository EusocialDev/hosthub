import json

from django.test import TestCase
from django.test import override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import (
    Account,
    BusinessHour,
    Call,
    DateOverride,
    Location,
    PhoneNumber,
    RetellPhoneConfiguration,
)
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

    def test_status_accepts_relative_dates_in_location_timezone(self):
        local_today = datetime.now(ZoneInfo("America/Detroit")).date()
        tomorrow = local_today + timedelta(days=1)
        BusinessHour.objects.create(
            location=self.location,
            day_of_week=tomorrow.weekday(),
            open_time=time(19, 0),
            close_time=time(22, 0),
        )

        response = self.client.get(
            "/test/api/hours/hours-main/status/",
            {"date": "tomorrow", "time": "9:30 PM"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["reservation_date"],
            tomorrow.strftime("%m/%d/%Y"),
        )
        self.assertTrue(response.json()["is_open"])

    def test_status_accepts_spoken_number_time_from_retell(self):
        local_today = datetime.now(ZoneInfo("America/Detroit")).date()
        tomorrow = local_today + timedelta(days=1)
        BusinessHour.objects.create(
            location=self.location,
            day_of_week=tomorrow.weekday(),
            open_time=time(17, 0),
            close_time=time(18, 0),
        )

        response = self.client.get(
            "/test/api/hours/hours-main/status/",
            {"date": "tomorrow", "time": "five thirty PM"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reservation_time"], "5:30 PM")
        self.assertTrue(response.json()["is_open"])

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


class RetellWebhookTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            name="Retell Test Account",
            slug="retell-test-account",
        )
        self.location = Location.objects.create(
            account=self.account,
            name="Retell Main",
            slug="retell-main",
        )
        PhoneNumber.objects.create(
            account=self.account,
            location=self.location,
            number="+19478135161",
        )

    @override_settings(
        RETELL_WEBHOOK_TOKEN="retell-test-token",
        RETELL_API_KEY="",
    )
    def test_retell_post_call_is_saved_through_existing_bland_upsert(self):
        payload = {
            "event": "call_analyzed",
            "name": "hosthub_post_call",
            "call": {
                "call_id": "retell-call-1",
                "from_number": "+17347527463",
                "to_number": "+19478135161",
                "start_timestamp": 1790988771000,
                "end_timestamp": 1790988801000,
                "call_status": "ended",
                "transcript": (
                    "agent: How can I help? user: I need a reservation for four."
                ),
                "transcript_object": [
                    {"role": "agent", "content": "How can I help?"},
                    {"role": "user", "content": "I need a reservation for four."},
                ],
                "call_analysis": {
                    "call_summary": "The caller requested a reservation for four.",
                    "custom_analysis_data": {
                        "hosthub_category": "reservation",
                        "caller_name": "Sarah",
                        "reservation_date": "November 18th",
                        "reservation_time": "7 PM",
                        "party_size": 4,
                    },
                },
                "collected_dynamic_variables": {
                    "user_name": "Sarah Collected",
                    "date": "November 19th",
                    "time": "7 PM",
                    "guest": "4",
                    "request": "a reservation",
                },
                "retell_llm_dynamic_variables": {},
            },
            "args": {},
        }

        response = self.client.post(
            "/test/webhooks/retell/calls/retell-test-token/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        call = Call.objects.get(bland_call_id="retell_retell-call-1")
        self.assertEqual(call.location_id, self.location.id)
        self.assertEqual(call.display_category, "reservation")
        self.assertEqual(call.user_name, "Sarah Collected")
        self.assertEqual(call.summary, "The caller requested a reservation for four.")
        self.assertIn("reservation for four", call.full_transcript)
        self.assertEqual(call.variables["party_size"], 4)
        self.assertEqual(call.variables["date"], "November 19th")
        self.assertEqual(call.variables["guest"], "4")
        self.assertEqual(call.host_status, "needs_action")
        self.assertIsNone(call.handled_at)

    @override_settings(
        RETELL_WEBHOOK_TOKEN="retell-test-token",
        RETELL_API_KEY="",
    )
    def test_retell_call_ended_is_ignored(self):
        response = self.client.post(
            "/test/webhooks/retell/calls/retell-test-token/",
            data=json.dumps(
                {
                    "event": "call_ended",
                    "call": {"call_id": "retell-ended-only"},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ignored_event"], "call_ended")
        self.assertFalse(
            Call.objects.filter(bland_call_id="retell_retell-ended-only").exists()
        )


class RetellInboundWebhookTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            name="Inbound Test Account",
            slug="inbound-test-account",
        )
        self.location = Location.objects.create(
            account=self.account,
            name="Sapori",
            slug="sapori",
        )
        self.phone_number = PhoneNumber.objects.create(
            account=self.account,
            location=self.location,
            number="+19478135161",
        )
        RetellPhoneConfiguration.objects.create(
            phone_number=self.phone_number,
            location_description="Italian restaurant in downtown Trenton.",
            location_address="123 Main Street, Trenton, MI",
            corking_fee="$25 per bottle",
            private_events_description="Private events are available for groups.",
            resy_venue_id="venue-123",
            resy_location_slug="sapori-trenton",
            host_email="orders@saporirestaurant.com",
            manager_email="manager@saporirestaurant.com",
            printer_api="printer-secret",
        )

    @override_settings(RETELL_API_KEY="")
    def test_inbound_webhook_returns_retell_dynamic_variables(self):
        response = self.client.post(
            "/api/retell/inbound/",
            data=json.dumps(
                {
                    "event": "call_inbound",
                    "call_inbound": {
                        "call_id": "inbound-call-1",
                        "from_number": "+17347527463",
                        "to_number": "+19478135161",
                    },
                }
            ),
            content_type="application/json",
        )

        payload = response.json()
        variables = payload["call_inbound"]["dynamic_variables"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(variables["location_slug"], "sapori")
        self.assertEqual(variables["location_name"], "Sapori")
        self.assertEqual(variables["location_discription"], "Italian restaurant in downtown Trenton.")
        self.assertEqual(variables["private_events_discription"], "Private events are available for groups.")
        self.assertEqual(variables["host_email"], "orders@saporirestaurant.com")
        self.assertEqual(variables["printer_api"], "printer-secret")
        self.assertEqual(
            payload["call_inbound"]["metadata"]["hosthub_location_id"],
            str(self.location.id),
        )

    @override_settings(RETELL_API_KEY="")
    def test_inbound_webhook_rejects_unknown_destination_number(self):
        response = self.client.post(
            "/api/retell/inbound/",
            data=json.dumps(
                {
                    "event": "call_inbound",
                    "call_inbound": {"to_number": "+15555550123"},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["call_inbound"]["reject"])
