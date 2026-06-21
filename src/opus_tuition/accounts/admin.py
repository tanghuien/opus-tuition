from django.contrib import admin
from .models import Tutor, Student

# Register your models here.
@admin.register(Tutor)
class TutorAdmin(admin.ModelAdmin):
    list_display = ("id", "tutor_name", "tutor_email")

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("id", "student_name")
