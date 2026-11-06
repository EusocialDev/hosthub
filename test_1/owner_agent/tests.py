from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from .models import OwnerAgentAssessment
from .services.assessment import assess_call
from .services.digest_preview import _compose_message


class OwnerAgentAssessmentTests(SimpleTestCase):
    evaluation_time = datetime(2026, 11, 6, 10, 0, tzinfo=ZoneInfo("America/Detroit"))

    def make_call(self, **overrides):
        values = {
            "host_status": "needs_action",
            "handled_at": None,
            "display_category": "reservation",
            "disposition": None,
            "created_at": datetime(2026, 11, 5, 18, 0, tzinfo=ZoneInfo("America/Detroit")),
            "variables": {},
            "summary": "",
            "notes": "",
            "transcripts": [{"user": "user", "text": "I need help"}],
            "full_transcript": "user: I need help",
            "location": SimpleNamespace(timezone="America/Detroit"),
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_hosthub_handled_always_wins(self):
        call = self.make_call(
            host_status="resolved",
            variables={"date": "12/12/2026", "time": "7 PM"},
        )

        result = assess_call(call, evaluation_time=self.evaluation_time)

        self.assertEqual(result.status, OwnerAgentAssessment.Status.HANDLED)
        self.assertEqual(result.reason, OwnerAgentAssessment.Reason.HOSTHUB_HANDLED)

    def test_future_reservation_needs_attention(self):
        call = self.make_call(
            variables={"date": "12/12/2026", "time": "7 PM", "guests": "4"},
        )

        result = assess_call(call, evaluation_time=self.evaluation_time)

        self.assertEqual(result.status, OwnerAgentAssessment.Status.NEEDS_ATTENTION)
        self.assertEqual(result.reason, OwnerAgentAssessment.Reason.FUTURE_RESERVATION)
        self.assertEqual(result.basis["guest_count"], 4)

    def test_past_reservation_is_context_only(self):
        call = self.make_call(
            variables={"date": "11/05/2026", "time": "7 PM", "guests": "4"},
        )

        result = assess_call(call, evaluation_time=self.evaluation_time)

        self.assertEqual(result.status, OwnerAgentAssessment.Status.CONTEXT_ONLY)
        self.assertEqual(result.reason, OwnerAgentAssessment.Reason.PAST_RESERVATION)

    def test_same_day_future_reservation_is_attention_item(self):
        call = self.make_call(
            variables={"date": "11/06/2026", "time": "7 PM", "guests": "4"},
        )

        result = assess_call(call, evaluation_time=self.evaluation_time)

        self.assertEqual(result.status, OwnerAgentAssessment.Status.NEEDS_ATTENTION)
        self.assertEqual(result.reason, OwnerAgentAssessment.Reason.FUTURE_RESERVATION)

    def test_call_with_no_user_speech_is_context_only(self):
        call = self.make_call(
            transcripts=[{"user": "agent", "text": "Hello"}],
            full_transcript="assistant: Hello",
            variables={"date": "12/12/2026"},
        )

        result = assess_call(call, evaluation_time=self.evaluation_time)

        self.assertEqual(result.status, OwnerAgentAssessment.Status.CONTEXT_ONLY)
        self.assertEqual(result.reason, OwnerAgentAssessment.Reason.SILENT_CALL)

    def test_callback_request_needs_attention_without_reservation_date(self):
        call = self.make_call(
            display_category="leave_message",
            summary="Caller requested a manager callback.",
            variables={},
        )

        result = assess_call(call, evaluation_time=self.evaluation_time)

        self.assertEqual(result.status, OwnerAgentAssessment.Status.NEEDS_ATTENTION)
        self.assertEqual(result.reason, OwnerAgentAssessment.Reason.FUTURE_CALLBACK)

    def test_digest_message_prioritizes_attention_and_summarizes_context(self):
        message = _compose_message(
            total_calls=10,
            handled_calls=7,
            unhandled_calls=3,
            attention_items=[
                {"summary": "Maria requested a reservation for December 12 at 7 PM."}
            ],
            context_items=[
                {"reason": "silent_call"},
                {"reason": "silent_call"},
            ],
        )

        self.assertIn("Yesterday you received 10 calls.", message)
        self.assertIn("3 were not marked handled, but only 1 may need attention:", message)
        self.assertIn("1. Maria requested a reservation for December 12 at 7 PM.", message)
        self.assertIn("For context, the other 2 unhandled calls:", message)
        self.assertIn("2 unhandled calls contained no meaningful customer conversation.", message)
