## API Reference: OPUS Tuition
### 1. Overview
This API provides the necessary endpoints to manage the lifecycle of tuition data, including file ingestion, validation, reporting, and error resolution.
#### 2. API Endpoints
##### 2a. File Upload
`POST /api/upload/`
<br>
Processes uploaded Excel files through the data pipeline.

<span style="color:green">Success (200 OK)</span>: Returns a list of processing results, including metadata for each file.
```json
{
    "results": [
        {
            "success": true,
            "report": {
                "upload_id": "8b721e06-06fe-4b9d-b42e-723fcf169bb4",
                "file": "/uploads/uploaded_files/2026/06/24/lesson_logs_messy_IwHW29c.xlsx",
                "file_name": "lesson_logs_messy_IwHW29c.xlsx",
                "file_category": "LESSON_LOG",
                "upload_status": "QUARANTINED",
                "metrics": {
                    "total_rows_received": 2,
                    "rows_accepted": 1,
                    "rows_quarantined": 1
                },
                "clean_records": [
                    {
                        "clean_record_id": "3e9e6dcf-cd77-4321-92bf-e81f45140ea6",
                        "data": {
                            "Log ID": "LOG-001",
                            "Assignment ID": "TAS-001",
                            "Session Date": "2025-01-05",
                            "Duration (Hours)": 1.5,
                            "Attendance Status": "Present",
                            "Session Notes": "Covered algebra ch.3",
                            "Fees Charged": 82.5
                        }
                    }
                ],
                "quarantine_records": [
                    {
                        "quarantine_record_id": "dd83e03d-9953-417d-b97d-9d0c6332b194",
                        "row_index": 4,
                        "reason_code": "INVALID_VALUE",
                        "error_details": "Row 4 has an invalid non-numeric value in 'Fees Charged': 'TBC'.",
                        "raw_data": {
                            "Log ID": "LOG-004",
                            "Assignment ID": "TAS-004",
                            "Session Date": "20/03/25",
                            "Duration (Hours)": 1.5,
                            "Attendance Status": "Absent",
                            "Session Notes": "Student unwell — cancelled",
                            "Fees Charged": "TBC"
                        }
                    }
                ]
            }
        }
    ]
}
```
<span style="color:red">Failure (413 REQUEST_ENTITY_TOO_LARGE)</span>: File size exceeded 10 MB. 
```json
{
    "success": false,
    "error": {
        "code": "FILE_TOO_LARGE",
        "message": "File exceeds 10MB."
    }
}
```
<span style="color:red">Failure (404 NOT_FOUND)</span>: Non-excel file extension.
```json
{   "success": false, 
    "error": {
        "code": "INVALID_FILE_EXTENSION", 
        "message": "Only Excel files are allowed."
    }
}
```

#####  2b. Data Records
`GET /api/records/`
Returns clean records with filtering capabilities.
<br>
Query Params:
<br>
upload_id (Filter by specific upload).
<br>
start_date / end_date (ISO format).
<br>
file_category (e.g., "ASSIGNMENT", "LESSON_LOG", "INVOICE").

<span style="color:green">Success (200 OK)</span>: Returns JSON containing cleaned record count, filtered date range, and the cleaned records.
```json
{
  "success": true,
  "count": 1,
  "filters": {
    "date_range_range": {
      "start": "2026-06-24T01:46:47.200202+00:00",
      "end": "2026-06-24T08:41:21.920179+00:00"
    }
  },
  "results": [
    {
      "clean_record_id": "48569113-c418-4205-af54-6898aabc62c0",
      "upload_id": "f745565f-3c9c-4b65-bf96-366c00f18e1c",
      "created_at": "2026-06-24T01:46:47.200202+00:00",
      "clean_payload": {
        "Assignment ID": "TAS-001",
        "Tutor Name": "Ahmad Rizwan",
        "Student Name": "Lim Wei Jie",
        "Subject": "Mathematics",
        "Level": "Secondary 3",
        "Hourly Rate (SGD)": 55.0,
        "Start Date": "2025-01-05",
        "Status": "Active",
        "Contact Email": "ahmad.r@tutors.com"
      }
    }
  ]
}
```
#### 2c. Quarantine Management
`GET /api/quarantine/`
<br>
Lists of all unresolved quarantined records.

<span style="color:green">Success (200 OK)</span>: Displays full report of clean and quarantined records for an upload.
```json
{
    "success": true,
    "total_quarantined_items": 1,
    "results": [
        {
            "upload_id": "dc249931-85eb-420f-9984-35d5e7617526",
            "row_index": 4,
            "reason_code": "REFERENCE_NOT_FOUND",
            "error_details": "Assignment ID 'TAS-004' not found. File could not be saved to database.",
            "raw_payload": {
                "Invoice ID": "INV-2025-004",
                "Assignment ID": "TAS-004",
                "Student Name": "Chloe Wong",
                "Invoice Date": "2025-03-31",
                "Amount": "SGD 75.00",
                "Payment Status": "PENDING",
                "Payment Date": null,
                "Notes": "No response from parent"
            }
        }
    ]
}
```

#### 2d. Reports
`GET /api/report/<uuid:upload_id>/`
<br>
Retrieves the full processing report for a specific upload.

<span style="color:red">Failure (404 NOT_FOUND)</span>: Upload does not exist in the database.
```json
{
    "success": false, 
    "message": "Upload token sequence tracking index '{cf4f01ea-2140-4e05-9020-93d80f136ec3}' is invalid.",
    "timestamp": "2026-06-24T08:31:47.281192+00:00"
}
```
#### 2e. Resolve quarantined records
`PATCH /api/quarantine/<uuid:row_id>`
<br>
 Marks a row as resolved and triggers re-validation.

<span style="color:green">Success (200 OK)</span>: Confirms database and file system connectivity.
```json
{
    "success": true, 
    "message": "Successfully migrated to clean records."
}
```

<span style="color:red">Failure (404 NOT_FOUND)</span>: Quarantined record does not exist in the database.
```json
{
    "success": false, 
    "message": "Record not found."
}
```
<span style="color:red">Failure (400 BAD_REQUEST)</span>: Quarantined record exist in the database but already resolved.
```json
{
    "success": false, 
    "message": "Record has already resolved."
}
```
<span style="color:red">Failure (400 BAD_REQUEST)</span>: No data is entered.
```json
{
    "success": false, 
    "message": "Missing payload."
}
```
<span style="color:red">Failure (404 NOT_FOUND)</span>: Foreign key constraint. Reference not found.
```json
{
    "success": false, 
    "message": "Assignment with ID TAS-231 not found."
}
```
<span style="color:red">Failure (422 UNPROCESSABLE_ENTITY)</span>: Returns re-validation error.
```json
{
    "success": false,
         "error": {
             "code": "REVALIDATION_FAILED", 
             "details": {
                 "reason": "NULL_RECORD", 
                 "message": "Row 2 is completely empty."
             }
         }
}
```
<span style="color:red">Failure (422 UNPROCESSABLE_ENTITY)</span>: Returns re-validation errors.
```json
{
    "success": false,
         "error": {
             "code": "REVALIDATION_FAILED", 
             "details": {
                 "reason": ["DUPLICATE_ID", "DUPLICATE_CONTENT"], 
                 "message": [
                  "ID TAS-004 already exists (first seen at row 1).",
                  "Entry with identical details: ('aisha binte yusof', '2025-07-31', 'paid', '2025-08-02') already exists at row 7."]
             }
         }
}
```
<span style="color:red">Failure (500 INTERNAL_SERVER_ERROR)</span>: Unexpected issues causing system error.
```json
{
     "success": false, 
      "error": "An internal system error occurred during revalidation. Error: System error."
}
```
#### 2f. Database health 
`GET /api/health`
<br>
Verifies system and database status.

<span style="color:green">Success (200 OK)</span>: Confirms database and system is working.
```json
{
    "success": true,
    "status": "HEALTHY",
    "services": {
        "database": "CONNECTED",
        "file_system": "WRITABLE"
    },
    "timestamp": "2026-06-24T07:23:37.963968+00:00"
}
```
<span style="color:red">Failure (503 SERVICE UNAVAILABLE)</span>: Confirms the database and system is down.
```json
{
    "success": false, 
    "error": {
        "code": "DATABASE_DOWN", 
        "message": "Database is down.", 
        "details": "The database is currently down. Please try again later."
    }
}
```

### 3. HTTP Staus Code
| HTTP | Code | Description |
|--- | ---| ---|
| 400 | Bad Request | Missing files or empty payload.
| 404 |Not Found | Upload or Record ID does not exist.
| 413 | Entity Too Large | File size exceeds 10MB limit.
| 415 | Unsupported Media | Non-Excel file extension provided.
| 422 | Unprocessable | Unable to resolve quarantine record.
| 500 | Internal Server Error | System pipeline failure.
| 503 |	Service Unavailable | Database connection issues.

