from django.db import models

# Create your models here.
class Level(models.Model):
    level_id = models.AutoField(primary_key=True)
    level_name = models.CharField(max_length=100)

class Subject(models.Model):
    subject_id = models.AutoField(primary_key=True)
    subject_name = models.CharField(max_length=100)

class Assignment(models.Model):
    class AssignmentStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        PENDING = "pending", "Pending"
        CANCELLED = "cancelled", "Cancelled"

    assignment_id = models.CharField(max_length=100, primary_key=True)
    hourly_rate = models.DecimalField(max_digits=19, decimal_places=4)
    start_date = models.DateField()
    assignment_status = models.CharField(
        max_length=20, 
        choices=AssignmentStatus.choices, 
        default=AssignmentStatus.PENDING
    )
    tutor = models.ForeignKey("accounts.Tutor", on_delete=models.CASCADE)
    student = models.ForeignKey("accounts.Student", on_delete=models.CASCADE)
    level = models.ForeignKey("Level", on_delete=models.CASCADE)
    subject = models.ForeignKey("Subject", on_delete=models.CASCADE)