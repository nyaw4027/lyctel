"""
ecommerce/firebase_storage_backend.py
Lazy import — only loads Google Cloud Storage when actually used,
so the app starts fine even if google-cloud-storage isn't installed locally.
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class FirebaseMediaStorage:
    """
    Proxy — defers the GoogleCloudStorage import until first file operation.
    This prevents a startup crash when google-cloud-storage isn't installed.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            try:
                from storages.backends.gcloud import GoogleCloudStorage
            except (ImportError, ImproperlyConfigured) as e:
                raise ImproperlyConfigured(
                    f'Firebase Storage requires google-cloud-storage. '
                    f'Add it to requirements.txt. Error: {e}'
                )

            class _Backend(GoogleCloudStorage):
                def __init__(self):
                    super().__init__(
                        bucket_name=getattr(settings, 'FIREBASE_STORAGE_BUCKET',
                                            'lynctel-dd634.appspot.com'),
                        location='media',
                        default_acl='publicRead',
                    )

            cls._instance = _Backend()

        return cls._instance