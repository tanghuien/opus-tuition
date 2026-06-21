from django.contrib import admin

# Register your models here.
from .models import Upload, CleanRecord, QuarantineRecord

@admin.register(Upload)
class UploadAdmin(admin.ModelAdmin):
    list_display = ("upload_id", "raw_file", "file_category", "status", "accepted_rows", "quarantined_rows", "created_at", "updated_at","system_error_trace")
    list_filter = ("status", "file_category")
    readonly_fields = ("upload_id", "created_at", "updated_at", "system_error_trace")

@admin.register(CleanRecord)
class CleanRecordAdmin(admin.ModelAdmin):
    list_display = ("clean_record_id", "upload_id", "row_index", "created_at")
    list_filter = ("upload",)
    readonly_fields = ("clean_record_id", "upload_id", "row_index", "clean_payload")

@admin.register(QuarantineRecord)
class QuarantineRecordAdmin(admin.ModelAdmin):
    list_display = ("quarantine_record_id", "raw_payload", "upload_id", "created_at", "row_index", "reason_code", "error_details", "is_resolved")
    list_filter = ("is_resolved", "reason_code")
    readonly_fields = ("quarantine_record_id", "upload_id", "row_index", "raw_payload")

   
