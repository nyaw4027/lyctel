"""
firebase_storage_backend.py
Place this file at: ecommerce/firebase_storage_backend.py
(or any importable path, then update STORAGES in settings.py)

Firebase Storage uses Google Cloud Storage under the hood,
so we use django-storages[google] — no extra Firebase library needed.
"""

from storages.backends.gcloud import GoogleCloudStorage
from django.conf import settings


class FirebaseMediaStorage(GoogleCloudStorage):
    """Stores user-uploaded media (product images, etc.) in Firebase Storage."""
    bucket_name = settings.FIREBASE_STORAGE_BUCKET
    location = "media"                 # files go under gs://bucket/media/
    default_acl = "publicRead"         # publicly accessible URLs


class FirebaseStaticStorage(GoogleCloudStorage):
    """Stores Django static files in Firebase Storage."""
    bucket_name = settings.FIREBASE_STORAGE_BUCKET
    location = "static"                # files go under gs://bucket/static/
    default_acl = "publicRead"