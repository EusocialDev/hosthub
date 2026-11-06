from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import models


class OwnerAgentSettings(models.Model):
    """Account-level configuration for the owner assistant."""

    account = models.OneToOneField(
        "testendpoint.Account",
        on_delete=models.CASCADE,
        related_name="owner_agent_settings",
    )
    owner_phone_number = models.CharField(max_length=30, blank=True)
    timezone_name = models.CharField(max_length=64, default="America/Detroit")
    preferred_time = models.TimeField(default=time(10, 0))
    enabled = models.BooleanField(default=False)

    # HighLevel uses the existing shared sender number. The contact is still
    # account-specific so inbound owner replies can be routed safely.
    ghl_contact_id = models.CharField(max_length=255, blank=True)
    ghl_location_id = models.CharField(max_length=255, blank=True)
    owner_phone_verified_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["enabled", "preferred_time"]),
            models.Index(fields=["owner_phone_number"]),
        ]

    def clean(self):
        super().clean()
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, TypeError):
            raise ValidationError({"timezone_name": "Enter a valid IANA timezone."})

    def __str__(self):
        return f"Owner agent settings: {self.account.name}"


class OwnerAgentAnalysis(models.Model):
    """Structured interpretation of one persisted HostHub call."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"

    call = models.OneToOneField(
        "testendpoint.Call",
        on_delete=models.CASCADE,
        related_name="owner_agent_analysis",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    meaningful_conversation = models.BooleanField(null=True, blank=True)
    intent = models.CharField(max_length=80, blank=True)
    reservation_date = models.DateField(null=True, blank=True)
    reservation_time = models.TimeField(null=True, blank=True)
    guest_count = models.PositiveIntegerField(null=True, blank=True)
    future_commitment = models.BooleanField(null=True, blank=True)
    customer_request = models.TextField(blank=True)
    normalized_summary = models.TextField(blank=True)
    confidence = models.FloatField(null=True, blank=True)

    # Preserve the structured model response and the source facts used to
    # generate it so an owner-facing message can be audited later.
    llm_output = models.JSONField(default=dict, blank=True)
    input_snapshot = models.JSONField(default=dict, blank=True)
    model_name = models.CharField(max_length=120, blank=True)
    prompt_version = models.CharField(max_length=40, blank=True)
    error_message = models.TextField(blank=True)
    analyzed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "updated_at"]),
            models.Index(fields=["reservation_date"]),
        ]

    def __str__(self):
        return f"Owner agent analysis: call {self.call_id}"


class OwnerAgentAssessment(models.Model):
    """Current rule-based owner follow-up decision for a call."""

    class Status(models.TextChoices):
        HANDLED = "handled", "Handled"
        NEEDS_ATTENTION = "needs_attention", "Needs attention"
        CONTEXT_ONLY = "context_only", "Context only"
        UNKNOWN = "unknown", "Unknown"

    class Reason(models.TextChoices):
        HOSTHUB_HANDLED = "hosthub_handled", "Handled in HostHub"
        SILENT_CALL = "silent_call", "No meaningful customer conversation"
        PAST_RESERVATION = "past_reservation", "Reservation date has passed"
        FUTURE_RESERVATION = "future_reservation", "Future reservation is unhandled"
        PAST_COMMITMENT = "past_commitment", "Commitment date has passed"
        FUTURE_COMMITMENT = "future_commitment", "Future commitment is unhandled"
        FUTURE_CALLBACK = "future_callback", "Future callback or commitment"
        INSUFFICIENT_INFORMATION = "insufficient_information", "Insufficient information"

    call = models.OneToOneField(
        "testendpoint.Call",
        on_delete=models.CASCADE,
        related_name="owner_agent_assessment",
    )
    status = models.CharField(max_length=30, choices=Status.choices)
    reason = models.CharField(max_length=40, choices=Reason.choices)
    explanation = models.TextField(blank=True)
    evaluated_for_date = models.DateField(null=True, blank=True)
    rule_version = models.CharField(max_length=40, default="v1")
    basis = models.JSONField(default=dict, blank=True)
    evaluated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "evaluated_for_date"]),
            models.Index(fields=["reason"]),
        ]

    def __str__(self):
        return f"Owner agent assessment: call {self.call_id}"


class OwnerAgentDigest(models.Model):
    """One account-scoped daily digest, including delivery state."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    account = models.ForeignKey(
        "testendpoint.Account",
        on_delete=models.CASCADE,
        related_name="owner_agent_digests",
    )
    local_date = models.DateField()
    scheduled_for = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    message_body = models.TextField(blank=True)
    ghl_message_id = models.CharField(max_length=255, blank=True)
    provider_response = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    total_calls = models.PositiveIntegerField(default=0)
    handled_calls = models.PositiveIntegerField(default=0)
    unhandled_calls = models.PositiveIntegerField(default=0)
    attention_calls = models.PositiveIntegerField(default=0)
    context_calls = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "local_date"],
                name="unique_owner_agent_digest_per_account_day",
            ),
        ]
        indexes = [
            models.Index(fields=["account", "local_date"]),
            models.Index(fields=["status", "scheduled_for"]),
        ]

    def __str__(self):
        return f"Owner agent digest: {self.account.name} {self.local_date}"


class OwnerAgentDigestItem(models.Model):
    """A point-in-time snapshot of a call included in a digest."""

    class Section(models.TextChoices):
        ATTENTION = "attention", "May need attention"
        CONTEXT = "context", "Context"

    digest = models.ForeignKey(
        OwnerAgentDigest,
        on_delete=models.CASCADE,
        related_name="items",
    )
    call = models.ForeignKey(
        "testendpoint.Call",
        on_delete=models.CASCADE,
        related_name="owner_agent_digest_items",
    )
    section = models.CharField(max_length=20, choices=Section.choices)
    position = models.PositiveIntegerField(default=0)
    reason = models.CharField(max_length=40, blank=True)
    summary = models.TextField(blank=True)
    source_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["digest", "call"],
                name="unique_owner_agent_digest_call",
            ),
        ]
        indexes = [
            models.Index(fields=["digest", "section", "position"]),
        ]

    def __str__(self):
        return f"Owner agent digest item: {self.digest_id}/{self.call_id}"


class OwnerAgentMessage(models.Model):
    """Inbound and outbound SMS records for the owner conversation."""

    class Direction(models.TextChoices):
        INBOUND = "inbound", "Inbound"
        OUTBOUND = "outbound", "Outbound"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        RECEIVED = "received", "Received"
        FAILED = "failed", "Failed"

    account = models.ForeignKey(
        "testendpoint.Account",
        on_delete=models.CASCADE,
        related_name="owner_agent_messages",
    )
    digest = models.ForeignKey(
        OwnerAgentDigest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
    )
    direction = models.CharField(max_length=20, choices=Direction.choices)
    channel = models.CharField(max_length=20, default="sms")
    status = models.CharField(max_length=20, choices=Status.choices)
    owner_phone_number = models.CharField(max_length=30)
    ghl_contact_id = models.CharField(max_length=255, blank=True)
    ghl_message_id = models.CharField(max_length=255, blank=True)
    body = models.TextField()
    provider_payload = models.JSONField(default=dict, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ghl_message_id"],
                condition=~models.Q(ghl_message_id=""),
                name="unique_owner_agent_ghl_message_id",
            ),
        ]
        indexes = [
            models.Index(fields=["account", "created_at"]),
            models.Index(fields=["owner_phone_number", "created_at"]),
            models.Index(fields=["ghl_contact_id", "created_at"]),
        ]

    def __str__(self):
        return f"Owner agent {self.direction} SMS: {self.account.name}"
