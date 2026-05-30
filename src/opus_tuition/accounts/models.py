from django.db import models

# Create your models here.
class Tutor(models.Model):
    tutor_id = models.CharField(max_length=100, primary_key=True)
    tutor_name = models.CharField(max_length=100)
    tutor_email = models.EmailField(unique=True)

class Student(models.Model):
    student_id = models.AutoField(primary_key=True)
    student_name = models.CharField(max_length=100)

