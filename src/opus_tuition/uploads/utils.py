import os
import logging
from rest_framework.response import Response
from rest_framework import status
from decimal import Decimal
import numpy as np
import pandas as pd

class RowValidationError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(self.message)

class RowValidationCollectionError(Exception):
    def __init__(self, errors):
        self.errors = errors

def sanitize_for_json(obj):
    """Recursively convert data to JSON-serializable formats."""
    if isinstance(obj, dict):
        return {key: sanitize_for_json(value) for key, value in obj.items()} # Sanitize dictionary values to ensure compatibility with JSON serialization
    elif isinstance(obj, list):
        return [sanitize_for_json(var) for var in obj] # Sanitize each item in the list 
    elif isinstance(obj, Decimal):
        return float(obj)  # Convert Decimal to float for JSON
    elif isinstance(obj, (np.float64, np.int64)):
        return obj.item()  # Convert numpy types to native Python
    elif pd.isna(obj):
        return None        # Convert NaN to JSON null
    return obj

