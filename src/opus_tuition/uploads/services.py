import pandas as pd
from .models import CleanRecord, QuarantineRecord
from .pipeline import generate_styled_excel_in_memory
from django.core.files.base import ContentFile

def generate_and_save_report(upload):
    """
    Unified logic to generate and save the report to the Upload model.
    """
    clean_records = CleanRecord.objects.filter(upload=upload)
    data_clean = [{"row_index": r.row_index, **r.clean_payload, "Reason Code": "", "Error Details": ""} for r in clean_records]
    
    quar_records = QuarantineRecord.objects.filter(upload=upload)
    data_quar = [{"row_index": r.row_index, **r.raw_payload, "Reason Code": r.reason_code, "Error Details": r.error_details} for r in quar_records]
    
    df_combined = pd.concat([pd.DataFrame(data_clean), pd.DataFrame(data_quar)], ignore_index=True)
    
    if not df_combined.empty:
        df_combined = df_combined.sort_values(by="row_index").drop(columns=["row_index"]).fillna("")

    # Use your existing styled excel generator
    buffer = generate_styled_excel_in_memory(df_combined, sheet_name="Full Report")
    
    # Save the buffer into the 'upload' model's report file field
    upload.report_file.save(f"report_{upload.id}.xlsx", ContentFile(buffer.getvalue()))

def generate_report_buffer(upload):
    """
    Generates the report in-memory and returns the buffer.
    No database 'save' operations occur here.
    """
    clean_records = CleanRecord.objects.filter(upload=upload)
    data_clean = [{"row_index": r.row_index, **r.clean_payload, "Reason Code": "", "Error Details": ""} for r in clean_records]
    
    quar_records = QuarantineRecord.objects.filter(upload=upload)
    data_quar = [{"row_index": r.row_index, **r.raw_payload, "Reason Code": r.reason_code, "Error Details": r.error_details} for r in quar_records]
    
    df_combined = pd.concat([pd.DataFrame(data_clean), pd.DataFrame(data_quar)], ignore_index=True)
    
    if not df_combined.empty:
        df_combined = df_combined.sort_values(by="row_index").drop(columns=["row_index"]).fillna("")
    
    # Generate the buffer once
    buffer = generate_styled_excel_in_memory(df_combined, sheet_name="Full Report")

    # Return the existing buffer
    return buffer