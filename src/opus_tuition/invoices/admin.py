from django.contrib import admin
from .models import Invoice

# Register your models here.
@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_id", "get_invoice_date_iso", "invoice_amount", "payment_status", "get_payment_date_iso", "payment_notes", "assignment__assignment_id")
    list_filter = ("payment_status",)

    def get_invoice_date_iso(self, obj):
        return obj.invoice_date.strftime("%Y-%m-%d")

    get_invoice_date_iso.short_description = "Invoice Date"
    get_invoice_date_iso.admin_order_field = "invoice_date"

    def get_payment_date_iso(self, obj):
        # Check if the date exists
        if obj.payment_date:
            return obj.payment_date.strftime("%Y-%m-%d")
        # Return a blank string or a placeholder if there is no date
        return ""

    get_payment_date_iso.short_description = "Payment Date"
    get_payment_date_iso.admin_order_field = "payment_date"