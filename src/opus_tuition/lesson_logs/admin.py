from django.contrib import admin
from .models import LessonLog

# Register your models here.
@admin.register(LessonLog)
class LessonLogAdmin(admin.ModelAdmin):
    list_display = ("log_id", "get_session_date_iso", "duration_in_hours", "attendance_status", "session_notes", "fees_charged", "assignment__assignment_id")
    list_filter = ("attendance_status",)

    def get_session_date_iso(self, obj):
        return obj.session_date.strftime("%Y-%m-%d")

    get_session_date_iso.short_description = "Session Date"
    get_session_date_iso.admin_order_field = "session_date"
