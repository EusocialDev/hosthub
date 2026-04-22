from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import datetime

from .models import Account, Call, Location
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
