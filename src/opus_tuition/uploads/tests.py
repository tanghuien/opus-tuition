from django.test import TestCase
from datetime import date
from decimal import Decimal
from .pipeline import (
    parse_single_date, parse_and_round_decimal, 
    validate_and_clean_row_dict, RowValidationError
)
from django.db import connection, transaction
from .models import Upload, CleanRecord, QuarantineRecord
from accounts.models import Tutor, Student
from assignments.models import Level, Subject, Assignment
from lesson_logs.models import LessonLog
from invoices.models import Invoice
from .utils import sanitize_for_json


class PipelineDataTests(TestCase):
    def setUp(self):
        # Create the upload object once so later all tests can use
        self.upload = Upload.objects.create(
            upload_status="PROCESSING",
            total_rows=0
        )

        self.tutor, _ = Tutor.objects.get_or_create(tutor_name="Mary Tan", tutor_email="mary@tutors.com")
        self.student, _ = Student.objects.get_or_create(student_name="Joshua Toh")
        self.level, _ = Level.objects.get_or_create(level_name="Primary 1")
        self.subject, _ = Subject.objects.get_or_create(subject_name="Science")
        
        # Update exisitng or create the assignment object so later all tests can use
        self.assignment, _ = Assignment.objects.update_or_create(
            assignment_id="ASG-111",
            hourly_rate=45.00,
            start_date=date(2026, 6, 19),
            assignment_status="Active",
            tutor=self.tutor,
            student=self.student,
            level=self.level,
            subject=self.subject
        )
    
    # I. Date Normalisation 
    def test_parse_single_date_variations(self):    
        test_cases = [
            ("2025-03-12", "2025-03-12"),
            ("01/05/2025", "2025-01-05"),
            ("25-04-2025", "2025-04-25"),
            ("12 Feb 2025", "2025-02-12"),
            ("July 7, 2025", "2025-07-07"),
            ("15-Oct-2025", "2025-10-15"),
            ("12/03/25", "2025-03-12")
        ]

        for raw, expected in test_cases:
            parsed, success = parse_single_date(raw)
            
            self.assertEqual(parsed, expected)

    # M. Duplicate Detection for all file category
    def test_assignment_duplicate_id(self):
        stored_id = {}
        stored_content = {}
        
        row = {
            "Assignment ID": "TAS-123",
            "Tutor Name": "Mary Tan",
            "Student Name": "Joshua Toh",
            "Subject": "Science",
            "Level": "Primary 1",
            "Hourly Rate (SGD)": 45,
            "Start Date": "2026-08-12",        
            "Status": "Active",
            "Contact Email": "mary.t@tutors.com"
        }
        
    
        validate_and_clean_row_dict(row, "ASSIGNMENT", stored_id, stored_content, 1)
        
        with self.assertRaises(RowValidationError) as rve:
            validate_and_clean_row_dict(row, "ASSIGNMENT", stored_id, stored_content, 2)
        
        self.assertEqual(rve.exception.code, "DUPLICATE_ID")
        
    def test_lesson_log_duplicate_id(self):
        stored_id = {}
        stored_content = {}
        
        row = {
            "Log ID": "LOG-122",
            "Assignment ID": "TAS-123" ,
            "Session Date": "2026-08-12",        
            "Duration (Hours)": 2.0,
            "Attendance Status": "Present",
            "Session Notes": "Timed practice paper",
            "Fees Charged": 45
        }
        
        validate_and_clean_row_dict(row, "LESSON_LOG", stored_id, stored_content, 1)
        
        with self.assertRaises(RowValidationError) as rve:
            validate_and_clean_row_dict(row, "LESSON_LOG", stored_id, stored_content, 2)
        
        self.assertEqual(rve.exception.code, "DUPLICATE_ID")
    
    def test_invoice_duplicate_id(self):
        stored_id = {}
        stored_content = {}
        
        row = {
            "Invoice ID": "INV-123",
            "Assignment ID": "TAS-123" ,
            "Student Name": "Joshua Toh",
            "Invoice Date": "2026-07-07",
            "Amount": 165,
            "Payment Status": "Pending",
            "Payment Date": "",
            "Notes": "",
            "Duration (Hours)": 2.0
        }
    
        validate_and_clean_row_dict(row, "INVOICE", stored_id, stored_content, 1)
        
        with self.assertRaises(RowValidationError) as rve:
            validate_and_clean_row_dict(row, "INVOICE", stored_id, stored_content, 2)
        
        self.assertEqual(rve.exception.code, "DUPLICATE_ID")

    def test_assignment_duplicate_content(self):
        stored_id = {}
        stored_content = {}
        
        # two rows with different "Assignment ID", but similar "Tutor Name", "Student Name", and "Start Date"
        row1 = {
            "Assignment ID": "TAS-123",
            "Tutor Name": "Mary Tan",
            "Student Name": "Joshua Toh",
            "Subject": "Science",
            "Level": "Primary 1",
            "Hourly Rate (SGD)": 45,
            "Start Date": "2026-08-12",        
            "Status": "Active",
            "Contact Email": "mary.t@tutors.com"
        }
        
        row2 = {
            "Assignment ID": "TAS-321",
            "Tutor Name": "Mary Tan",
            "Student Name": "Joshua Toh",
            "Subject": "English",
            "Level": "Primary 6",
            "Hourly Rate (SGD)": 45,
            "Start Date": "2026-08-12",        
            "Status": "Inactive",
            "Contact Email": "mary.t@tutors.com"
        }
    
        validate_and_clean_row_dict(row1, "ASSIGNMENT", stored_id, stored_content, 1)
        
        with self.assertRaises(RowValidationError) as rve:
            validate_and_clean_row_dict(row2, "ASSIGNMENT", stored_id, stored_content, 2)
        
        self.assertEqual(rve.exception.code, "DUPLICATE_CONTENT")
    
    def test_lesson_log_duplicate_content(self):
        stored_id = {}
        stored_content = {}
        
        # two rows with different "Log ID", but similar "Assignment ID", "Session Date", and "Session Notes"
        row1 = {
            "Log ID": "LOG-122",
            "Assignment ID": "TAS-123" ,
            "Session Date": "2026-08-12",        
            "Duration (Hours)": 2.0,
            "Attendance Status": "Present",
            "Session Notes": "Timed practice paper",
            "Fees Charged": 45
        }

        row2 = {
            "Log ID": "LOG-221",
            "Assignment ID": "TAS-123" ,
            "Session Date": "2026-08-12",        
            "Duration (Hours)": 1.0,
            "Attendance Status": "Absent",
            "Session Notes": "Timed practice paper",
            "Fees Charged": 100
        }
        
        validate_and_clean_row_dict(row1, "LESSON_LOG", stored_id, stored_content, 1)
        
        with self.assertRaises(RowValidationError) as rve:
            validate_and_clean_row_dict(row2, "LESSON_LOG", stored_id, stored_content, 2)
        
        self.assertEqual(rve.exception.code, "DUPLICATE_CONTENT")
    
    def test_invoice_duplicate_content(self):
        stored_id = {}
        stored_content = {}
        
        # two rows with different "Invoice ID", but similar "Student Name", "Invoice Date", "Payment Date"
        row1 = {
            "Invoice ID": "INV-123",
            "Assignment ID": "TAS-123" ,
            "Student Name": "Joshua Toh",
            "Invoice Date": "2026-07-07",
            "Amount": 165,
            "Payment Status": "Paid",
            "Payment Date": "2026-07-08",
            "Notes": "",
            "Duration (Hours)": 2.0
        }

        row2 = {
            "Invoice ID": "INV-321",
            "Assignment ID": "TAS-123" ,
            "Student Name": "Joshua Toh",
            "Invoice Date": "2026-07-07",
            "Amount": 225,
            "Payment Status": "Paid",
            "Payment Date": "2026-07-08",
            "Notes": "Cheque",
            "Duration (Hours)": 1.0
        }
    
        validate_and_clean_row_dict(row1, "INVOICE", stored_id, stored_content, 1)
        
        with self.assertRaises(RowValidationError) as rve:
            validate_and_clean_row_dict(row2, "INVOICE", stored_id, stored_content, 2)
        
        self.assertEqual(rve.exception.code, "DUPLICATE_CONTENT")

    # N. Required Field Validation     
    def test_assignment_required_fields(self):
        valid_row = {
            "Assignment ID": self.assignment.assignment_id,
            "Tutor Name": "Mary Tan",
            "Student Name": "Joshua Toh",
            "Subject": "Science",
            "Level": "Primary 1",
            "Hourly Rate (SGD)": 45,
            "Start Date": "2026-08-12",        
            "Status": "Active",
            "Contact Email": "mary.t@tutors.com"
        }

        invalid_row = {
            "Assignment ID": "LOG-123", "Session Date": "2026-06-19",
        }

        batch = [
            {"data": valid_row, "category": "ASSIGNMENT", "idx": 1},
            {"data": invalid_row, "category": "ASSIGNMENT", "idx": 2}
        ]
        
        # 3. Execution
        for item in batch:
            try:
                cleaned, _ = validate_and_clean_row_dict(item["data"], item["category"], {}, {}, item["idx"])
                safe_payload = sanitize_for_json(cleaned)
                CleanRecord.objects.create(upload=self.upload, row_index=item["idx"], clean_payload=safe_payload)
            except RowValidationError as rve:
                QuarantineRecord.objects.create(
                    upload=self.upload, row_index=item["idx"],
                    reason_code=rve.code, error_details=rve.message,
                    raw_payload=item["data"]
                )

        # 4. Verification
        self.assertEqual(CleanRecord.objects.count(), 1)
        self.assertEqual(QuarantineRecord.objects.count(), 1)
        
        # Confirm specifically that the fail was due to missing fields
        quarantine = QuarantineRecord.objects.get(row_index=2)
        self.assertEqual(quarantine.reason_code, "NULL_FIELD")

    def test_lesson_log_batch_required_fields(self):
        valid_row = {
            "Log ID": "LOG-122",
            "Assignment ID": "TAS-123" ,
            "Session Date": "2026-08-12",        
            "Duration (Hours)": 2.0,
            "Attendance Status": "Present",
            "Session Notes": "Timed practice paper",
            "Fees Charged": 45
        }

        invalid_row = {
            "Log ID": "LOG-123", "Session Date": "2026-06-19",
        }

        batch = [
            {"data": valid_row, "category": "LESSON_LOG", "idx": 1},
            {"data": invalid_row, "category": "LESSON_LOG", "idx": 2}
        ]
        
        # 3. Execution
        for item in batch:
            try:
                cleaned, _ = validate_and_clean_row_dict(item["data"], item["category"], {}, {}, item["idx"])
                safe_payload = sanitize_for_json(cleaned)
                CleanRecord.objects.create(upload=self.upload, row_index=item["idx"], clean_payload=safe_payload)
            except RowValidationError as rve:
                QuarantineRecord.objects.create(
                    upload=self.upload, row_index=item["idx"],
                    reason_code=rve.code, error_details=rve.message,
                    raw_payload=item["data"]
                )

        # 4. Verification
        self.assertEqual(CleanRecord.objects.count(), 1)
        self.assertEqual(QuarantineRecord.objects.count(), 1)
        
        # Confirm specifically that the fail was due to missing fields
        quarantine = QuarantineRecord.objects.get(row_index=2)
        self.assertEqual(quarantine.reason_code, "NULL_FIELD")

    def test_invoice_batch_required_fields(self):
        valid_row = {
            "Invoice ID": "INV-123",
            "Assignment ID": "TAS-123" ,
            "Student Name": "Joshua Toh",
            "Invoice Date": "2026-07-07",
            "Amount": 165,
            "Payment Status": "Paid",
            "Payment Date": "2026-07-08",
            "Notes": "",
            "Duration (Hours)": 2.0
        }
        # Missing required fields (Assignment ID is missing, which is a required relational field)
        invalid_row = {
            "INV ID": "INV-123"
        }

        batch = [
            {"data": valid_row, "category": "INVOICE", "idx": 1},
            {"data": invalid_row, "category": "INVOICE", "idx": 2}
        ]
        
        # 3. Execution
        for item in batch:
            try:
                cleaned, _ = validate_and_clean_row_dict(item["data"], item["category"], {}, {}, item["idx"])
                safe_payload = sanitize_for_json(cleaned)
                CleanRecord.objects.create(upload=self.upload, row_index=item["idx"], clean_payload=safe_payload)
            except RowValidationError as rve:
                QuarantineRecord.objects.create(
                    upload=self.upload, row_index=item["idx"],
                    reason_code=rve.code, error_details=rve.message,
                    raw_payload=item["data"]
                )

        # 4. Verification
        self.assertEqual(CleanRecord.objects.count(), 1)
        self.assertEqual(QuarantineRecord.objects.count(), 1)
        
        # Confirm specifically that the fail was due to missing fields
        quarantine = QuarantineRecord.objects.get(row_index=2)
        self.assertEqual(quarantine.reason_code, "NULL_FIELD")

    # O. Currency Symbol Stripping
    def test_parse_and_round_decimal(self):
        self.assertEqual(parse_and_round_decimal("$1,250.5043"), Decimal("1250.5043"))
        self.assertEqual(parse_and_round_decimal("SGD 500"), Decimal("500.00"))

    # P. Quarantine Reason Code Generation
    def test_quarantine_null_record(self):
        # all fields are missing
        with self.assertRaises(RowValidationError) as cm:
            validate_and_clean_row_dict({}, "INVOICE", {}, {}, 1)
        self.assertEqual(cm.exception.code, "NULL_RECORD")

    def test_quarantine_null_field(self):
        # missing fields except assignment id
        with self.assertRaises(RowValidationError) as cm:
            validate_and_clean_row_dict({"Assignment ID": "TAS-001"}, "ASSIGNMENT", {}, {}, 1)
        self.assertEqual(cm.exception.code, "NULL_FIELD")

    def test_quarantine_invalid_enum(self):
        row = {
            "Invoice ID": "INV-123",
            "Assignment ID": "TAS-123" ,
            "Student Name": "Joshua Toh",
            "Invoice Date": "2026-07-07",
            "Amount": 165,
            # "Missing" is not in the PaymentStatus Enum (paid, overdue, pending)
            "Payment Status": "Missing", 
            "Payment Date": "",
            "Notes": "",
            "Duration (Hours)": 2.0
        }

        with self.assertRaises(RowValidationError) as cm:
            validate_and_clean_row_dict(row, "INVOICE", {}, {}, 1)
        self.assertEqual(cm.exception.code, "INVALID_ENUM")

    def test_quarantine_invalid_date(self):
        row = {
            "Invoice ID": "INV-123",
            "Assignment ID": "TAS-123" ,
            "Student Name": "Joshua Toh",
            # date format is not part of the format that could parse to YYYY-MM-DD
            "Invoice Date": "9 September 2026",
            "Amount": 165,
            "Payment Status": "Pending", 
            "Payment Date": "",
            "Notes": "",
            "Duration (Hours)": 2.0
        }

        with self.assertRaises(RowValidationError) as cm:
            validate_and_clean_row_dict(row, "INVOICE", {}, {}, 1)
        self.assertEqual(cm.exception.code, "INVALID_DATE")

