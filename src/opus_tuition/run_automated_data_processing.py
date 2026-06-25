import os
import shutil
import pandas as pd
import sys
import django
import logging
from django.core.files import File

logger = logging.getLogger("run_automated_data_processing.engine")

# Initialize Django configuration environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "opus_tuition.settings")
django.setup()

from uploads.views import run_full_data_pipeline
from uploads.models import Upload, CleanRecord, QuarantineRecord
from uploads.pipeline import find_highlighted_header, identify_and_map_columns, generate_styled_excel_in_memory

# Create custom validation error
class FileValidationError(Exception):
    def __init__(self, message, code):
        self.message = message
        self.code = code
        super().__init__(self.message)

def validate_disk_file(file_path):
    """Validates file size and format constraints for uploaded files on disk."""
    if not os.path.exists(file_path):
        raise FileValidationError("File does not exist.", "FILE_NOT_FOUND")

    file_size = os.path.getsize(file_path)
    if file_size > 10 * 1024 * 1024:
        logger.warning(f"File validation failed: File {file_path} too large.")
        raise FileValidationError("File size exceeds 10MB.", "FILE_TOO_LARGE")
    elif file_size == 0:
        logger.warning(f"File validation failed: {file_path} is 0 bytes (empty).")
        raise FileValidationError("File is empty (0 bytes).", "ZERO_BYTE_FILE")

    allowed_extensions = (".xlsx", ".xls")
    file_extension = os.path.splitext(file_path)[1].lower()
    
    if file_extension not in allowed_extensions:
        logger.warning(f"File validation failed: Unsupported file extension '{file_extension}' for {file_path}.")
        raise FileValidationError("Only Excel files are allowed.", "INVALID_FILE_EXTENSION")
    

def identify_file_category(file_path):
    """Determine the file category of the excel file."""
    try:
        # Locate headers using layout highlighting.  
        # If fails, uses heuristic column mapping to infer the file category.
        sheet_name, rows_to_skip, header_found = find_highlighted_header(file_path)

        if header_found:
            logger.info(f"Header discovered via highlighting (Sheet: {sheet_name}, Skip: {rows_to_skip})")
            df = pd.read_excel(file_path, sheet_name=sheet_name, skiprows=rows_to_skip)
        else:
            logger.warning(f"No header found in {file_path}; Falling back to heuristic mapping.")
            df = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
        
        max_rows_to_check = min(30, len(df))
        df, inferred_category = identify_and_map_columns(df, max_rows_to_check)

        if inferred_category == "UNKNOWN":
            logger.error(f"Discovery failed: File category could not be inferred for {file_path}.")
            raise ValueError("File category could not be identified.")

        return inferred_category
    except Exception as e:
        logger.error(f"Failed to identify category for {file_path}: {e}", exc_info=True)
        raise

def generate_report_buffer(upload):
    """Generates the report in-memory and returns the bytes buffer."""
    clean_records = CleanRecord.objects.filter(upload=upload)
    data_clean = [{"Row Index": r.row_index, "Reason Code": "", "Error Details": "", **r.clean_payload} for r in clean_records]
    
    quarantine_records = QuarantineRecord.objects.filter(upload=upload)
    data_quarantine = [{"Row Index": r.row_index, "Reason Code": r.reason_code, "Error Details": r.error_details, **r.raw_payload} for r in quarantine_records]
    
    df_combined = pd.concat([pd.DataFrame(data_clean), pd.DataFrame(data_quarantine)], ignore_index=True)
    
    if not df_combined.empty:
        df_combined = df_combined.sort_values(by="Row Index")
    
    return generate_styled_excel_in_memory(df_combined, sheet_name="Full Report")

def run_automated_data_processing():
    """Runs background process to orchestrate the end-to-end data pipeline."""
    
    # Initialise path for raw files to be ingested by the pipeline
    raw_dir = "uploads/data/raw/"
    
    # Initialise path for successfully processed files with no quarantine records
    processed_dir = "uploads/data/processed/"
    
    # Initialise path for files containing quarantine records after processing    
    quarantine_dir = "uploads/data/quarantine/"
    
    # Initialise path for report containing both clean and quarantined records with error codes and details    
    report_dir = "uploads/data/report/" 

    # Create the directory if it doesn't exists
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(processed_dir, exist_ok=True)
    os.makedirs(quarantine_dir, exist_ok=True)
    os.makedirs(report_dir, exist_ok=True)

    raw_file_names = [file_name for file_name in os.listdir(raw_dir)]
  
    # Pre-sort: Identify file categories and prioritise "ASSIGNMENT" to ensure database foreign key dependency
    file_queue = []
    for file_name in raw_file_names:
        file_path = os.path.join(raw_dir, file_name)
        try:
            # Validate file sizes and file extension
            validate_disk_file(file_path)
            file_category = identify_file_category(file_path) 
            file_queue.append({"file_name": file_name, "file_path": file_path, "file_category": file_category})
            logger.info(f"File successfully categorised: {file_name} as {file_category}")
        except (FileValidationError, ValueError) as ve:
            logger.warning(f"Skipping preprocessing sorting for file {file_name}: {ve}")
            # Move it to quarantine_dir to avoid endless loops
            shutil.move(file_path, os.path.join(quarantine_dir, file_name))

    # Sort: "ASSIGNMENT" (0) comes before others (1) to resolve database foreign key dependency
    # ASSIGNMENT records must be inserted before INVOICE, LESSON_LOG or UNKNOWN records
    # to satisfy foreign key constraints
    file_queue.sort(key=lambda x: 0 if x["file_category"] == "ASSIGNMENT" else 1)

    for item in file_queue:
        file_name = item["file_name"]
        file_path = item["file_path"]
        file_category = item["file_category"]

        logger.info(f"--- Processing: {file_name} ({file_category}) ---")
        
        try:
            # Create tracking database upload trace
            upload = Upload.objects.create(upload_status="PROCESSING", file_category=file_category)

            with open(file_path, 'rb') as f:
                upload.raw_file.save(file_name, File(f), save=True)

            # Run data pipiline
            run_full_data_pipeline(upload)

            # Generate processing report and write the buffer out to disk
            report_buffer = generate_report_buffer(upload)
            report_out_path = os.path.join(report_dir, f"Report_{os.path.splitext(file_name)[0]}.xlsx")
            with open(report_out_path, 'wb') as f_out:
                f_out.write(report_buffer.getbuffer())

            # Move the raw files based on upload status to their respective directory
            if QuarantineRecord.objects.filter(upload=upload).exists():
                shutil.move(file_path, os.path.join(quarantine_dir, file_name))
                upload.upload_status = "QUARANTINED"
            else:
                shutil.move(file_path, os.path.join(processed_dir, file_name))
                upload.upload_status = "COMPLETED"
            
            upload.save()
            logger.info(f"Successfully finalized pipeline execution for: {file_name}")

        except Exception as e:
            logger.error(f"Critical execution block system failure for {file_name}: {e}", exc_info=True)
            upload.upload_status = "FAILED"
            upload.save()      

if __name__ == "__main__":
    run_automated_data_processing()
