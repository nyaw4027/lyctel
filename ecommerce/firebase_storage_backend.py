"""
ecommerce/firebase_storage_backend.py
"""

from storages.backends.gcloud import GoogleCloudStorage
from django.conf import settings


class FirebaseStorage(GoogleCloudStorage):
    """
    Google Cloud Storage backend for Firebase Storage.
    """

    bucket_name = getattr(settings, "GS_BUCKET_NAME", None)
    location = "media"
    file_overwrite = False
    querystring_auth = False
    default_acl = None

    def url(self, name):
        if not self.bucket_name:
            return ""

        return (
            f"https://storage.googleapis.com/"
            f"{self.bucket_name}/media/{name}"
        )


FirebaseMediaStorage = FirebaseStorage