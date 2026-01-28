"""
File validation utilities for billing.
"""
import os


def is_file_type_allowed(filename):
    """
    Check if the file type is allowed for upload.

    Args:
        filename: The filename to check

    Returns:
        bool: True if allowed, False otherwise
    """
    allowed_extensions = ['.pdf', '.png', '.jpg', '.jpeg']
    ext = os.path.splitext(filename)[1].lower()
    return ext in allowed_extensions


def validate_file_size(file, max_size_mb=10):
    """
    Validate file size.

    Args:
        file: Django UploadedFile
        max_size_mb: Maximum allowed size in megabytes

    Returns:
        bool: True if valid, False otherwise
    """
    max_size_bytes = max_size_mb * 1024 * 1024
    return file.size <= max_size_bytes
