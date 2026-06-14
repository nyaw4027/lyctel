"""
ecommerce/firebase_storage_backend.py

Firebase Storage backend using django-storages GoogleCloudStorage.
Used when GOOGLE_APPLICATION_CREDENTIALS_JSON and FIREBASE_STORAGE_BUCKET
are both set in environment variables.
"""

from django.conf import settings
from storages.backends.gcloud import GoogleCloudStorage


class FirebaseStorage(GoogleCloudStorage):
    """
    Media file storage on Firebase (Google Cloud Storage).
    Files are stored under gs://<bucket>/media/ and served publicly.
    """

    def __init__(self, *args, **kwargs):
        bucket = getattr(settings, 'FIREBASE_STORAGE_BUCKET', None)
        if not bucket:
            raise ValueError(
                'FIREBASE_STORAGE_BUCKET is not set in settings.py'
            )
        kwargs.setdefault('bucket_name',     bucket)
        kwargs.setdefault('location',        'media')
        kwargs.setdefault('default_acl',     'publicRead')
        kwargs.setdefault('file_overwrite',  False)
        kwargs.setdefault('querystring_auth', False)
        super().__init__(*args, **kwargs)

    def url(self, name):
        """Return a direct public URL — no signed URL needed."""
        bucket = getattr(settings, 'FIREBASE_STORAGE_BUCKET', '')
        return f'https://storage.googleapis.com/{bucket}/media/{name}'


# Legacy alias — keeps existing imports working
FirebaseMediaStorage = FirebaseStorage