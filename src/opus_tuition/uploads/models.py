from django.db import models

# Create your models here.
class Upload(models.Model):
    class UploadStatus(models.TextChoices):
        Pending = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
    
    upload_id = models.AutoField(primary_key=True)
    filename = models.CharField(max_length=255)
    total_records = models.IntegerField(default=0)
    successful_records = models.IntegerField(default=0)
    failed_records = models.IntegerField(default=0)
    upload_status = models.CharField(
        max_length=20,
        choices=UploadStatus.choices,
        default=UploadStatus.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)

class Record(models.Model):
    class ValidationStatus(models.TextChoices):
        VALID = "valid", "Valid"
        INVALID = "invalid", "Invalid"
        QUARANTINED = "quarantined", "Quarantined"

    record_id = models.AutoField(primary_key=True)
    raw_data = models.JSONField()    
    validation_status = models.CharField(
        max_length=20,
        choices=ValidationStatus.choices
    )
    reason_code = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    upload = models.ForeignKey(
        "Upload", 
        on_delete=models.CASCADE, 
        related_name="records"
    )
