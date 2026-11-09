from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as django_timezone

from owner_agent.models import OwnerAgentDigest, OwnerAgentSettings
from owner_agent.services.digest_delivery import deliver_owner_digest, scheduled_for


class Command(BaseCommand):
    help = "Send due owner-agent daily digests for all enabled accounts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--account-id",
            type=int,
            help="Limit the run to one account for testing.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Build due digests without saving or sending them.",
        )
        openai_group = parser.add_mutually_exclusive_group()
        openai_group.add_argument(
            "--openai",
            dest="use_openai",
            action="store_true",
            help="Analyze unhandled calls with OpenAI before sending.",
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
            help="Maximum number of unhandled calls to analyze per account.",
        )
        parser.add_argument(
            "--now",
            help="UTC timestamp override for testing, in ISO-8601 format.",
        )

    def handle(self, *args, **options):
        now = self._parse_now(options.get("now"))
        settings_qs = OwnerAgentSettings.objects.filter(
            enabled=True,
            account__is_active=True,
        ).select_related("account")
        if options.get("account_id"):
            settings_qs = settings_qs.filter(account_id=options["account_id"])

        due_count = 0
        sent_count = 0
        skipped_count = 0
        error_count = 0

        for owner_settings in settings_qs.order_by("account_id"):
            tz = self._timezone(owner_settings.timezone_name)
            local_now = django_timezone.localtime(now, tz)
            report_date = local_now.date() - timedelta(days=1)
            scheduled_time = scheduled_for(owner_settings, report_date)

            if local_now < scheduled_time:
                skipped_count += 1
                self.stdout.write(
                    self.style.NOTICE(
                        f"SKIP account {owner_settings.account_id}: "
                        f"scheduled for {scheduled_time.isoformat()}"
                    )
                )
                continue

            if OwnerAgentDigest.objects.filter(
                account_id=owner_settings.account_id,
                local_date=report_date,
                status=OwnerAgentDigest.Status.SENT,
            ).exists():
                skipped_count += 1
                self.stdout.write(
                    f"SKIP account {owner_settings.account_id}: "
                    f"digest {report_date} already sent"
                )
                continue

            due_count += 1
            try:
                result = deliver_owner_digest(
                    owner_settings.account,
                    owner_settings,
                    report_date=report_date,
                    use_openai=options["use_openai"],
                    max_openai_calls=options["max_openai_calls"],
                    dry_run=options["dry_run"],
                )
            except Exception as exc:
                error_count += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"ERROR account {owner_settings.account_id}: {exc}"
                    )
                )
                continue

            if result.sent:
                sent_count += 1
            self.stdout.write(
                f"{'DRY RUN' if result.dry_run else 'SENT'} account "
                f"{owner_settings.account_id}: {report_date} | "
                f"{result.preview.total_calls} calls, "
                f"{result.preview.attention_calls} attention"
            )

        self.stdout.write(
            f"Due: {due_count}; sent: {sent_count}; skipped: {skipped_count}; errors: {error_count}"
        )
        if error_count:
            raise CommandError(f"{error_count} owner digest(s) failed.")

    @staticmethod
    def _timezone(name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, TypeError):
            return ZoneInfo("America/Detroit")

    @staticmethod
    def _parse_now(value: str | None) -> datetime:
        if not value:
            return django_timezone.now()
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CommandError("--now must use ISO-8601 format.") from exc
        if django_timezone.is_naive(parsed):
            parsed = django_timezone.make_aware(parsed, timezone=ZoneInfo("UTC"))
        return parsed.astimezone(ZoneInfo("UTC"))
