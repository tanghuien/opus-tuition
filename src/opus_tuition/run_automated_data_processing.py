import os
import shutil
import pandas as pd
import sys
import django
import traceback
import logging
from django.core.files import File

logger = logging.getLogger("run_automated_data_processing.engine")

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "opus_tuition.settings")
django.setup()

from uploads.views import run_full_data_pipeline
from uploads.models import Upload, CleanRecord, QuarantineRecord
from uploads.utils import RowValidationError
from uploads.pipeline import find_highlighted_header, identify_and_map_columns, generate_styled_excel_in_memory

def validate_disk_file(file_path):
    """
    Validates file size and format constraints for uploaded files on disk.

    Args:
        file_path (str): The absolute path to the file to be validated.

    Returns:
        Response: If the file size exceed 10 MB or file extension is not .xlsx and .xlsx. format
    """

    # Checks if file size exceeded 10 MB
    file_size = os.path.getsize(file_path)
    if file_size > 10 * 1024 * 1024:
        logger.warning(f"File validation failed: File {file_path} too large ({file_size} bytes).")
        return Response({"success": False, "error": {"code": "FILE_TOO_LARGE", "message": "File exceeds 10MB."}}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
   
    # Only accepts if the file extension is .xlsx or .xls. format
    allowed_extensions = (".xlsx", ".xls")
    file_extension= os.path.splitext(file_path)[1].lower()
    
    if file_extension not in allowed_extensions:
        logger.warning(f"File validation failed: Unsupported file extension '{file_extension}' for file {file_path}.")
        return Response(
            {"success": False, "error": {"code": "INVALID_FILE_EXTENSION", "message": "Only Excel files are allowed."}}, 
            status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        )

def identify_file_category(file_path):
    """
    Determine the file category of the excel file.

    This function attempts to locate headers using layout highlighting. If that 
    fails, it uses heuristic column mapping to infer the file type.

    Args:
        file_path (str): The absolute path to the file for the headers to be determined.

    Returns:
        str: The identified category (e.g., "ASSIGNMENT", "LESSON_LOGS", "INVOICE", "UNKNOWN").

    Raises:
        ValueError: If the file category cannot be determined after heuristic analysis.
        Exception: Re-raises unexpected errors after logging them for observability.
    """
    
    try:
        # Using existing find_highlighted_header logic
        sheet_name, rows_to_skip, header_found = find_highlighted_header(file_path)

        if header_found:
            # Case A: Header found via highlighting
            logger.info(f"Header discovered via highlighting (Sheet: {sheet_name}, Skip: {rows_to_skip})")
            df = pd.read_excel(file_path, sheet_name=sheet_name, skiprows=rows_to_skip)
        else:
            # Case B: No header found, apply heuristic mapping to infer column structure
            logger.warning(f"No header found in {file_path}; Falling back to heuristic column structure inference.")
            df = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
        
        max_rows_to_check = min(30, len(df))
        df, inferred_category = identify_and_map_columns(df, max_rows_to_check)

        if inferred_category == "UNKNOWN":
            logger.error(f"Discovery failed: File category could not be inferred for {file_path}.")
            raise ValueError("File category could not be identified.")

        logger.info(f"Successfully identified file as: {inferred_category}")

        return inferred_category

    except Exception as e:
        logger.error(f"Failed to process {file_path}: {e}", exc_info=True)
        raise

def generate_report_buffer(upload):
    """
    Generates the report in-memory and returns the buffer.
    """
    
    clean_records = CleanRecord.objects.filter(upload=upload)
    data_clean = [{"Row Index": r.row_index, "Reason Code": "", "Error Details": "", **r.clean_payload} for r in clean_records]
    
    quarantine_records = QuarantineRecord.objects.filter(upload=upload)
    data_quarantine = [{"Row Index": r.row_index, "Reason Code": r.reason_code, "Error Details": r.error_details, **r.raw_payload} for r in quarantine_records]
    
    df_combined = pd.concat([pd.DataFrame(data_clean), pd.DataFrame(data_quarantine)], ignore_index=True)
    
    if not df_combined.empty:
        df_combined = df_combined.sort_values(by="Row Index")
    
    # Generate the buffer 
    buffer = generate_styled_excel_in_memory(df_combined, sheet_name="Full Report")

    # Return the existing buffer
    return buffer

def run_automated_data_processing():
    """
    Runs background process to orchestrates the end-to-end data pipeline: ingestion, validation, and database persistence.

    This function scans the raw directory for Excel files, categorizes them based on 
    business rules, and processes them in an order that respects database foreign 
    key dependencies. After processing, it moves files to success/quarantine 
    directories and generates a comprehensive Excel report of the results.
    """

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

    # Retrieves all files in the raw file directory thats is .xlsx and .xls format
    raw_file_names = [file_name for file_name in os.listdir(raw_dir) if file_name.endswith((".xlsx", ".xls"))]
  
    # Pre-sort: Identify file categories and prioritise "ASSIGNMENT" to ensure database foreign key dependency
    file_queue = []
    for file_name in raw_file_names:
        file_path = os.path.join(raw_dir, file_name)
        file_category = identify_file_category(file_path) 
        file_queue.append({"file_name": file_name, "file_path": file_path, "file_category": file_category})
        logging.info(f"File is successfully categorised: {file_name} as {file_category}")
    
    # Sort: "ASSIGNMENT" (0) comes before others (1) to resolve database foreign key dependency
    # Critical: Enforce processing order to satisfy foreign key constraints
    # ASSIGNMENT records must be inserted before INVOICE, LESSON_LOG or UNKNOWN records
    # to prevent database integrity errors during relational mapping
    file_queue.sort(key=lambda x: 0 if x["file_category"] == "ASSIGNMENT" else 1)

    for item in file_queue:
        file_name = item["file_name"]
        file_path = item["file_path"]


        logging.info(f"--- Processing: {file_name} ---")
        
        try:
            file_validation_error = validate_disk_file(file_path)

            # Log it if there is file validation error
            if file_validation_error is not None:
                logger.warning(
                    f"Validation failed for file: {file_name} | "
                    f"Error Details: {file_validation_error}"
                )
                # Skip this file but continue processing the rest of the queue
                continue
                
            # Create upload record in the database to indicate file is current waiting to be processed
            upload = Upload.objects.create(upload_status="PENDING")

            with open(file_path, 'rb') as f:
                # Save the file object to the model's FileField
                # The first argument is the filename in the DB
                upload.raw_file.save(file_name, File(f), save=True)

            # Run data pipeline
            run_full_data_pipeline(upload, manual_path=file_path)
            
            # Move the raw files based on upload status to their respective directory
            if upload.upload_status == "COMPLETED":
                logger.info(f"Data processing completed with {upload.total_rows} records: {file_name}")
                shutil.move(file_path, os.path.join(processed_dir, file_name))
            elif upload.upload_status == "QUARANTINED":
                logger.warning(f"Data processing finished with {upload.quarantined_rows} quarantine records: {file_name}")
                shutil.move(file_path, os.path.join(quarantine_dir, file_name))
            elif upload.upload_status == "FAILED":
                logger.error(f"Data processing failed: {file_name}. Error: {upload.system_error_trace}")
                shutil.move(file_path, os.path.join(quarantine_dir, file_name))
            elif upload.upload_status == "PENDING":
                logger.info(f"File waiting to be processed: {file_name}")
            elif upload.upload_status == "PROCESSED":
                logger.info(f"File is currently being processed: {file_name}")
            else:
                logger.error(f"Unknown file processing state: {upload.upload_status}")

            # Generate processing report
            logging.info(f"Generating report for {file_name}...")
            report_buffer = generate_report_buffer(upload)
            
            # Store generated report in reports folder
            if report_buffer:
                logger.info(f"Save report: {file_name}")
                
                # Initialise path to store the processing report
                destination = os.path.join(report_dir, f"report_{file_name}")
                
                # Store the buffer content in the destination directory
                with open(destination, 'wb') as report:
                    report.write(report_buffer.getvalue())
                
                logger.info(f"Report successfully saved to: {destination}")

        except Exception as e:
            logger.error(
                f"Unexpected crash during validation of file: {file_name} | "
                f"Exception: {str(e)}"
            )
            shutil.move(file_path, os.path.join(quarantine_dir, file_name))
            continue

if __name__ == "__main__":
    run_automated_data_processing()