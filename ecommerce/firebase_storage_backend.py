from django.conf import settings
from storages.backends.gcloud import GoogleCloudStorage


class FirebaseStorage(GoogleCloudStorage):
    """
    Firebase / GCS storage backend
    """

    def __init__(self, *args, **kwargs):
        bucket = getattr(settings, "GS_BUCKET_NAME", None)

        if not bucket:
            # DO NOT crash entire app
            raise RuntimeError(
                "GS_BUCKET_NAME is missing. Check FIREBASE_STORAGE_BUCKET env var."
            )

        kwargs.setdefault("bucket_name", bucket)
        kwargs.setdefault("location", "media")
        kwargs.setdefault("file_overwrite", False)
        kwargs.setdefault("querystring_auth", False)
        kwargs.setdefault("default_acl", None)

        super().__init__(*args, **kwargs)

    def url(self, name):
        bucket = getattr(settings, "GS_BUCKET_NAME", None)
        if not bucket:
            return ""

        return f"https://storage.googleapis.com/{bucket}/media/{name}"


FirebaseMediaStorage = FirebaseStorage