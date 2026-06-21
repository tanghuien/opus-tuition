from django.urls import path
from .views import (
    FileUploadAPIView,
    RecordsAPIView,
    QuarantineListAPIView,
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
    path("api/upload/", FileUploadAPIView.as_view(), name="pipeline-upload"),
    
    # b. GET /records
    path("api/records/", RecordsAPIView.as_view(), name="pipeline-clean-records"),
    
    # c. GET /quarantine
    path("api/quarantine/", QuarantineListAPIView.as_view(), name="pipeline-quarantine-list"),
    
    # d. GET /report/:upload_id
    path("api/report/<uuid:upload_id>/", UploadReportAPIView.as_view(), name="pipeline-upload-report"),
    
    # e. PATCH /quarantine/:row_id
    path("api/quarantine/<uuid:row_id>/", QuarantineResolveAPIView.as_view(), name="pipeline-quarantine-resolve"),

    path('api/delete/<str:record_type>/<uuid:row_id>/', DeleteRecordAPIView.as_view(), name='delete-record'),
    
    # f. GET /health
    path("api/health/", SystemHealthAPIView.as_view(), name="pipeline-system-health"),

    path("ui/", upload_page, name="pipeline-ui"),

    path("download-cleaned-records/<str:upload_id>/", download_cleaned_records, name="download_cleaned_records"),

    path("download-full-report/<str:upload_id>/", download_full_report, name="download_full_report"),
]


