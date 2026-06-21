from django.db import models

# Create your models here.
class Level(models.Model):
    level_name = models.CharField(max_length=100)

    def __str__(self):
        return self.level_name

class Subject(models.Model):
    subject_name = models.CharField(max_length=100)

    def __str__(self):
        return self.subject_name

class Assignment(models.Model):
    class AssignmentStatus(models.TextChoices):
        ACTIVE = "Active", "Active"
        INACTIVE = "Inactive", "Inactive"
        PENDING = "Pending", "Pending"

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