from django.core.management.base import BaseCommand
from testendpoint.services.email_reports import send_daily_call_report


class Command(BaseCommand):
    help = "Send the daily call report email"

    def handle(self, *args, **kwargs):
        self.stdout.write("Generating daily call report...")

        result = send_daily_call_report()

        self.stdout.write(self.style.SUCCESS(f"Email send result: {result}"))