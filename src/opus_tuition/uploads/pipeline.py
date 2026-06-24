import os
import logging
import openpyxl
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import pandas as pd
from django.db import transaction
from django.conf import settings
from .models import Upload, QuarantineRecord, CleanRecord
from .utils import RowValidationError, RowValidationCollectionError
from enum import Enum, StrEnum
import io
from uploads.constants import *

logger = logging.getLogger("pipeline.engine")

def apply_row_standardisation(row):
    # Force columns to be in strings
    must_be_strings = ["Invoice ID", "Tutor ID", "Student Name", "Tutor Name", 
                       "Log ID", "Assignment ID", "Subject", "Status"]

    for col in must_be_strings:
        val = row.get(col)
        if val is not None:
            row[col] = str(val).lower()

    # Payment Status
    payment_status = row.get("Payment Status")
    if isinstance(payment_status, str) and payment_status.lower().startswith("pend"):
        row["Payment Status"] = "Pending"
    
    # Subject Standardisation
    subject = row.get("Subject")
    if isinstance(subject, str) and subject.lower().startswith("maths"):
        row["Subject"] = "Mathematics"
    
    # Attendance Status Standardisation
    payment_status = row.get("Attendance Status")
    if isinstance(payment_status, str) and payment_status.lower().endswith("mc"):
        row["Attendance Status"] = "Absent-MC"

    return row

def parse_single_date(raw_val):
    """
    Returns: (parsed_date_str, success_boolean)
    - If empty: (None, True)
    - If parsed: ("YYYY-MM-DD", True)
    - If failed: (original_raw_val, False)
    """
    # Handle Null/Empty cases
    if pd.isna(raw_val) or raw_val in ["", "None", "NaN"]:
        return None, True

    # Expected date formats
    expected_formats = [
        "%Y-%m-%d",     # 2025-03-12
        "%m/%d/%Y",     # 01/05/2025
        "%d-%m-%Y",     # 25-04-2025
        "%d %b %Y",     # 12 Feb 2025
        "%B %d, %Y",    # July 7, 2025
        "%d-%b-%Y",     # 15-Oct-2025
        "%d/%m/%y"      # 12/03/25
    ]

    for fmt in expected_formats:
        try:
            return datetime.strptime(raw_val, fmt).date().isoformat(), True
        except (ValueError, TypeError):            
            logger.debug(f"Date format '{fmt}' failed for value: '{raw_val}'")            
            continue
            
    # Failure to parse the date
    logger.warning(f"All date formats failed for value: '{raw_val}'")
    return raw_val, False

def parse_and_round_decimal(val, places=4):
    """
    Cleans a single value by stripping symbols/commas, 
    extracting the number, and rounding to 'places'.
    """
    # Handle Null/Empty/NaN
    if pd.isna(val) or str(val).lower() in ["nan", "none", ""]:
        return None
    
    try:
        # Remove commas and white spaces
        clean_str = str(val).replace(",", "").strip()
        
        # Handles positive and negative numbers, and more than one decimal point
        # (e.g. 12.34.56 -> 12.34)    
        match = re.search(r"([-+]?[\d.]+)", clean_str)
        
        if not match:
            logger.error(f"Could not extract a valid number from '{val}'")
            raise ValueError(f"Could not extract a valid number from '{val}'")        
        
        # Extract the first capture group which is the numeric string in this case
        number_str = match.group(1)
        
        # Map places to decimal quantize format
        formats = {1: "0.1", 2: "0.01", 4: "0.0001"}
        quantize_format = Decimal(formats.get(places, "0.01"))
        
        return Decimal(number_str).quantize(quantize_format, rounding=ROUND_HALF_UP)
        
    except Exception:
        # If parsing fails, return None (or 0 if you prefer)
        logger.exception("Parsing and rounding of ")
        return None

def validate_and_clean_row_dict(row_dict, file_category, stored_id, stored_content, row_index):
    errors = []

    # 1. Strip leading, trailing, and internal excess whitespace for all cell values
    row = {column_header: (re.sub(r'\s+', ' ', value).strip() if isinstance(value, str) else value) for column_header, value in row_dict.items()}
            
    # 2. Identifify null records
    is_null_row = all(value is None or value == "" or pd.isna(value) for value in row.values())
    if is_null_row:
        raise RowValidationError(code="NULL_RECORD", message=f"Row {row_index} is completely empty.")

    # 3. Apply standisation for text fields
    row = apply_row_standardisation(row)    

    # 4. Apply different case formatting
    title_cols = ["Student Name", "Tutor Name", "Level", "Payment Status", "Attendance Status", "Subject", "Status"]
    for col in title_cols:
        if col in row and isinstance(row[col], str):
            row[col] = row[col].title()

    capitalize_cols = ["Payment Status", "Subject", "Status"]
    for col in capitalize_cols:
        if col in row and isinstance(row[col], str):
            row[col] = row[col].capitalize()
    
    uppercase_cols = ["Invoice ID", "Assignment ID", "Log ID"]
    for col in uppercase_cols:
        if col in row and isinstance(row[col], str):
            row[col] = row[col].upper()

    # 5. Perform date parsing
    date_cols = ["Invoice Date", "Payment Date", "Session Date", "Start Date"]

    for col in date_cols:
        # Only process if the column exists and is not null/empty
        if col in row and row[col] not in [None, ""]:
            raw_val = row[col]
            
            val, success = parse_single_date(raw_val)
            if not success:
                errors.append({"code": "INVALID_DATE", "message": f"Column '{col}' has invalid date format."})

            else:
                row[col] = val

    # 6. ROW-BY-ROW DECIMAL PARSING
    decimal_map = {
        "Amount": 4, 
        "Fees Charged": 4, 
        "Duration (Hours)": 1, 
        "Hourly Rate (SGD)": 4
    }

    for col, places in decimal_map.items():
        if col in row:
            # This will correctly overwrite "150 SGD" with a Decimal(150.0000)
            val= row[col]

            # Checks for non-numeric value
            if isinstance(val, str) and re.match(r'^[A-Za-z]+$', val.strip()):
                errors.append({
                    "code":"INVALID_VALUE",
                    "message":f"Row {row_index} has an invalid non-numeric value in '{col}': '{val}'."
                })

            # Checks for missing/null
            elif val is None or val ==0:
                errors.append({
                    "code": "ZERO_OR_NULL_VALUE",
                    "message": f"Row {row_index} has an invalid zero or empty value in '{col}'."
                })

            # If it's not alphabetic, proceed to parse and round
            row[col] = parse_and_round_decimal(val, places=places)

            

    # 7. Identify missing fields
    FIELD_CONFIG = {
        "INVOICE": {
            "Invoice ID": {"mandatory": True},
            "Assignment ID": {"mandatory": True},
            "Student Name": {"mandatory": True},
            "Invoice Date": {"mandatory": True},
            "Amount": {"mandatory": True},
            "Payment Status": {"mandatory": True},
            "Payment Date": {"mandatory": False}, 
            "Notes": {"mandatory": False},
        },
        "ASSIGNMENT": {
            "Assignment ID": {"mandatory": True},
            "Tutor Name": {"mandatory": True},
            "Student Name": {"mandatory": True},
            "Subject": {"mandatory": True}, 
            "Level": {"mandatory": True}, 
            "Hourly Rate (SGD)": {"mandatory": True}, 
            "Start Date": {"mandatory": True}, 
            "Status": {"mandatory": True}, 
            "Contact Email": {"mandatory": True}, 
        },
        "LESSON_LOG": {
            "Log ID": {"mandatory": True},
            "Assignment ID": {"mandatory": True},
            "Session Date": {"mandatory": True},
            "Duration (Hours)": {"mandatory": True}, 
            "Attendance Status": {"mandatory": True}, 
            "Session Notes": {"mandatory": True}, 
            "Fees Charged": {"mandatory": True}, 
        },
    }

    file_rules = FIELD_CONFIG.get(file_category, {})
    
    missing_fields = []

    for field, rules in file_rules.items():
        # Check if the field is mandatory AND (critically) if it was expected in the row
        if rules.get("mandatory", False):
            # Validate against the cleaned 'row' object
            val = row.get(field)
            
            # Robust check for None, empty, or NaN
            if val is None or (isinstance(val, str) and not val.strip()) or pd.isna(val):
                missing_fields.append(field)
            
    if missing_fields:
        errors.append({
            "code": "NULL_FIELD", 
            "message": f"Row {row_index} is missing mandatory data in field(s): {', '.join(missing_fields)}."
        })

    # 8. Identify  non enum value
    enum_map = {
        "Attendance Status": AttendanceStatus,
        "Subject": Subject,
        "Payment Status": PaymentStatus,
        "Status": AssignmentStatus, 
        "Duration (Hours)": Duration
    }
    
    for col, enum_class in enum_map.items():
        if col in row and row[col] is not None:
            val = str(row[col]).strip().lower()
            
            # 2. Extract allowed values (using the pre-computed set logic)
            # Ensure these are also lowercase for the comparison
            allowed_values = {str(item.value).lower() for item in enum_class}
            
            if val not in allowed_values:
                errors.append({
                    "code": "INVALID_ENUM",
                    "message": f"Row {row_index}: '{val}' is not a valid option for '{col}'. Allowed: {', '.join([str(v) for v in allowed_values])}"
                })

    # 9. Identify duplicates
    criteria_map = {
        'INVOICE': {'pk': 'Invoice ID', 'secondary': ["Student Name", "Invoice Date", "Payment Status", "Payment Date"]},
        'ASSIGNMENT': {'pk': 'Assignment ID', 'secondary': ["Tutor Name", "Student Name", "Start Date"]},
        'LESSON_LOG': {'pk': 'Log ID', 'secondary': ["Assignment ID", "Session Date", "Session Notes"]}
    }

    config = criteria_map.get(file_category, {})
    pk_key = config.get('pk')
    pk_val = str(row.get(pk_key, '')).strip().upper()

    secondary_vals = []
    for col in config.get('secondary', []):
        val = row.get(col)
        # Normalization (ensure it matches your specific logic)
        secondary_vals.append(str(val).strip().lower() if val is not None else "")
    
    # Generate signatures
    # 1. Unique ID signature
    id_signature = pk_val
    # 2. Business Content signature (The actual data)
    content_signature = tuple(secondary_vals)

    # Check for Technical Duplicates (ID conflict)
    if id_signature in stored_id:
        # Get the row index where it was first seen
        original_row = stored_id[id_signature]
        errors.append({
            "code":"DUPLICATE_ID", 
            "message":f"ID '{id_signature}' already exists (first seen at row {original_row})."
        })

    # Check for Business Logic Duplicates (Content conflict)
    if content_signature in stored_content:
        original_row = stored_content[content_signature]
        errors.append({
            "code":"DUPLICATE_CONTENT", 
            "message":f"Entry with identical details: {content_signature} already exists at row {original_row}."
        })

    # 3. Store the entries ONLY after passing validation
    # Use dictionary assignment, NOT .add()
    stored_id[id_signature] = row_index
    stored_content[content_signature] = row_index
        
    if errors:
        raise RowValidationCollectionError(errors)

    return row, file_category

def find_highlighted_header(file_path, max_scan_rows=30):
    # visual formatting clues 
    # such as bolded text, coloured background, unique column values 
    try:
        # Load the workbook safely
        wb = openpyxl.load_workbook(file_path, data_only=True)
        first_sheet_name = wb.sheetnames[0]
        sheet = wb[first_sheet_name]

        # Loop through up to 30 rows
        for row_index in range(1, max_scan_rows + 1):
            has_bold = False
            has_color = False
            row_values = []

            # Loop through every cell in current row
            for cell in sheet[row_index]:
                cell_value = cell.value

                # Check if there is text in the cell
                if cell_value is not None and cell_value != "":
                    row_values.append(cell_value)

                    # Check if cell's font is bolded
                    if cell.font and getattr(cell.font, 'bold', False):
                        has_bold = True

                    # Check if a fill pattern actually exists and isn't the default "none" string
                    if cell.fill:
                        # Verify the cell has a solid fill pattern
                        is_solid = getattr(cell.fill, 'fill_type', None) == 'solid'

                        # Verify that background fill color exists and has a valid RGB value
                        start_color = getattr(cell.fill, 'start_color', None)
                        has_rgb = start_color and start_color.rgb is not None

                        # If both conditions are met, the cell has a custom background color
                        if is_solid and has_rgb:
                            has_color = True

            # Check if the row have multiple data columns
            has_multiple_columns = len(row_values) > 1
            # Check if each cell in the current row is unique
            is_unique = len(row_values) == len(set(row_values))

            if has_multiple_columns and has_color and has_bold and is_unique:
                logger.info(f"Header successfully matched at row {row_index} ({len(row_values)} unique columns found)!")
                return first_sheet_name, (row_index - 1), True


        # Fallback if the loop finishes without matching any specific criteria
        logger.info("Notice: No highlighted header matched standard criteria. Defaulting to row 0.")
        return first_sheet_name, 0, False

    except FileNotFoundError:
        logger.error(f"Error: The file at path '{file_path}' was not found.")
        return None, 0, False
    
    except Exception as e:
        logger.exception(f"Unexpected error reading or processing the Excel file header: {e}")
        return None, 0, False

def identify_file_category(data_path):
    try:
        # 1. ATTEMPT HEADER DISCOVERY
        # Using existing find_highlighted_header logic
        sheet_name, rows_to_skip, header_found = find_highlighted_header(data_path)

        if header_found:
            # Case A: Header found via highlighting
            logger.info(f"Header discovered via highlighting (Sheet: {sheet_name}, Skip: {rows_to_skip})")
            df = pd.read_excel(data_path, sheet_name=sheet_name, skiprows=rows_to_skip)
        else:
            # Case B: No header found, apply heuristic mapping to infer column structure
            logger.warning(f"No header found in {data_path}; Falling back to heuristic column structure inference.")
            df = pd.read_excel(data_path, sheet_name=sheet_name, header=None)
        
        max_rows_to_check = min(30, len(df))
        df, inferred_category = identify_and_map_columns(df, max_rows_to_check)

        if inferred_category == "UNKNOWN":
            logger.error(f"Discovery failed: File category could not be inferred for {data_path}.")
            raise ValueError("File category could not be identified.")

        logger.info(f"Successfully identified file as: {inferred_category}")

        return inferred_category

    except Exception as e:
        logger.error(f"Failed to process {data_path}: {e}", exc_info=True)
        raise
    
def is_valid_date(raw_val) -> bool:
    # Define the exact formats expected
    expected_formats = [
        "%Y-%m-%d",   # 2025-03-12
        "%m/%d/%Y",   # 01/05/2025
        "%d-%m-%Y",   # 25-04-2025
        "%d/%m/%y",   # 25/04/26
        "%d %b %Y",   # 12 Feb 2025
        "%B %d, %Y",  # July 7, 2025
        "%d-%b-%Y"    # 15-Oct-2025
    ]

    try:
        # Return False immediately for empty, null, or blank values
        if pd.isna(raw_val) or str(raw_val).strip() in ["", "None", "NaN", "nan"]:
            return False

        clean_val = str(raw_val).strip()

        # Return True the moment a format matches successfully
        for fmt in expected_formats:
            try:
                datetime.strptime(clean_val, fmt)
                return True
            except ValueError:
                # Format didn't match, continue to next
                continue

        # Return False if all formatting options fail
            logger.debug(f"Date validation failed for input: '{clean_val}'")
            return False

    except Exception as e:
        # Catch unexpected type conversion errors or pandas evaluation crashes
        logger.exception(f"Unexpected error validating date for value '{raw_val}': {e}")
    return False

def parse_decimal(raw_value) -> Decimal:
    """
    Extracts only digits from value and converts a numeric string to a Decimal object.
    """
    # Raise and log if value is empty/null
    if raw_value is None or str(raw_value).strip() in ["", "nan", "None"]:
        logger.debug(f"Null or empty input received: {raw_value} while parsing decimal")
        raise ValueError("Input value is null or completely empty.")

    val_str = str(raw_value).strip()

    # Extract numeric sequence (supports signs, commas, and decimal points)
    match = re.search(r"([-+]?[\d.,]+)", val_str)

    # If no digits are found, raise an error instead of returning 0
    if not match:
        logger.warning(f"No numeric digits found in raw text: '{val_str}'")
        raise ValueError(f"No numeric digits found in raw text: '{val_str}'")

    extracted_text = match.group(0)
    clean_text = extracted_text.replace(",", "")

    # Convert directly to Decimal.
    # If the string is malformed (like "1..23"), Python will naturally raise an error.
    return Decimal(clean_text)


def identify_and_map_columns(df, max_rows_to_check):
    """
    Identifies column headers using a two-pass heuristic approach:
    Pass 1: Identify columns with explicit, unique identifiers (e.g., IDs, known names, or status keywords)
    Pass 2: Infer context-dependent columns (Dates, Fees, Notes) based on columns identified during Pass 1
    """

    df = df.copy()

    # distinct keywords and key phrases to identify potential header
    session_notes_words_to_check = ["reading", "covered", "timed"]
    invoice_notes_phases_to_check = ["awaiting bank transfer", "no response from parent"]
    student_names = ["lim wei jie"]
    tutor_names = ["ahmad rizwan"]

    header_row_index = None # The index for header row
    existing_headers = [] # Store header that exists already
    column_samples = {} # First 30 rows of data
    pass1_headers = [] # Headers that are identified during first stage of header identification

    try:

        # ==========================================
        # PASS 1: Identify Structural Anchor Columns
        # ==========================================
        
        # Loop through all columns, column by column
        for col_index in range(df.shape[1]):
            column_sample = df.iloc[:max_rows_to_check, col_index].tolist()
            column_samples[col_index] = column_sample
            matched_header = None

            for current_row_index, value in enumerate(column_sample):
                clean_val = str(value).strip().lower() if pd.notna(value) else ""

                if clean_val.startswith("log"):
                    matched_header = "Log ID"
                elif clean_val.startswith("tas"):
                    matched_header = "Assignment ID"
                elif clean_val.startswith("inv"):
                    matched_header = "Invoice ID"
                elif any(clean_val == name for name in student_names):
                    matched_header = "Student Name"
                elif any(clean_val == name for name in tutor_names):
                    matched_header = "Tutor Name"
                elif clean_val in [AttendanceStatus.PRESENT.value, AttendanceStatus.ABSENT.value, AttendanceStatus.LATE.value]:
                    matched_header = "Attendance Status"
                elif clean_val in [Subject.ENGLISH.value, Subject.MATHEMATICS.value, Subject.SCIENCE.value]:
                    matched_header = "Subject"
                elif any(level in clean_val for level in SchoolLevel):
                    matched_header = "Level"
                elif clean_val in [PaymentStatus.PAID.value, PaymentStatus.OVERDUE.value]:
                    matched_header = "Payment Status"
                elif clean_val in [AssignmentStatus.ACTIVE.value, AssignmentStatus.INACTIVE.value]:
                    matched_header = "Status"
                elif clean_val.endswith("@tutors.com"):
                    matched_header = "Contact Email"

                # 1. Ensure we only track unique headers
                if matched_header:
                    if matched_header not in existing_headers:
                        existing_headers.append(matched_header)

                    # 2. Identify the top-most row as the header row.
                    # If theres a match on a row before the current 'header_row_index', 
                    # it implies there might be a multi-line header an earlier starting point.
                    if header_row_index is None or current_row_index < header_row_index:
                        logger.info(f"Setting header_row_index to {current_row_index} based on match: {matched_header}")
                        header_row_index = current_row_index
                    
                    # 3. Stop scanning once header is identified
                    logger.debug(f"Breaking search at row {current_row_index} after finding match.")
                    break

            pass1_headers.append(matched_header)

        # ==========================================
        # PASS 2: Resolve Context-Dependent Columns
        # ==========================================

        new_headers = [] # Store headers during secong stage of header identification

        # Categorise file category using the headers identified during pass 1
        is_lesson_log = "Log ID" in existing_headers and "Assignment ID" in existing_headers
        is_invoice = "Invoice ID" in existing_headers and "Assignment ID" in existing_headers
        is_assignment = "Assignment ID" in existing_headers and "Level" in existing_headers and "Subject" in existing_headers

        for col_index, matched_header in enumerate(pass1_headers):
            if matched_header is None:
                for current_row_index, value in enumerate(column_samples[col_index]):
                    clean_val = str(value).strip().lower() if pd.notna(value) else ""

                    try:
                        # If is not identified as data, parse it to decimal
                        if not is_valid_date(clean_val):
                            decimal_val = parse_decimal(clean_val)
                        else:
                            # If it is a date, skip it and set to zero
                            decimal_val = Decimal("0")

                    # ---- THE CATCH BLOCK ----
                    except Exception as e:
                        logger.exception(f" Failed extracting numeric value from row {current_row_index}, col {col_index} ('{clean_val}'): {e}")
                        decimal_val = Decimal("0")

                    if is_lesson_log:
                        if is_valid_date(clean_val):
                            matched_header = "Session Date"
                        elif decimal_val >= 45.00:
                            matched_header = "Fees Charged"
                        elif len(clean_val.split()) >= 2 and any(word in clean_val.split() for word in session_notes_words_to_check):
                            matched_header = "Session Notes"
                        elif decimal_val in [Duration.SHORT.value, Duration.MEDIUM.value,  Duration.LONG.value]:
                            matched_header = "Duration (Hours)"

                    elif is_invoice:
                        if is_valid_date(clean_val):
                            matched_header = "Date Candidate"
                        elif decimal_val >= 45.00:
                            matched_header = "Amount"
                        elif any(clean_val == phase for phase in invoice_notes_phases_to_check):
                            matched_header = "Notes"

                    elif is_assignment:
                        if is_valid_date(clean_val):
                            matched_header = "Start Date"
                        elif decimal_val >= 45.00:
                            matched_header = "Hourly Rate (SGD)"

                    if matched_header:
                        if header_row_index is None or current_row_index < header_row_index:
                            header_row_index = current_row_index
                        break

            # Assign a fallback structural index label if unmatched
            new_headers.append(matched_header if matched_header else f"Column_{col_index+1}")

        if is_invoice:
                date_cols = [i for i, h in enumerate(new_headers) if h == "Date Candidate"]
                if len(date_cols) >= 2:
                    # Compare dates in the first available data row to determine identity
                    d1 = pd.to_datetime(df.iloc[header_row_index, date_cols[0]])
                    d2 = pd.to_datetime(df.iloc[header_row_index, date_cols[1]])
                    if d1 < d2:
                        new_headers[date_cols[0]], new_headers[date_cols[1]] = "Invoice Date", "Payment Date"
                    else:
                        new_headers[date_cols[0]], new_headers[date_cols[1]] = "Payment Date", "Invoice Date"
                elif len(date_cols) == 1:
                    new_headers[date_cols[0]] = "Invoice Date"

        # Raise value error if no headers could be identified
        if not any(new_headers):
            logger.error("Mapping failed: No headers could be identified.")
            raise ValueError("Mapping failed: No headers could be identified.")

        # Assign new headers
        df.columns = new_headers

        if is_invoice: 
            inferred_category = 'INVOICE'
        elif is_lesson_log: 
            inferred_category = 'LESSON_LOG'
        elif is_assignment: 
            inferred_category = 'ASSIGNMENT'
        else: 
            inferred_category = 'UNKNOWN'

        # Crop data to match discovered table boundaries
        if header_row_index is not None:
            df = df.iloc[header_row_index:].reset_index(drop=True)

        logger.info("Heuristic column mapping completed successfully!")
        return df, inferred_category

    except ValueError as ve:
        logger.error(f"Data Validation Error: {ve}")
        return df, "Unknown"

    except Exception as e:
        logger.exception(f"An unexpected error occurred during column mapping: {e}")
        return df, "Unknown"

def generate_styled_excel_in_memory(df_cleaned, sheet_name="Sheet1"):
    sheet_name = sheet_name.replace(" ", "_")
    buffer = io.BytesIO()

    try:
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            df_cleaned.to_excel(writer, sheet_name=sheet_name, index=False, startrow=1, header=False)
            
            workbook = writer.book
            worksheet = writer.sheets[sheet_name]

            # Define formats
            header_format = workbook.add_format({
                "bold": True, "bg_color": "#1B3A6B", "font_color": "#FFFFFF",
                "align": "left", "valign": "vcenter", "border": 1
            })
            money_format = workbook.add_format({"num_format": "#,##0.00"})
            duration_format = workbook.add_format({"num_format": "0.0"})

            # Write headers
            for col_index, col_name in enumerate(df_cleaned.columns):
                worksheet.write(0, col_index, str(col_name), header_format)

            # Apply column formats and wiidths
            column_formats = {
                "Amount": money_format, "Fees Charged": money_format,
                "Hourly Rate (SGD)": money_format, "Duration (Hours)": duration_format
            }

            for col_index, col_name in enumerate(df_cleaned.columns):
                col_fmt = column_formats.get(col_name)
                max_len = max(len(str(col_name)), df_cleaned[col_name].astype(str).str.len().max()) + 5
                final_width = max(10, min(max_len, 50))
                worksheet.set_column(col_index, col_index, final_width, col_fmt)

        buffer.seek(0)
        return buffer

    except Exception as e:
        logger.exception(f"Failed to generate styled Excel report: {e}")
        return None