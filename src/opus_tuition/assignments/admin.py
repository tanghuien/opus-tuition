from django.contrib import admin

# Register your models here.
from .models import Level, Subject, Assignment

@admin.register(Level)
class LevelAdmin(admin.ModelAdmin):
    list_display = ("id", "level_name")

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("id", "subject_name")

@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("assignment_id", "hourly_rate", "get_start_date_iso", "assignment_status", "tutor__tutor_name", "student__student_name", "level__level_name", "subject__subject_name")
    list_filter = ("assignment_status",)

    def get_start_date_iso(self, obj):
        return obj.start_date.strftime("%Y-%m-%d")

    get_start_date_iso.short_description = "Start Date"
    get_start_date_iso.admin_order_field = "start_date"