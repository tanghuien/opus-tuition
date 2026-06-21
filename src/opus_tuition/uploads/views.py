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
from .utils import RowValidationError, validate_disk_file, validate_uploaded_file, get_engine_for_file, sanitize_for_json

logger = logging.getLogger("views.engine")

def run_full_data_pipeline(upload, manual_path = None):
    # Use the manual path is provided for pipeline auto 
    # Else, use the file path uploaded
    data_path = manual_path if manual_path else upload.raw_file.path
    
    # Identify the engine used for the file format identified
    engine = get_engine_for_file(data_path)

    try:
        # 1. ATTEMPT HEADER DISCOVERY
        # Using existing find_highlighted_header logic
        sheet_name, rows_to_skip, header_found = find_highlighted_header(data_path)

        if header_found:
            # Case A: Header found via highlighting
            logger.info(f"Header discovered via highlighting (Sheet: {sheet_name}, Skip: {rows_to_skip})")
            df = pd.read_excel(data_path, sheet_name=sheet_name, skiprows=rows_to_skip, engine=engine)
        else:
            # Case B: No header found, apply heuristic mapping to infer column structure
            logger.warning(f"No header found in {data_path}; falling back to heuristic column structure inference.")
            df = pd.read_excel(data_path, sheet_name=sheet_name, header=None, engine=engine)
        
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

        all_valid_rows = []
        error_report = []

        for index, row in df.iterrows():
            row_dict = row.to_dict()
            human_row_idx = index + 1
            sanitized_row = {str(k): (str(v) if pd.notnull(v) else None) for k, v in row_dict.items()}
            
            try:
                with transaction.atomic():
                    cleaned_payload, file_category = validate_and_clean_row_dict(row_dict, inferred_category, stored_id, stored_content, human_row_idx)

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
                        # Standardize the lookup so both types behave the same way
                        try:
                            assignment = Assignment.objects.get(assignment_id=safe_payload["Assignment ID"])
                        except Assignment.DoesNotExist:
                            raise RowValidationError(
                                code="MISSING_RELATIONSHIP",
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
                        else: # INVOICE
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
                        row_index=human_row_idx,
                        clean_payload=safe_payload # Use the safe version
                    )
                    accepted_count += 1
            
            except RowValidationError as rve:
                safe_payload = sanitize_for_json(row_dict) # USE YOUR NEW FUNCTION

                QuarantineRecord.objects.create(
                    upload=upload,
                    row_index=human_row_idx,
                    reason_code=rve.code,
                    error_details=rve.message,
                    raw_payload=safe_payload
                )
                quarantined_count += 1

        upload.accepted_rows, upload.quarantined_rows = accepted_count, quarantined_count
        upload.status = "COMPLETED" if quarantined_count == 0 else "QUARANTINED"
        upload.save()
        
    except Exception as e:
        upload.status = "FAILED"
        upload.system_error_trace = str(e)
        upload.save()
        print(f"Caught by mistake: {e}")
        raise e


class FileUploadAPIView(APIView):
    parser_classes = [MultiPartParser]
    serializer_class = UploadReportSerializer


    def post(self, request):
        files = request.FILES.getlist("file")
        if not files:
            return Response({"error": "No files uploaded."}, status=400)
        
        results = []
        
        for file_obj in files:
            # 1. Validation
            if validate_uploaded_file(file_obj):
                results.append({"success": False, "file": file_obj.name, "error": "Validation failed"})
                continue

            # 2. Database Record
            upload = Upload.objects.create(raw_file=file_obj, status="PROCESSING")
            
            # 3. Pipeline
            try:
                run_full_data_pipeline(upload)
                upload.refresh_from_db()
                results.append({
                    "success": True,
                    "report": UploadReportSerializer(upload).data
                })
            except Exception as e:
                upload.status = "FAILED"
                upload.save()
                results.append({"success": False, "file": file_obj.name, "error": str(e)})
                
        return Response({"results": results}, status=200)
        
# ==========================================
# B. GET /records (with filters)
# ==========================================
class RecordsAPIView(APIView):
    """
    Returns clean records with filtering capabilities.
    """
    def get(self, request):
       # 1. Capture parameters (default to None if not provided)
        upload_id = request.query_params.get("upload_id")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        file_category = request.query_params.get("file_category")

        # 2. Base Query
        clean_records = CleanRecord.objects.select_related("upload").all()

        if upload_id:
            clean_records = clean_records.filter(upload__upload_id=upload_id)
        if file_category:
            clean_records = clean_records.filter(upload__file_category__iexact=file_category)
        if start_date:
            clean_records = clean_records.filter(created_at__date__gte=start_date)
        if end_date:
            clean_records = clean_records.filter(created_at__date__lte=end_date)

        # 4. Get the effective date range of the returned data for the report metadata
        # If no filters were applied, this shows the full range of your data
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
# C. GET /quarantine
# ==========================================
class QuarantineListAPIView(APIView):
    def get(self, request):
        """Returns unresolved quarantined rows with structured reason codes."""
        # Pull records that currently await manual operations corrections
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
# D. GET /report/:upload_id
# ==========================================
class UploadReportAPIView(APIView):
    def get(self, request, upload_id):
        try:            
            upload = Upload.objects.get(upload_id=upload_id)
            
            # print(f"DEBUG: Checking database for Upload {upload_id}")
            # print(f"DEBUG: Clean records count in DB: {upload.clean_records.count()}")
            # print(f"DEBUG: Quarantined records count in DB: {upload.quarantine_records.filter(is_resolved=False).count()}")
            
            return Response({
                "success": True, 
                "report": UploadReportSerializer(upload).data
            }, status=status.HTTP_200_OK)
        except Upload.DoesNotExist:
            return Response({
                "success": False,
                "error": {"code": "NOT_FOUND", "message": f"Upload token sequence tracking index '{upload_id}' is invalid.", "timestamp": timezone.now().isoformat()}
            }, status=status.HTTP_404_NOT_FOUND)

class DeleteRecordAPIView(APIView):
    def delete(self, request, record_type, row_id):
        try:
            if record_type == "quarantine":
                record = QuarantineRecord.objects.get(pk=row_id)
            elif record_type == "cleaned":
                record = CleanRecord.objects.get(pk=row_id)
            else:
                return Response({"error": "Invalid type"}, status=400)
            
            # CRITICAL: Force the delete and ensure it commits
            record.delete()
            
            # Verify it is gone
            return Response({"success": True}, status=200)
        except Exception as e:
            # Log the error so you can see it in your terminal
            # print(f"DEBUG: Delete failed for {record_type} ID {row_id}: {str(e)}")
            return Response({"success": False, "error": str(e)}, status=status.HTTP_404_NOT_FOUND)

# ==========================================
# E. PATCH /quarantine/:row_id
# ==========================================
class QuarantineResolveAPIView(APIView):
    parser_classes = [JSONParser]

    def patch(self, request, row_id):
        try:
            record = QuarantineRecord.objects.get(quarantine_record_id=row_id, is_resolved=False)
        except QuarantineRecord.DoesNotExist:
            return Response({"success": False, "error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
            
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

        # 2. PRIME THE SETS FROM DATABASE
        # This tells the validator what is already 'taken'
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
            # 1. Re-validate the row (Unpack the tuple returned by the function)
            cleaned_data, _ = validate_and_clean_row_dict(
                corrected_payload, 
                record.upload.file_category, 
                stored_id,
                stored_content, 
                record.row_index
            )

            # 2. NEW: Explicitly verify the relationship exists 
            # (If the record is a Lesson Log or Invoice)
            if record.upload.file_category in ["LESSON_LOG", "INVOICE"]:
                assignment_id = cleaned_data.get("Assignment ID")
                try:
                    assignment = Assignment.objects.get(assignment_id = assignment_id)
                except Assignment.DoesNotExist:
                    logger.warning(f"Assignment with ID {assignment_id} not found.")
                    return Response({
                        "success": False,
                        "error": {"code": "NOT_FOUND", "message": f"Assignment with ID {assignment_id} not found."}
                    }, status=status.HTTP_404_NOT_FOUND)

            # 2. Sanitize using your recursive function to handle Decimals/Tuples
            # This replaces the crashing json.loads(json.dumps(...))
            sanitized_payload = sanitize_for_json(cleaned_data)

            # 3. Perform atomic transition
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
            
            return Response({"success": True, "message": "Successfully migrated to clean records."}, status=status.HTTP_200_OK)
            
        except RowValidationError as rve:
            return Response({
                "success": False,
                "error": {"code": "REVALIDATION_FAILED", "details": {"reason": rve.code, "msg": rve.message}}
            }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

# ==========================================
# F. GET /health
# ==========================================
class SystemHealthAPIView(APIView):
    def get(self, request):
        try:
            # Check database query engine latency pipelines
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
    # 1. Fetch only the uploads for the table
    # We don't need all clean/quarantined records here, 
    # as the API call will fetch them individually.
    upload_list = Upload.objects.all().order_by("-created_at")
    
    # 2. Paginate: 5 items per page
    paginator = Paginator(upload_list, 5)
    page_number = request.GET.get('page')
    uploads = paginator.get_page(page_number)
    
    # 3. Pass only the paginated uploads to the context
    context = {
        "uploads": uploads,
    }
    
    return render(request, "upload_file.html", context)

def download_cleaned_records(request, upload_id):
    # 1. Fetch the payloads from the database
    # .values_list extracts just the JSON data, which is faster
    payloads = CleanRecord.objects.filter(upload_id=upload_id).values_list("clean_payload", flat=True)
    
    if not payloads:
        return HttpResponse("No records found to download.", status=404)
        
    # 2. Convert to DataFrame
    df = pd.DataFrame(list(payloads))
    
    # 3. Pass to your existing styling function
    buffer = generate_styled_excel_in_memory(df, sheet_name="Report")
    
    if buffer is None:
        return HttpResponse("Report generation failed.", status=500)
    
    # 4. Stream to browser
    return FileResponse(
        buffer, 
        as_attachment=True, 
        filename=f"Cleaned_Record_{upload_id[:8]}.xlsx"
    )

def download_full_report(request, upload_id):
    # 1. Fetch Clean
    clean_records = CleanRecord.objects.filter(upload_id=upload_id)
    # Using list comprehension ensures we capture the row_index for sorting
    data_clean = [{"row_index": r.row_index, **r.clean_payload, "Reason Code": "", "Error Details": ""} for r in clean_records]
    df_clean = pd.DataFrame(data_clean)

    # 2. Fetch Quarantined
    quar_records = QuarantineRecord.objects.filter(upload_id=upload_id)
    data_quar = [{"row_index": r.row_index, **r.raw_payload, "Reason Code": r.reason_code, "Error Details": r.error_details} for r in quar_records]
    df_quar = pd.DataFrame(data_quar)

    # 3. Combine and Sort
    # concat handles mismatched columns automatically
    df_combined = pd.concat([df_clean, df_quar], ignore_index=True)
    
    upload_obj = get_object_or_404(Upload, pk=upload_id)
    # Extract only the filename from the path (e.g., "uploads/2026/data.csv" -> "data.csv")
    base_name = os.path.basename(upload_obj.raw_file.name)
    
    # Prepend "Report_" to the name
    final_file_name = f"report_{base_name}"

    # Sort by the row_index to restore the original file sequence
    if not df_combined.empty:
        df_combined = df_combined.sort_values(by="row_index")
        # Drop the helper column if you don"t want it in the final file
        df_combined = df_combined.drop(columns=["row_index"])
    
    # Fill NaN values with empty strings
    df_combined = df_combined.fillna("")

    # 4. Generate
    buffer = generate_styled_excel_in_memory(df_combined, sheet_name="Full Report")
    return FileResponse(buffer, as_attachment=True, filename=f"{final_file_name}")

