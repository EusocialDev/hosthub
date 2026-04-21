from django.core.management.base import BaseCommand
from testendpoint.services.email_reports import send_daily_call_report
from testendpoint.models import Account


class Command(BaseCommand):
    help = "Send the daily call report email"

    def handle(self, *args, **kwargs):
        self.stdout.write("Generating daily call report...")

        accounts = (
            Account.objects.
            filter(is_active=True, daily_report_email_enabled=True)
            .exclude(daily_report_email__isnull=True)
            .exclude(daily_report_email__exact="")
            .order_by("name")
        )

        sent_count = 0
        failed_count = 0

        for account in accounts:
            self.stdout.write(f"Generating daily call report for {account.name}...")

            try:
                result = send_daily_call_report(account=account)
            except Exception as exc:
                failed_count += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Failed to send report for {account.name}: {exc}"
                    )
                )
                continue

            sent_count += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"Sent Report for {account.name}: {result}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Daily Report complete. \nSent: {sent_count}.\nFailed: {failed_count}."
            )
        )

