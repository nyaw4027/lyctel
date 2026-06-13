"""
Firebase / Google Cloud Storage backend for Django media files.

Clean implementation using django-storages (GoogleCloudStorage).
No proxy wrapper, no lazy import issues.
"""

from django.conf import settings
from storages.backends.gcloud import GoogleCloudStorage


class FirebaseStorage(GoogleCloudStorage):
    """
    Proper Django storage backend for Firebase (Google Cloud Storage).
    Handles upload, retrieval, and URL generation correctly.
    """

    def __init__(self, *args, **kwargs):
        bucket_name = getattr(settings, "FIREBASE_STORAGE_BUCKET", None)

        if not bucket_name:
            raise ValueError(
                "FIREBASE_STORAGE_BUCKET is not set in settings.py"
            )

        kwargs.setdefault("bucket_name", bucket_name)
        kwargs.setdefault("location", "media")
        kwargs.setdefault("default_acl", "publicRead")
        kwargs.setdefault("file_overwrite", False)
        kwargs.setdefault("querystring_auth", False)

        super().__init__(*args, **kwargs)