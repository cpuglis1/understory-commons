from django.contrib import admin, messages

from .models import AttendanceRecord, Participant


def merge_participants(modeladmin, request, queryset):
    """Merge selected participants into the oldest one, preserving all history."""
    if queryset.count() < 2:
        modeladmin.message_user(
            request, "Select at least 2 participants to merge.", level=messages.ERROR
        )
        return

    already_merged = queryset.filter(merged_into__isnull=False)
    if already_merged.exists():
        names = ", ".join(already_merged.values_list("display_name", flat=True))
        modeladmin.message_user(
            request,
            f"Cannot merge already-merged participants: {names}",
            level=messages.ERROR,
        )
        return

    target = queryset.order_by("created_at").first()
    merged_count = queryset.exclude(pk=target.pk).update(merged_into=target)
    modeladmin.message_user(
        request,
        f"Merged {merged_count} participant(s) into '{target.display_name}'.",
    )


merge_participants.short_description = "Merge selected participants into the oldest"


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("display_name", "organization", "merged_into", "created_at")
    list_filter = ("organization",)
    search_fields = ("display_name",)
    readonly_fields = ("id", "created_at", "updated_at")
    actions = [merge_participants]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("organization", "merged_into")


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("participant", "session", "status", "source", "recorded_by", "recorded_at")
    list_filter = ("status", "source", "session__program__organization")
    search_fields = ("participant__display_name",)
    readonly_fields = (
        "id",
        "session",
        "participant",
        "status",
        "recorded_by",
        "recorded_at",
        "source",
        "raw_input",
        "llm_request_id",
        "submission_idempotency_key",
    )

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
