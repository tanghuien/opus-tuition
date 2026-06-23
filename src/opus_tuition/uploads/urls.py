from django.urls import path
from .views import (
    FileUploadAPIView,
    RecordsAPIView,
    QuarantineRecordsAPIView,
    UploadReportAPIView,
    DeleteRecordAPIView,
    QuarantineResolveAPIView,
    SystemHealthAPIView,
    upload_page,
    download_cleaned_records,
    download_full_report
)

from .models import *

urlpatterns = [
    # a. POST /upload
    path("api/upload/", FileUploadAPIView.as_view(), name="upload_api"),
    
    # b. GET /records
    path("api/records/", RecordsAPIView.as_view(), name="records_api"),
    
    # c. GET /quarantine
    path("api/quarantine/", QuarantineRecordsAPIView.as_view(), name="quarantine_records_api"),
    
    # d. GET /report/:upload_id
    path("api/report/<uuid:upload_id>/", UploadReportAPIView.as_view(), name="upload_report_api"),
    
    # e. PATCH /quarantine/:row_id
    path("api/quarantine/<uuid:row_id>/", QuarantineResolveAPIView.as_view(), name="quarantine_resolve_api"),

    # DELETE /delete/:record_type/row_id/
    path('api/delete/<str:record_type>/<uuid:row_id>/', DeleteRecordAPIView.as_view(), name='delete-record_api'),
    
    # f. GET /health
    path("api/health/", SystemHealthAPIView.as_view(), name="system-health"),

    path("ui/", upload_page, name="ui"),

    path("download-cleaned-records/<str:upload_id>/", download_cleaned_records, name="download_cleaned_records"),

    path("download-full-report/<str:upload_id>/", download_full_report, name="download_full_report"),
]


