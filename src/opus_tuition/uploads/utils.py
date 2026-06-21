import os
import logging
from rest_framework.response import Response
from rest_framework import status
from decimal import Decimal
import numpy as np
import pandas as pd

logger = logging.getLogger("utils.engine")

class RowValidationError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(self.message)

def get_engine_for_file(file_path):
    extension = os.path.splitext(file_path)[1].lower()
    if extension.endswith(".xlsx"):
        return "openpyxl"
    elif extension.endswith(".xls"):
        return "xlrd"
    return None

def validate_disk_file(file_path):
    # Checks if file size exceeded 10 MB
    file_size = os.path.getsize(file_path)
    if file_size > 10 * 1024 * 1024:
        logger.warning(f"File validation failed: File {file_path} too large ({file_size} bytes).")
        return Response({"success": False, "error": {"code": "FILE_TOO_LARGE", "message": "File exceeds 10MB."}}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
   
    # Check if the file extension is .xlsx or .xls.
    allowed_extensions = (".xlsx", ".xls")
    file_extension= os.path.splitext(file_path)[1].lower()
    
    if file_extension not in allowed_extensions:
        logger.warning(f"File validation failed: Unsupported file extension '{file_extension}' for file {file_path}.")
        return Response(
            {"success": False, "error": {"code": "INVALID_FILE_EXTENSION", "message": "Only Excel files are allowed."}}, 
            status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        )

    # Structural Integrity Check: .xlsx and .xls files in ZIP format. 
    # Checks if the file is not corrupted or mislabeled.
    # try:
    #     with zipfile.ZipFile(file_path, 'r') as z:
    #         # If this succeeds, the file is a valid ZIP archive (OpenXML)
    #         pass
    # except (zipfile.BadZipFile, zipfile.LargeZipFile) as e:
    #     logger.error(f"File validation failed: File {file_path} is corrupted or not a valid Excel structure. Error: {e}")
    #     return Response(
    #         {"success": False, "error": {"code": "INVALID_FILE_STRUCTURE", "message": "File is corrupted or not a valid Excel file."}}, 
    #         status=status.HTTP_400_BAD_REQUEST
    #     )
    
    # logger.info(f"File {file_path} passed full validation.")
    # return None

def validate_uploaded_file(file_obj):
    if not file_obj:
        return Response({"success": False, "error": {"code": "MISSING_FILE", "message": "No file found."}}, status=status.HTTP_400_BAD_REQUEST)
    if file_obj.size > 10 * 1024 * 1024:
        return Response({"success": False, "error": {"code": "FILE_TOO_LARGE", "message": "File exceeds 10MB."}}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    extension = os.path.splitext(file_obj.name)[1].lower()
    if extension not in [".xlsx", ".xls"]:
        return Response({"success": False, "error": {"code": "INVALID_FILE_EXTENSION", "message": "Only Excel files are allowed."}}, status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
    return None

def sanitize_for_json(obj):
    """Recursively convert data to JSON-serializable formats."""
    if isinstance(obj, dict):
        return {key: sanitize_for_json(value) for key, value in obj.items()} # Sanitize dictionary values to ensure compatibility with JSON serialization
    elif isinstance(obj, list):
        return [sanitize_for_json(var) for var in obj] # Sanitize each item in the list for JSON serialization
    elif isinstance(obj, Decimal):
        return float(obj)  # Convert Decimal to float for JSON
    elif isinstance(obj, (np.float64, np.int64)):
        return obj.item()  # Convert numpy types to native Python
    elif pd.isna(obj):
        return None        # Convert NaN to JSON null
    return obj

