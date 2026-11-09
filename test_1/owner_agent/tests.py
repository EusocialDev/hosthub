from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import override_settings
from django.test import SimpleTestCase

from .models import OwnerAgentAssessment
from .services.assessment import assess_call
from .services.digest_preview import _compose_message
from .services.ghl_owner_sms import (
    GHLOwnerSMSDeliveryError,
    build_owner_sms_payload,
    send_owner_sms,
)
from .services.openai_analysis import normalize_analysis_output


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
            "from_number": "+17347527463",
            "transcripts": [{"user": "user", "text": "I need help"}],
            "full_transcript": "user: I need help",
            "location": SimpleNamespace(timezone="America/Detroit"),
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def make_analysis(self, **overrides):
        values = {
            "meaningful_conversation": True,
            "workflow": "reservation_new",
            "reservation_date": None,
            "reservation_time": None,
            "guest_count": None,
            "future_commitment": False,
            "booking_link_sent": False,
            "kitchen_share_completed": False,
            "details_shared_with_manager": False,
            "manager_review_required": False,
            "customer_waiting_confirmation": False,
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

    def test_small_future_reservation_with_booking_link_is_context_only(self):
        call = self.make_call(
            variables={"date": "12/12/2026", "time": "7 PM", "guests": "4"},
        )
        analysis = self.make_analysis(
            reservation_date=datetime(2026, 12, 12).date(),
            reservation_time=datetime.strptime("19:00", "%H:%M").time(),
            guest_count=4,
            booking_link_sent=True,
            future_commitment=True,
        )

        result = assess_call(
            call,
            evaluation_time=self.evaluation_time,
            analysis=analysis,
        )

        self.assertEqual(result.status, OwnerAgentAssessment.Status.CONTEXT_ONLY)
        self.assertEqual(result.reason, OwnerAgentAssessment.Reason.BOOKING_LINK_SENT)

    def test_large_future_reservation_needs_manager_attention(self):
        call = self.make_call(variables={})
        analysis = self.make_analysis(
            reservation_date=datetime(2026, 12, 12).date(),
            reservation_time=datetime.strptime("19:00", "%H:%M").time(),
            guest_count=9,
            manager_review_required=True,
            customer_waiting_confirmation=True,
            future_commitment=True,
        )

        result = assess_call(
            call,
            evaluation_time=self.evaluation_time,
            analysis=analysis,
        )

        self.assertEqual(result.status, OwnerAgentAssessment.Status.NEEDS_ATTENTION)
        self.assertEqual(result.reason, OwnerAgentAssessment.Reason.FUTURE_RESERVATION)

    def test_carryout_with_kitchen_handoff_is_context_only(self):
        call = self.make_call(
            display_category="carryout",
            variables={},
            full_transcript=(
                "user: I want a carryout order\n"
                "assistant: I've successfully shared your order with the kitchen and they've already started preparing it."
            ),
        )
        analysis = self.make_analysis(
            workflow="carryout",
            kitchen_share_completed=True,
        )

        result = assess_call(
            call,
            evaluation_time=self.evaluation_time,
            analysis=analysis,
        )

        self.assertEqual(result.status, OwnerAgentAssessment.Status.CONTEXT_ONLY)
        self.assertEqual(
            result.reason,
            OwnerAgentAssessment.Reason.CARRYOUT_SHARED_WITH_KITCHEN,
        )

    def test_carryout_handoff_can_be_detected_without_llm_analysis(self):
        call = self.make_call(
            display_category="carryout",
            variables={},
            full_transcript=(
                "user: Carry out.\n"
                "assistant: I've successfully shared your order with the kitchen "
                "and they've already started preparing it."
            ),
        )

        result = assess_call(call, evaluation_time=self.evaluation_time)

        self.assertEqual(result.status, OwnerAgentAssessment.Status.CONTEXT_ONLY)
        self.assertEqual(
            result.reason,
            OwnerAgentAssessment.Reason.CARRYOUT_SHARED_WITH_KITCHEN,
        )

    def test_carryout_without_kitchen_handoff_needs_attention(self):
        call = self.make_call(display_category="carryout", variables={})
        analysis = self.make_analysis(
            workflow="carryout",
            kitchen_share_completed=False,
        )

        result = assess_call(
            call,
            evaluation_time=self.evaluation_time,
            analysis=analysis,
        )

        self.assertEqual(result.status, OwnerAgentAssessment.Status.NEEDS_ATTENTION)
        self.assertEqual(result.reason, OwnerAgentAssessment.Reason.INCOMPLETE_CARRYOUT)

    def test_same_day_change_needs_attention_even_if_time_has_passed(self):
        call = self.make_call(variables={})
        analysis = self.make_analysis(
            workflow="reservation_change",
            reservation_date=datetime(2026, 11, 6).date(),
            reservation_time=datetime.strptime("09:00", "%H:%M").time(),
            customer_waiting_confirmation=True,
        )

        result = assess_call(
            call,
            evaluation_time=self.evaluation_time,
            analysis=analysis,
        )

        self.assertEqual(result.status, OwnerAgentAssessment.Status.NEEDS_ATTENTION)
        self.assertEqual(result.reason, OwnerAgentAssessment.Reason.FUTURE_RESERVATION)

    def test_past_private_event_is_context_only(self):
        call = self.make_call(
            display_category="private_events",
            variables={"date": "11/05/2026"},
        )
        analysis = self.make_analysis(
            workflow="private_event_new",
            reservation_date=datetime(2026, 11, 5).date(),
            details_shared_with_manager=True,
            manager_review_required=True,
        )

        result = assess_call(
            call,
            evaluation_time=self.evaluation_time,
            analysis=analysis,
        )

        self.assertEqual(result.status, OwnerAgentAssessment.Status.CONTEXT_ONLY)
        self.assertEqual(result.reason, OwnerAgentAssessment.Reason.PAST_COMMITMENT)

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
                {
                    "user_name": "Maria",
                    "phone_number": "(734) 752-7463",
                    "summary": "Maria requested a reservation for December 12 at 7 PM.",
                }
            ],
            context_items=[
                {"reason": "silent_call"},
                {"reason": "silent_call"},
            ],
        )

        self.assertIn("Yesterday you received 10 calls.", message)
        self.assertTrue(message.startswith("Hello Dear Owner\n\n"))
        self.assertIn("3 were not marked handled, but only 1 may need attention:", message)
        self.assertIn(
            "1. Maria (734) 752-7463 requested a reservation for December 12 at 7 PM.",
            message,
        )
        self.assertIn("For context, the other 2 unhandled calls:", message)
        self.assertIn("2 unhandled calls contained no meaningful customer conversation.", message)

    def test_openai_analysis_can_enrich_missing_future_reservation_fields(self):
        call = self.make_call(variables={})
        analysis = normalize_analysis_output(
            {
                "meaningful_conversation": True,
                "intent": "reservation_request",
                "reservation_date": "2026-12-12",
                "reservation_time": "19:00",
                "guest_count": 4,
                "future_commitment": True,
                "customer_request": "Requested a reservation.",
                "normalized_summary": "Maria requested a reservation for four on December 12 at 7 PM.",
                "confidence": 0.97,
            },
            input_snapshot={"call_id": "call-1"},
            model_name="gpt-6-luna",
        )

        result = assess_call(
            call,
            evaluation_time=self.evaluation_time,
            analysis=analysis,
        )

        self.assertEqual(result.status, OwnerAgentAssessment.Status.NEEDS_ATTENTION)
        self.assertEqual(result.reason, OwnerAgentAssessment.Reason.FUTURE_RESERVATION)
        self.assertEqual(result.basis["reservation_date"], "2026-12-12")

    def test_openai_shortens_unbounded_classification_text_for_database_fields(self):
        result = normalize_analysis_output(
            {
                "meaningful_conversation": True,
                "intent": "I" * 200,
                "workflow": "W" * 200,
                "reservation_date": "",
                "reservation_time": "",
                "guest_count": 0,
                "future_commitment": False,
                "booking_link_sent": False,
                "kitchen_share_completed": False,
                "details_shared_with_manager": False,
                "manager_review_required": False,
                "customer_waiting_confirmation": False,
                "customer_request": "",
                "normalized_summary": "",
                "confidence": 0.5,
            },
            input_snapshot={},
            model_name="gpt-6-luna",
        )

        self.assertEqual(len(result.intent), 80)
        self.assertEqual(len(result.workflow), 80)


class GHLOwnerSMSTests(SimpleTestCase):
    def test_owner_sms_payload_contains_digest_context_and_normalized_phone(self):
        payload = build_owner_sms_payload(
            account_id=1,
            digest_id=22,
            report_date=datetime(2026, 11, 8).date(),
            owner_phone_number="(734) 752-7463",
            message_body="Hello Dear Owner",
            ghl_contact_id="contact-1",
            ghl_location_id="location-1",
        )

        self.assertEqual(payload["phone"], "+17347527463")
        self.assertEqual(payload["digest_id"], 22)
        self.assertEqual(payload["report_date"], "2026-11-08")
        self.assertEqual(payload["message"], "Hello Dear Owner")

    @override_settings(GHL_OWNER_AGENT_SMS_WEBHOOK_URL="https://example.test/owner-sms")
    @patch("owner_agent.services.ghl_owner_sms.requests.post")
    def test_owner_sms_sender_returns_provider_message_id(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"message_id": "ghl-123"}
        post.return_value.text = ""

        result = send_owner_sms({"phone": "+17347527463", "message": "Hello Dear Owner"})

        self.assertEqual(result.message_id, "ghl-123")
        post.assert_called_once_with(
            "https://example.test/owner-sms",
            json={"phone": "+17347527463", "message": "Hello Dear Owner"},
            timeout=10,
        )

    @override_settings(GHL_OWNER_AGENT_SMS_WEBHOOK_URL="")
    def test_owner_sms_sender_requires_webhook_configuration(self):
        with self.assertRaises(GHLOwnerSMSDeliveryError):
            send_owner_sms({"phone": "+17347527463", "message": "Hello Dear Owner"})
