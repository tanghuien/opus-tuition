from django.db import models

# Create your models here.
class Invoice(models.Model):
    class PaymentStatus(models.TextChoices):
        PAID = "Paid", "Paid"
        PENDING = "Pending", "Pending"
        OVERDUE = "Overdue", "Overdue"

    invoice_id = models.CharField(max_length=100, primary_key=True)
    invoice_date = models.DateField()
    invoice_amount = models.DecimalField(max_digits=19, decimal_places=4)
    payment_status = models.CharField(
        max_length=20, 
        choices=PaymentStatus.choices, 
        default=PaymentStatus.PENDING
    )
    payment_date = models.DateField(blank=True, null=True)
    payment_notes = models.TextField(blank=True, null=True)
    assignment = models.ForeignKey("assignments.Assignment", on_delete=models.CASCADE)