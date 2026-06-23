from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, JSONParser
from rest_framework import status
from django.utils import timezone
from django.db import connection, transaction
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from .serializers import UploadReportSerializer
from .pipeline import find_highlighted_header, identify_and_map_columns, validate_and_clean_row_dict, generate_styled_excel_in_memory
from django.shortcuts import render
import os
import pandas as pd
import json
import logging
from django.core.paginator import Paginator
from django.http import FileResponse, HttpResponse
from django.core.cache import cache
from django.db.models import F, Min, Max
import io
from django.shortcuts import get_object_or_404
from .models import Upload, CleanRecord, QuarantineRecord
from accounts.models import Tutor, Student
from assignments.models import Level, Subject, Assignment
from lesson_logs.models import LessonLog
from invoices.models import Invoice
from .utils import RowValidationError, RowValidationCollectionError, sanitize_for_json

logger = logging.getLogger("views.engine")

def validate_uploaded_file(file_obj):
    """
    Validates an uploaded file object before processing.
    Ensures the file exists, is within the size limit: 10MB, and has a valid Excel extension.
    """

    # Ensure file exists
    if not file_obj:
        return Response({"success": False, "error": {"code": "MISSING_FILE", "message": "No file found."}}, status=status.HTTP_400_BAD_REQUEST)
    
    # Ensure file size to not exceeds 10MB
    if file_obj.size > 10 * 1024 * 1024:
        return Response({"success": False, "error": {"code": "FILE_TOO_LARGE", "message": "File exceeds 10MB."}}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    
    # Validate file extension
    extension = os.path.splitext(file_obj.name)[1].lower()    
    if extension not in [".xlsx", ".xls"]:
        return Response({"success": False, "error": {"code": "INVALID_FILE_EXTENSION", "message": "Only Excel files are allowed."}}, status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
    
    return None

def run_full_data_pipeline(upload, manual_path = None):
    """
    This function ensures the data uploaded went through header algorithmn, data processing, and saving data into database.
    """


    # Use the manual path that is provided from automated data processing 
    # Else, use the file path uploaded on web
    data_path = manual_path if manual_path else upload.raw_file.path

    try:
        # An attempt to find header
        # Using existing find_highlighted_header logic
        sheet_name, rows_to_skip, header_found = find_highlighted_header(data_path)

        if header_found:
            # Case A: Header found via highlighting using visual formatting clues 
            # such as bolded text, coloured background, unique column values 
            logger.info(f"Header discovered via highlighting (Sheet: {sheet_name}, Skip: {rows_to_skip})")
            df = pd.read_excel(data_path, sheet_name=sheet_name, skiprows=rows_to_skip)
        else:
            # Case B: No header found, apply heuristic mapping to infer column structure
            logger.warning(f"No header found in {data_path}; falling back to heuristic column structure inference.")
            df = pd.read_excel(data_path, sheet_name=sheet_name, header=None)
        
        max_rows_to_check = min(30, len(df))
        df, inferred_category = identify_and_map_columns(df, max_rows_to_check)

        if inferred_category == "UNKNOWN":
            logger.error(f"Discovery failed: File category could not be inferred for {data_path}.")
            raise ValueError("File category could not be identified.")

        logger.info(f"Successfully identified file as: {inferred_category}")

        upload.file_category = inferred_category
        upload.total_rows = len(df)
        
        # 4. PROCESSING LOOP
        stored_id = {}
        stored_content = {}
        accepted_count, quarantined_count = 0, 0

        # loop through every single line in a table (DataFrame) one by one.
        for index, row in df.iterrows():
            # Make each row into a dictionary
            row_dict = row.to_dict()
            # Starts from the first line after header row
            first_data_row_index = index + 1
            
            # Force column header into string
            # If there is data in cell, converts into string.
            # If the data is empty, converts into None.
            sanitized_row = {str(column_header): (str(cell_value) if pd.notnull(cell_value) else None) for column_header, cell_value in row_dict.items()}
            
            try:
                with transaction.atomic():
                    cleaned_payload, file_category = validate_and_clean_row_dict(row_dict, inferred_category, stored_id, stored_content, first_data_row_index)

                    safe_payload = sanitize_for_json(cleaned_payload)

                    if file_category == "ASSIGNMENT":                        
                        tutor, _ = Tutor.objects.get_or_create(tutor_name=safe_payload["Tutor Name"], tutor_email=safe_payload["Contact Email"])
                        student, _ = Student.objects.get_or_create(student_name=safe_payload["Student Name"])
                        level, _ = Level.objects.get_or_create(level_name=safe_payload["Level"])
                        subject, _ = Subject.objects.get_or_create(subject_name=safe_payload["Subject"])
                        
                        assignment, created = Assignment.objects.update_or_create(
                            assignment_id=safe_payload["Assignment ID"],
                            defaults={
                                "hourly_rate": safe_payload["Hourly Rate (SGD)"],
                                "start_date": safe_payload["Start Date"],
                                "assignment_status": safe_payload["Status"],
                                "tutor": tutor,  
                                "student": student,
                                "level": level,
                                "subject": subject
                            }
                        )
                    elif file_category in ["LESSON_LOG", "INVOICE"]:
                        # Ensure the foreign key dependency is available
                        try:
                            assignment = Assignment.objects.get(assignment_id=safe_payload["Assignment ID"])
                        except Assignment.DoesNotExist:
                            raise RowValidationError(
                                code="REFERENCE_NOT_FOUND",
                                message=f"Assignment ID '{safe_payload['Assignment ID']}' not found. File could not be saved to database."
                            )
                            
                        if file_category == "LESSON_LOG":
                            lesson_log, created = LessonLog.objects.update_or_create(
                                log_id=safe_payload["Log ID"],
                                defaults={
                                    "session_date": safe_payload["Session Date"],
                                    "duration_in_hours": safe_payload["Duration (Hours)"],
                                    "attendance_status": safe_payload["Attendance Status"],
                                    "session_notes": safe_payload["Session Notes"],
                                    "fees_charged": safe_payload["Fees Charged"],
                                    "assignment": assignment
                                }
                            )                        
                        else: 
                            invoice, created = Invoice.objects.update_or_create(
                                invoice_id=safe_payload["Invoice ID"],
                                defaults={
                                    "invoice_date": safe_payload["Invoice Date"],
                                    "invoice_amount": safe_payload["Amount"],
                                    "payment_status": safe_payload["Payment Status"],
                                    "payment_date": safe_payload["Payment Date"],
                                    "payment_notes": safe_payload["Notes"],
                                    "assignment": assignment
                                }
                            ) 
                    
                    CleanRecord.objects.create(
                        upload=upload,
                        row_index=first_data_row_index,
                        clean_payload=safe_payload 
                    )
                    accepted_count += 1
            
            except RowValidationError as rve:
                # Handle single, critical validation stops
                safe_payload = sanitize_for_json(row_dict)
                QuarantineRecord.objects.create(
                    upload=upload,
                    row_index=first_data_row_index,
                    reason_code=rve.code,
                    error_details=rve.message,
                    raw_payload=safe_payload
                )
                quarantined_count += 1

            except RowValidationCollectionError as rvce:
                # Handle multiple non-critical errors found in one row
                safe_payload = sanitize_for_json(row_dict)
                            
                for error in rvce.errors:
                    QuarantineRecord.objects.create(
                        upload=upload,
                        row_index=first_data_row_index,
                        reason_code=error.get("code"),
                        error_details=error.get("message"),
                        raw_payload=safe_payload
                    )
                quarantined_count += 1

        upload.accepted_rows, upload.quarantined_rows = accepted_count, quarantined_count
        upload.upload_status = "COMPLETED" if quarantined_count == 0 else "QUARANTINED"
        upload.save()
        
    except Exception as e:
        upload.upload_status = "FAILED"
        upload.system_error_trace = str(e)
        upload.save()
        logger.exception(f"Caught by mistake: {e}")
        raise e

# ==========================================
# a. POST /api/upload/
# ==========================================
class FileUploadAPIView(APIView):
    """
    Endpoint to receive a file, runs the full pipeline, returns a processing report
    """
    
    # Accept file
    parser_classes = [MultiPartParser]
    serializer_class = UploadReportSerializer

    def post(self, request):
        # Extract all uploaded files from the request
        files = request.FILES.getlist("file")

        if not files:
            logger.error("No files uploaded.")
            return Response({"error": "No files uploaded."}, status=400)
        
        results = []
        logger.info(f"Processing {len(files)} file(s).")

        for file_obj in files:
            # Validate all file to check data size, file format etc        
            error_response = validate_uploaded_file(file_obj)

            if error_response is not None:
                logger.error(f"Validation failed for file: {file_obj.name}")
                
                # Extract the actual payload from the Response object
                results.append({
                    "file": file_obj.name,
                    **error_response.data  
                })
                continue            

            upload = Upload.objects.create(raw_file=file_obj, upload_status="PROCESSING")
            logger.info(f"Upload record created: ID {upload.upload_id} for file {file_obj.name}")

            # Finally, run data pipeline
            try:
                run_full_data_pipeline(upload)
                upload.refresh_from_db()
                results.append({
                    "success": True,
                    "report": UploadReportSerializer(upload).data
                })
                logger.info(f"Successfully processed upload ID {upload.upload_id}")
            except Exception as e:
                logger.exception(f"Pipeline failed for upload ID {upload.upload_id}: {str(e)}")
                upload.upload_status = "FAILED"
                upload.save()
                results.append({"success": False, "file": file_obj.name, "error": str(e)})
                
        return Response({"results": results}, status=status.HTTP_200_OK)

# ==========================================
# b. GET /api/records/ 
# ==========================================
class RecordsAPIView(APIView):
    """
    Returns clean records with filtering capabilities.
    """
    
    def get(self, request):
       # Extract the given parameters
        upload_id = request.query_params.get("upload_id")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        file_category = request.query_params.get("file_category")

        # Fetch all clean records
        clean_records = CleanRecord.objects.select_related("upload").all()

        if upload_id:
            clean_records = clean_records.filter(upload__upload_id=upload_id)
        if file_category:
            clean_records = clean_records.filter(upload__file_category__iexact=file_category)
        if start_date:
            clean_records = clean_records.filter(created_at__date__gte=start_date)
        if end_date:
            clean_records = clean_records.filter(created_at__date__lte=end_date)

        # Get the effective date range of the returned data for the report metadata
        # If no filters were applied, this shows the full range ofdata
        total_count = clean_records.count()
        date_range = clean_records.aggregate(start=Min("created_at"), end=Max("created_at"))

        results = [
            {
                "clean_record_id": record.clean_record_id,
                "upload_id": record.upload.upload_id,
                "created_at": record.created_at.isoformat(),
                "clean_payload": record.clean_payload
            } for record in clean_records
        ]


        return Response({
            "success": True,
            "count": total_count,
            "filters": {
                "date_range_range": {
                    "start": date_range["start"].isoformat() if date_range["start"] else None,
                    "end": date_range["end"].isoformat() if date_range["end"] else None,
                }
            },
            "results": results
        }, status=status.HTTP_200_OK)

# ==========================================
# c. GET /api/quarantine/
# ==========================================
class QuarantineRecordsAPIView(APIView):
    """
    Endpoint to returns quarantined rows with structured reason codes and details
    """

    def get(self, request):
        """Returns unresolved quarantined rows with structured reason codes."""
        # Fetch quarantined records that has yet resolved
        quarantine_records = QuarantineRecord.objects.filter(is_resolved=False)
        
        results = [
            {
                "upload_id": record.upload_id,
                "row_index": record.row_index,
                "reason_code": record.reason_code,
                "error_details": record.error_details,
                "raw_payload": record.raw_payload
            } for record in quarantine_records
        ]

        return Response({
            "success": True,
            "total_quarantined_items": len(results),
            "results": results
        }, status=status.HTTP_200_OK)

# ==========================================
# d. GET /api/report/:upload_id/
# ==========================================
class UploadReportAPIView(APIView):
    """"
    Endpoint to retrieve the full processing results for a specific upload.
    """

    def get(self, request, upload_id):
        """
        Fetches the processing report for a given upload_id.
        
        This view aggregates both "CleanRecord" (successful) and 
        "QuarantineRecord" (failed/flagged) entries, providing the user with 
        a complete audit trail and error feedback.
        """

        try:            
            upload = Upload.objects.get(upload_id=upload_id)
            
            logger.debug(f"Checking database for Upload {upload_id}")
            logger.debug(f"Clean records count in DB: {upload.clean_records.count()}")
            logger.debug(f"Quarantined records count in DB: {upload.quarantine_records.filter(is_resolved=False).count()}")
            
            return Response({
                "success": True, 
                "report": UploadReportSerializer(upload).data
            }, status=status.HTTP_200_OK)
        except Upload.DoesNotExist:
            return Response({
                "success": False,
                "error": {
                    "code": "NOT_FOUND", 
                    "message": f"Upload token sequence tracking index '{upload_id}' is invalid.", "timestamp": timezone.now().isoformat()}
            }, status=status.HTTP_404_NOT_FOUND)

class DeleteRecordAPIView(APIView):
    """"
    Endpoint to delete a specific record.
    """

    def delete(self, request, record_type, row_id):
        model_map = {
            "quarantine": QuarantineRecord,
            "cleaned": CleanRecord
        }
        
        target_model = model_map.get(record_type)
        if not target_model:
            return Response({"error": "Invalid record type"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            record = target_model.objects.get(pk=row_id)
            record.delete()
            return Response({"success": True}, status=status.HTTP_200_OK)
        except target_model.DoesNotExist:
            return Response({"error": "Record not found"}, status=status.HTTP_404_NOT_FOUND)

# ==========================================
# E. PATCH /api/quarantine/:row_id
# ==========================================
class QuarantineResolveAPIView(APIView):
    """"
    Endpoint to delete a specific record.
    """

    def patch(self, request, row_id):
        try:
            # Checks if quaratine records exists
            record = QuarantineRecord.objects.get(quarantine_record_id=row_id)
        except QuarantineRecord.DoesNotExist:
            # If it's not even in the database, log the error
            logger.error(f"Deletion failed: Record {row_id} does not exist in DB.")
            return Response({"success": False, "error": "Record already removed"}, status=status.HTTP_404_NOT_FOUND)
        
        # If it exists, means is for delete purpose
        if record.is_resolved:
            logger.info(f"Record {row_id} found but already marked as resolved.")
            return Response({"success": False, "error": "Record has already processed"}, status=status.HTTP_400_BAD_REQUEST)
            
        corrected_payload = request.data.get("corrected_payload") 
        if not corrected_payload:
            return Response({"success": False, "error": "Missing payload"}, status=status.HTTP_400_BAD_REQUEST)
            
        criteria_map = {
            'INVOICE': {'pk': 'Invoice ID', 'secondary': ["Student Name", "Invoice Date", "Payment Status", "Payment Date"]},
            'ASSIGNMENT': {'pk': 'Assignment ID', 'secondary': ["Tutor Name", "Student Name", "Start Date"]},
            'LESSON_LOG': {'pk': 'Log ID', 'secondary': ["Assignment ID", "Session Date", "Session Notes"]}
        }
        config = criteria_map.get(record.upload.file_category, {})
        pk_key = config.get('pk')
        secondary_keys = config.get('secondary', [])
  
        existing_records = CleanRecord.objects.filter(upload=record.upload)

        stored_id = {
            str(rec.clean_payload.get(pk_key, "")).strip().upper(): rec.row_index 
            for rec in existing_records 
            if pk_key in rec.clean_payload
        }

        stored_content = {
            tuple(str(rec.clean_payload.get(col, "")).strip().lower() for col in secondary_keys): rec.row_index 
            for rec in existing_records
        }

        try:
            # Re-validate the row
            cleaned_data, _ = validate_and_clean_row_dict(
                corrected_payload, 
                record.upload.file_category, 
                stored_id,
                stored_content, 
                record.row_index
            )

            # Verify the relationship exists 
            if record.upload.file_category in ["LESSON_LOG", "INVOICE"]:
                assignment_id = cleaned_data.get("Assignment ID")
                try:
                    assignment = Assignment.objects.get(assignment_id = assignment_id)
                except Assignment.DoesNotExist:
                    logger.warning(f"Assignment with ID {assignment_id} not found.")
                    return Response({
                        "success": False,
                        "error": {
                            "code": "REVALIDATION_FAILED",                             
                            "details": {
                                "reason": "REFERENCE_NOT_FOUND", 
                                "message": f"Assignment with ID {assignment_id} not found."
                            }}
                    }, status=status.HTTP_404_NOT_FOUND)

            # Sanitize using your recursive function to handled decimals/, lists, and tuples etc
            sanitized_payload = sanitize_for_json(cleaned_data)

            # Perform atomic transition
            with transaction.atomic():
                CleanRecord.objects.create(
                    upload=record.upload,
                    row_index=record.row_index,
                    clean_payload=sanitized_payload 
                )
                
                record.is_resolved = True
                record.resolved_at = timezone.now()
                record.save()
                
                upload = record.upload
                upload.accepted_rows = F('accepted_rows') + 1
                if upload.quarantined_rows > 0:
                    upload.quarantined_rows = F('quarantined_rows') - 1
                upload.save()

                # Clean up the errors: Delete the quarantine row
                QuarantineRecord.objects.filter(
                    upload=upload, 
                    row_index=record.row_index
                ).delete()
            
            return Response({"success": True, "message": "Successfully migrated to clean records."}, status=status.HTTP_200_OK)
            
        except RowValidationError as rve:
            return Response({
                "success": False,
                "error": {
                    "code": "REVALIDATION_FAILED", 
                    "details": {
                        "reason": rve.code, 
                        "message": rve.message
                    }
                }
            }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        
        except RowValidationCollectionError as rvce:
            return Response({
                "success": False,
                "errors": list(rvce.errors) # Ensure this is a list for JSON serialization
            }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        
        except Exception as e:
            return Response({
                "success": False, 
                "error": "An internal system error occurred during revalidation. Error: {e}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        
# ==========================================
# F. GET /health
# ==========================================
class SystemHealthAPIView(APIView):
    """
    Endpoint to view the system and database status
    """
    def get(self, request):
        try:
            # Testing if the database can execute the command
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return Response({
                "success": True, 
                "status": "HEALTHY", 
                "services": {
                    "database": "CONNECTED",
                    "file_system": "WRITABLE"
                },
                "timestamp": timezone.now().isoformat()
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                "success": False, 
                "error": {"code": "DATABASE_DOWN", "message": "Database pipeline structural connections dropped.", "details": str(e)}
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

def upload_page(request):
    """"
    Fetch only the uploads to display on the table
    Access to the UI page to upload file, view processing report and download records.
    """

    # Order is by the date the file upload was created
    upload_list = Upload.objects.all().order_by("-created_at")
    
    # Display 5 items per page
    paginator = Paginator(upload_list, 5)
    page_number = request.GET.get('page')
    uploads = paginator.get_page(page_number)
    
    # Pass only the paginated uploads to the context
    context = {
        "uploads": uploads,
    }
    
    return render(request, "upload_file.html", context)

def download_cleaned_records(request, upload_id):
    """
    Endpoint for downloading clean records only.
    """

    # Fetch the clean payloads from the database
    clean_payloads = CleanRecord.objects.filter(upload_id=upload_id).values_list("clean_payload", flat=True)
    
    if not clean_payloads:
        return HttpResponse("No records found to download.", status=status.HTTP_404_NOT_FOUND)
        
    # Convert to DataFrame
    df = pd.DataFrame(list(clean_payloads))
    
    # Create buffer
    buffer = generate_styled_excel_in_memory(df, sheet_name="Report")
    
    if buffer is None:
        return Response("Report generation failed.", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    # Send data from server to web browser
    return FileResponse(
        buffer, 
        as_attachment=True, 
        filename=f"Cleaned_Record_{upload_id[:8]}.xlsx"
    )

def download_full_report(request, upload_id):
    """
    Endpoint for downloading full processing report including reason code and error details.
    """

    # Fetch clean records
    clean_records = CleanRecord.objects.filter(upload_id=upload_id)
    # Using list comprehension ensures we capture the row_index for sorting
    data_clean = [{"Row Index": r.row_index, "Reason Code": "", "Error Details": "", **r.clean_payload} for r in clean_records]
    df_clean = pd.DataFrame(data_clean)

    # Fetch quarantined records
    quarantine_records = QuarantineRecord.objects.filter(upload_id=upload_id)
    data_quarantine = [{"Row Index": r.row_index, "Reason Code": r.reason_code, "Error Details": r.error_details, **r.raw_payload} for r in quarantine_records]
    df_quarantine = pd.DataFrame(data_quarantine)

    # Concat both clean records and quarantine records
    df_combined = pd.concat([df_clean, df_quarantine], ignore_index=True)
    
    upload_obj = get_object_or_404(Upload, pk=upload_id)
    
    # Extract only the filename from the path (e.g., "uploads/2026/data.csv" -> "data.csv")
    base_name = os.path.basename(upload_obj.raw_file.name)
    
    # Determines the final filename
    final_file_name = f"report_{base_name}"

    # Sort by the row_index to restore the original file sequence
    if not df_combined.empty:
        df_combined = df_combined.sort_values(by="Row Index")
    
    # Fill NaN values with empty strings
    df_combined = df_combined.fillna("")

    # 4. Generate report
    buffer = generate_styled_excel_in_memory(df_combined, sheet_name="Full Report")

    return FileResponse(buffer, as_attachment=True, filename=f"{final_file_name}")

