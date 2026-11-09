from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as django_timezone

from testendpoint.models import Account

from owner_agent.models import OwnerAgentSettings
from owner_agent.services.digest_delivery import (
    OwnerAgentDigestDeliveryError,
    deliver_owner_digest,
)


class Command(BaseCommand):
    help = "Build and send one owner-agent daily digest through GoHighLevel."

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
            "--dry-run",
            action="store_true",
            help="Build and print the SMS without saving or sending it.",
        )
        openai_group = parser.add_mutually_exclusive_group()
        openai_group.add_argument(
            "--openai",
            dest="use_openai",
            action="store_true",
            help="Analyze unhandled calls with OpenAI before building the digest.",
        )
        openai_group.add_argument(
            "--skip-openai",
            dest="use_openai",
            action="store_false",
            help="Use deterministic HostHub fields only.",
        )
        parser.set_defaults(use_openai=True)
        parser.add_argument(
            "--max-openai-calls",
            type=int,
            default=100,
            help="Maximum number of unhandled calls to analyze with OpenAI.",
        )

    def handle(self, *args, **options):
        account_id = options.get("account_id")
        account_slug = options.get("account_slug")
        account_query = Account.objects.filter(is_active=True)
        if account_id:
            account = account_query.filter(id=account_id).first()
        else:
            account = account_query.filter(slug=account_slug).first()
        if not account:
            raise CommandError("Active account not found.")

        owner_settings = OwnerAgentSettings.objects.filter(account=account).first()
        if not owner_settings:
            raise CommandError("Owner-agent settings are not configured for this account.")

        report_date = self._parse_report_date(
            options.get("report_date"), owner_settings.timezone_name
        )
        try:
            result = deliver_owner_digest(
                account,
                owner_settings,
                report_date=report_date,
                use_openai=options["use_openai"],
                max_openai_calls=options["max_openai_calls"],
                dry_run=options["dry_run"],
            )
        except OwnerAgentDigestDeliveryError as exc:
            raise CommandError(str(exc)) from exc

        preview = result.preview
        mode = "DRY RUN" if result.dry_run else "SENT"
        self.stdout.write(
            f"{mode}: {preview.account_name} | {preview.report_date} | "
            f"{preview.total_calls} calls, {preview.handled_calls} handled, "
            f"{preview.attention_calls} attention, {preview.context_calls} context"
        )
        if not result.dry_run and not result.sent:
            self.stdout.write("Digest was already sent for this account and date.")
        self.stdout.write("\n--- SMS ---\n")
        self.stdout.write(preview.message_body)

    @staticmethod
    def _parse_report_date(value: str | None, timezone_name: str) -> date:
        if value:
            try:
                return date.fromisoformat(value)
            except ValueError as exc:
                raise CommandError("--date must use YYYY-MM-DD format.") from exc

        try:
            tz = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, TypeError):
            tz = ZoneInfo("America/Detroit")
        return django_timezone.localtime(django_timezone.now(), tz).date() - timedelta(days=1)
