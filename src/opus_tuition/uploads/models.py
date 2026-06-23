import os
import uuid
from datetime import datetime
from django.db import models

def get_upload_path(instance, filename):
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%dT%H%M%S")
    folder_path = now.strftime("%Y/%m/%d")
    
    name, extension = os.path.splitext(filename)
    return f"uploads/uploaded_files/{folder_path}/{name}{extension}"

class Upload(models.Model):
    UPLOAD_STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PROCESSING", "Processing"),
        ("COMPLETED", "Completed"),
        ("QUARANTINED", "Quarantined"),
        ("FAILED", "System Failure"),
    ]
    
    FILE_CATEGORY_CHOICES = [
        ("LESSON_LOG", "Lesson Log"),
        ("INVOICE", "Invoice"),
        ("ASSIGNMENT", "Assignment"),
        ("UNKNOWN", "Unknown"),
    ]

    upload_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    raw_file = models.FileField(upload_to=get_upload_path)
    upload_status = models.CharField(max_length=20, choices=UPLOAD_STATUS_CHOICES, default="PENDING")
    file_category = models.CharField(max_length=20, choices=FILE_CATEGORY_CHOICES, default="UNKNOWN")
    
    total_rows = models.IntegerField(default=0)
    accepted_rows = models.IntegerField(default=0)
    quarantined_rows = models.IntegerField(default=0)
    
    system_error_trace = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Upload {self.upload_id} - {self.upload_status}"

class CleanRecord(models.Model):
    clean_record_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    upload = models.ForeignKey(Upload, on_delete=models.CASCADE, related_name="clean_records")
    row_index = models.IntegerField()
    clean_payload = models.JSONField(help_text="Validated row data")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["row_index"]

    def __str__(self):
        return f"Clean Row {self.row_index} for Upload {self.upload_id}"

class QuarantineRecord(models.Model):
    quarantine_record_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    upload = models.ForeignKey(Upload, on_delete=models.CASCADE, related_name="quarantine_records")
    row_index = models.IntegerField()
    raw_payload = models.JSONField(help_text="Quarantined row data", null=True, blank=True)
    reason_code = models.CharField(max_length=100, help_text="e.g., DUPLICATE_RECORD, MALFORMED_DECIMAL")
    error_details = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True, auto_now=True)

    class Meta:
        ordering = ["row_index"]

    def __str__(self):
        return f"Quarantine Row {self.row_index} [Status: {self.is_resolved}]"

