from django.contrib import admin

from .models import Organization, Program, ProgramFacilitator, Session


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)
    readonly_fields = ("id", "created_at", "updated_at")


class ProgramFacilitatorInline(admin.TabularInline):
    """Facilitators now go through ProgramFacilitator (it carries the pay rate),
    so assignments are edited as an inline rather than filter_horizontal."""

    model = ProgramFacilitator
    extra = 0
    raw_id_fields = ("facilitator",)


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "coordinator", "site_label", "is_archived")
    list_filter = ("is_archived", "organization")
    search_fields = ("name", "site_label")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = (ProgramFacilitatorInline,)
    raw_id_fields = ("coordinator", "default_facilitator")


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("program", "scheduled_date", "created_at")
    list_filter = ("program__organization",)
    search_fields = ("program__name",)
    readonly_fields = ("id", "created_at", "updated_at")
    date_hierarchy = "scheduled_date"
