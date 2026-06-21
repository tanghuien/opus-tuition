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
from uploads.services import generate_report_buffer
from uploads.models import Upload
from uploads.utils import RowValidationError, validate_disk_file
from uploads.pipeline import identify_file_category
        
def run_automated_data_processing():
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
    file_queue.sort(key=lambda x: 0 if x["file_category"] == "ASSIGNMENT" else 1)

    # Loop through the file queue
    for item in file_queue:
        file_name = item["file_name"]
        file_path = item["file_path"]
        logging.info(f"--- Processing: {file_name} ---")
        
        try:
            # Checks for file validation error
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
            upload = Upload.objects.create(status="PENDING")

            with open(file_path, 'rb') as f:
                # Save the file object to the model's FileField
                # The first argument is the filename in the DB
                upload.raw_file.save(file_name, File(f), save=True)

            # Run data pipeline
            run_full_data_pipeline(upload, manual_path=file_path)
            
            # Generate processing report
            logging.info(f"Generating report for {file_name}...")
            report_buffer = generate_report_buffer(upload)
            
            # Move files based on upload status to their respective directory
            if upload.status == "COMPLETED":
                logger.info(f"Data processing completed with {upload.total_rows} records: {file_name}")
                shutil.move(file_path, os.path.join(processed_dir, f"cleaned_{file_name}"))
            elif upload.status == "QUARANTINED":
                logger.warning(f"Data processing finished with {upload.quarantined_rows} quarantine records: {file_name}")
                shutil.move(file_path, os.path.join(quarantine_dir, file_name))
            elif upload.status == "FAILED":
                logger.error(f"Data processing failed: {file_name}. Error: {upload.system_error_trace}")
                shutil.move(file_path, os.path.join(quarantine_dir, file_name))
            elif upload.status == "PENDING":
                logger.info(f"File waiting to be processed: {file_name}")
            elif upload.status == "PROCESSED":
                logger.info(f"File is currently being processed: {file_name}")
            else:
                logger.error(f"Unknown file processing state: {upload.status}")

            # Store generated report in reports folder
            if report_buffer:
                logger.info(f"Save report: {file_name}")
                
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