from django.contrib import admin

from .models import (
    OwnerAgentAnalysis,
    OwnerAgentAssessment,
    OwnerAgentDigest,
    OwnerAgentDigestItem,
    OwnerAgentMessage,
    OwnerAgentSettings,
)


@admin.register(OwnerAgentSettings)
class OwnerAgentSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "account",
        "owner_phone_number",
        "timezone_name",
        "preferred_time",
        "enabled",
    )
    list_filter = ("enabled", "timezone_name")
    search_fields = ("account__name", "owner_phone_number", "ghl_contact_id")


@admin.register(OwnerAgentAnalysis)
class OwnerAgentAnalysisAdmin(admin.ModelAdmin):
    list_display = (
        "call",
        "status",
        "intent",
        "workflow",
        "meaningful_conversation",
        "reservation_date",
        "confidence",
        "analyzed_at",
    )
    list_filter = ("status", "meaningful_conversation", "future_commitment")
    search_fields = ("call__bland_call_id", "call__user_name", "normalized_summary")


@admin.register(OwnerAgentAssessment)
class OwnerAgentAssessmentAdmin(admin.ModelAdmin):
    list_display = ("call", "status", "reason", "evaluated_for_date", "evaluated_at")
    list_filter = ("status", "reason")
    search_fields = ("call__bland_call_id", "call__user_name", "explanation")


@admin.register(OwnerAgentDigest)
class OwnerAgentDigestAdmin(admin.ModelAdmin):
    list_display = (
        "account",
        "local_date",
        "status",
        "total_calls",
        "handled_calls",
        "attention_calls",
        "sent_at",
    )
    list_filter = ("status", "local_date")
    search_fields = ("account__name", "message_body", "ghl_message_id")


@admin.register(OwnerAgentDigestItem)
class OwnerAgentDigestItemAdmin(admin.ModelAdmin):
    list_display = ("digest", "call", "section", "position", "reason")
    list_filter = ("section", "reason")
    search_fields = ("call__bland_call_id", "call__user_name", "summary")


@admin.register(OwnerAgentMessage)
class OwnerAgentMessageAdmin(admin.ModelAdmin):
    list_display = (
        "account",
        "direction",
        "status",
        "owner_phone_number",
        "ghl_message_id",
        "created_at",
    )
    list_filter = ("direction", "status", "channel")
    search_fields = ("account__name", "owner_phone_number", "ghl_contact_id", "body")
