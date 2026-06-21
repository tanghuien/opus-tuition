from django.db import models

# Create your models here.
class Tutor(models.Model):
    tutor_name = models.CharField(max_length=100)
    tutor_email = models.EmailField(max_length=254), unique=True)

class Student(models.Model):
    student_name = models.CharField(max_length=100)

