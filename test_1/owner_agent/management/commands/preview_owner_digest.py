import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from testendpoint.models import Account

from owner_agent.services.digest_preview import build_digest_preview


class Command(BaseCommand):
    help = "Preview an owner-agent daily digest without saving or sending anything."

    def add_arguments(self, parser):
        selector = parser.add_mutually_exclusive_group(required=True)
        selector.add_argument("--account-id", type=int)
        selector.add_argument("--account-slug")
        parser.add_argument(
            "--date",
            dest="report_date",
            help="Local report date in YYYY-MM-DD format. Defaults to yesterday.",
        )
        parser.add_argument(
            "--timezone",
            dest="timezone_name",
            help="Optional IANA timezone override for the preview.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print the full preview as JSON instead of the SMS and item summary.",
        )

    def handle(self, *args, **options):
        account_id = options.get("account_id")
        account_slug = options.get("account_slug")

        if account_id:
            account = Account.objects.filter(id=account_id, is_active=True).first()
        else:
            account = Account.objects.filter(slug=account_slug, is_active=True).first()

        if not account:
            raise CommandError("Active account not found.")

        report_date = None
        if options.get("report_date"):
            try:
                report_date = date.fromisoformat(options["report_date"])
            except ValueError as exc:
                raise CommandError("--date must use YYYY-MM-DD format.") from exc

        preview = build_digest_preview(
            account,
            report_date=report_date,
            timezone_name=options.get("timezone_name"),
        )

        if options.get("json"):
            payload = preview.as_dict()
            payload["report_date"] = preview.report_date.isoformat()
            payload["evaluation_time"] = preview.evaluation_time.isoformat()
            self.stdout.write(json.dumps(payload, indent=2, default=str))
            return

        self.stdout.write(f"Account: {preview.account_name} ({preview.account_id})")
        self.stdout.write(f"Report date: {preview.report_date} ({preview.timezone_name})")
        self.stdout.write(
            "Calls: "
            f"{preview.total_calls} total, "
            f"{preview.handled_calls} handled, "
            f"{preview.unhandled_calls} unhandled, "
            f"{preview.attention_calls} attention, "
            f"{preview.context_calls} context"
        )
        self.stdout.write("\n--- SMS PREVIEW ---\n")
        self.stdout.write(preview.message_body)

        if preview.attention_items:
            self.stdout.write("\n--- ATTENTION ITEMS ---")
            for item in preview.attention_items:
                self.stdout.write(
                    f"[{item['call_id']}] {item['reason']}: {item['summary']}"
                )

        if preview.context_items:
            self.stdout.write("\n--- CONTEXT ITEMS ---")
            for item in preview.context_items:
                self.stdout.write(
                    f"[{item['call_id']}] {item['reason']}: {item['summary']}"
                )
