from rest_framework import serializers
from .models import Upload, QuarantineRecord
from .pipeline import validate_and_clean_row_dict, RowValidationError
import os 

# REPORTING SERIALIZERS (For GET /report/:upload_id)
class UploadReportSerializer(serializers.ModelSerializer):
    """
    Translates structural Upload models into comprehensive operational 
    JSON reports matching specific endpoint guidelines.
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
            'upload_status', 
            'metrics', 
            'clean_records',
            'quarantine_records'
        ]
        read_only_fields = ['upload_status', 'file_category']

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
        return [{
            "clean_record_id": r.clean_record_id, 
            "data": r.clean_payload} for r in obj.clean_records.all()]

    def get_quarantine_records(self, obj):
        return [{
            "quarantine_record_id": r.quarantine_record_id, 
            "row_index": r.row_index, 
            "reason_code": r.reason_code, 
            "error_details": r.error_details, 
            "raw_data": r.raw_payload} for r in obj.quarantine_records.filter(is_resolved=False)]


