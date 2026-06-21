from django.db import models

# Create your models here.
class LessonLog(models.Model):
    class AttendanceStatus(models.TextChoices):
        PRESENT = "Present", "Present"
        ABSENT = "Absent", "Absent"
        LATE = "Late", "Late"
        ABSENT_MC = "Absent-Mc", "Absent-Mc"

    log_id = models.CharField(max_length=100, primary_key=True)
    session_date = models.DateField()
    duration_in_hours = models.DecimalField(max_digits=19, decimal_places=1)
    attendance_status = models.CharField(
        max_length=20, 
        choices=AttendanceStatus.choices
    )
    session_notes = models.TextField()
    fees_charged = models.DecimalField(max_digits=19, decimal_places=4)
    assignment = models.ForeignKey("assignments.Assignment", on_delete=models.CASCADE)

