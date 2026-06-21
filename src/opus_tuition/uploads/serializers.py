from rest_framework import serializers
from .models import Upload, QuarantineRecord
from .pipeline import validate_and_clean_row_dict, RowValidationError
import os 
# =========================================================================
# 1. REPORTING SERIALIZERS (For GET /report/:upload_id and GET /quarantine)
# =========================================================================

class QuarantineRecordSummarySerializer(serializers.ModelSerializer):
    """
    Sub-serializer to nestedly map detailed anomaly information 
    for the master processing report.
    """
    row_id = serializers.UUIDField(source='quarantine_record_id')
    
    class Meta:
        model = QuarantineRecord
        fields = ['row_id', 'row_index', 'reason_code', 'error_details', 'raw_payload']


class UploadReportSerializer(serializers.ModelSerializer):
    """
    Translates structural Upload models into comprehensive operational 
    JSON reports matching your specific endpoint guidelines.
    """
    file = serializers.FileField(source='raw_file') 
    file_name = serializers.SerializerMethodField()
    metrics = serializers.SerializerMethodField()
    clean_records = serializers.SerializerMethodField()
    quarantine_records = serializers.SerializerMethodField()


    class Meta:
        model = Upload
        fields = [
            'upload_id', 
            'file',
            'file_name',
            'file_category', 
            'status', 
            'metrics', 
            'clean_records',
            'quarantine_records'
        ]
        read_only_fields = ['status', 'file_category']

    def get_file_name(self, obj): 
        if obj.raw_file:
            return os.path.basename(obj.raw_file.name)
        return "No File Attached"


    def get_metrics(self, obj):
        """Compiles real-time row distribution balances via database aggregation."""
        # Count actual records linked to this upload in the database
        accepted_count = obj.clean_records.count()
        quarantine_count = obj.quarantine_records.filter(is_resolved=False).count()        
        
        return {
            "total_rows_received": accepted_count + quarantine_count,
            "rows_accepted": accepted_count,
            "rows_quarantined": quarantine_count
        }

    def get_clean_records(self, obj):
        return [{"clean_record_id": r.clean_record_id, "data": r.clean_payload} for r in obj.clean_records.all()]

    def get_quarantine_records(self, obj):
        # Ensure 'reason_code' matches what your JS expects ('r.reason')
        return [{"quarantine_record_id": r.quarantine_record_id, "row_index": r.row_index, "reason_code": r.reason_code, "error_details": r.error_details, "raw_data": r.raw_payload} for r in obj.quarantine_records.filter(is_resolved=False)]

# =========================================================================
# 2. RE-VALIDATION SERIALIZER (For PATCH /quarantine/:row_id)
# =========================================================================

class QuarantineResolutionSerializer(serializers.Serializer):
    """
    A pure functional serializer designed explicitly to intercept 
    and re-run raw rows back through the data validation matrix.
    """
    corrected_payload = serializers.JSONField(
        help_text="The full dictionary row payload with corrected manual inputs."
    )

    def validate_corrected_payload(self, value):
        """
        Interceptors hooked directly into the DRF validation framework.
        Runs your complete notebook normalization loop.
        """
        # Retrieve the historical tracking record passed from your view patch context
        record = self.context.get('record')
        if not record:
            raise serializers.ValidationError("System Error: Critical record tracking context missing.")

        try:
            # Trigger your exact pipeline validation engine matrix
            # An empty set() bypasses global batch tracking blocks during localized updates
            cleaned_row, _ = validate_and_clean_row_dict(
                raw_payload=value,
                file_category=record.upload.file_category,
                stored_id={},
                stored_content={},
                row_idx=record.row_index
            )
            
            # Return the fully normalized, stripped, and rounded dictionary back to the controller
            return cleaned_row

        except RowValidationError as rve:
            # Format pipeline exceptions so your frontend clients understand the failure reason
            raise serializers.ValidationError({
                "reason_code": rve.code,
                "error_details": rve.message
            })
        except Exception as e:
            raise serializers.ValidationError(f"Unexpected data formatting error: {str(e)}")

            