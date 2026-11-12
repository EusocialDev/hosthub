import json
from dataclasses import replace
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from testendpoint.models import Account, Call

from owner_agent.services.digest_preview import build_digest_preview
from owner_agent.services.openai_analysis import OpenAIAnalysisError, analyze_call
from owner_agent.services.digest_rewrite import DigestRewriteError, rewrite_digest_message


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
        parser.add_argument(
            "--openai",
            action="store_true",
            help="Run a non-persisting OpenAI analysis for unhandled calls and compare the enhanced preview.",
        )
        parser.add_argument(
            "--max-openai-calls",
            type=int,
            default=25,
            help="Maximum number of unhandled calls to send to OpenAI in this preview.",
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

        enhanced_preview = None
        comparisons = []
        analysis_by_call_id = {}

        if options.get("openai"):
            unhandled_ids = [
                item["call_id"]
                for item in preview.call_assessments
                if item["status"] != "handled"
            ]
            calls = list(
                Call.objects.filter(id__in=unhandled_ids)
                .select_related("location")
                .order_by("created_at", "id")[: options["max_openai_calls"]]
            )

            for call in calls:
                try:
                    analysis_by_call_id[call.id] = analyze_call(
                        call,
                        evaluation_time=preview.evaluation_time,
                    )
                except OpenAIAnalysisError as exc:
                    raise CommandError(
                        f"OpenAI analysis failed for call {call.id}: {exc}"
                    ) from exc

            enhanced_preview = build_digest_preview(
                account,
                report_date=preview.report_date,
                timezone_name=preview.timezone_name,
                evaluation_time=preview.evaluation_time,
                analysis_by_call_id=analysis_by_call_id,
            )
            try:
                enhanced_preview = replace(
                    enhanced_preview,
                    message_body=rewrite_digest_message(enhanced_preview),
                )
            except DigestRewriteError:
                pass

            baseline_by_id = {
                item["call_id"]: item for item in preview.call_assessments
            }
            enhanced_by_id = {
                item["call_id"]: item
                for item in enhanced_preview.call_assessments
            }
            for call_id, analysis in analysis_by_call_id.items():
                baseline = baseline_by_id[call_id]
                enhanced = enhanced_by_id[call_id]
                comparisons.append(
                    {
                        "call_id": call_id,
                        "changed": (
                            baseline["status"],
                            baseline["reason"],
                        )
                        != (
                            enhanced["status"],
                            enhanced["reason"],
                        ),
                        "baseline_status": baseline["status"],
                        "baseline_reason": baseline["reason"],
                        "enhanced_status": enhanced["status"],
                        "enhanced_reason": enhanced["reason"],
                        "openai_intent": analysis.intent,
                        "openai_summary": analysis.normalized_summary,
                        "confidence": analysis.confidence,
                    }
                )

        if options.get("json"):
            payload = {
                "baseline": preview.as_dict(),
                "enhanced": enhanced_preview.as_dict() if enhanced_preview else None,
                "openai_comparisons": comparisons,
            }
            for key in ("baseline", "enhanced"):
                if payload[key]:
                    payload[key]["report_date"] = payload[key]["report_date"].isoformat()
                    payload[key]["evaluation_time"] = payload[key]["evaluation_time"].isoformat()
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

        if enhanced_preview:
            self.stdout.write("\n--- OPENAI COMPARISON ---")
            self.stdout.write(
                f"Analyzed {len(analysis_by_call_id)} unhandled calls; no analysis records were saved."
            )
            for comparison in comparisons:
                changed = "changed" if comparison["changed"] else "unchanged"
                self.stdout.write(
                    f"[{comparison['call_id']}] {changed}: "
                    f"{comparison['baseline_status']}/{comparison['baseline_reason']} → "
                    f"{comparison['enhanced_status']}/{comparison['enhanced_reason']}"
                )
                if comparison["openai_summary"]:
                    self.stdout.write(f"  OpenAI: {comparison['openai_summary']}")

            self.stdout.write("\n--- OPENAI ENHANCED SMS PREVIEW ---\n")
            self.stdout.write(enhanced_preview.message_body)

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
