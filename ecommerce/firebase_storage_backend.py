from django.conf import settings


class FirebaseStorage:
    """
    Firebase / Google Cloud Storage backend.

    Only instantiated when GOOGLE_APPLICATION_CREDENTIALS_JSON and
    FIREBASE_STORAGE_BUCKET are both set in environment variables.
    If Firebase is not configured, Django uses FileSystemStorage instead
    (controlled in settings.py) and this class is never called.
    """

    def __new__(cls, *args, **kwargs):
        # Lazy import — only pulled in when Firebase is actually in use
        from storages.backends.gcloud import GoogleCloudStorage

        class _FirebaseStorage(GoogleCloudStorage):

            def __init__(self, *args, **kwargs):
                bucket = getattr(settings, 'GS_BUCKET_NAME', None)
                if not bucket:
                    raise RuntimeError(
                        'GS_BUCKET_NAME is not set. '
                        'Set FIREBASE_STORAGE_BUCKET in your Railway variables.'
                    )
                kwargs.setdefault('bucket_name',      bucket)
                kwargs.setdefault('location',         'media')
                kwargs.setdefault('file_overwrite',   False)
                kwargs.setdefault('querystring_auth', False)
                kwargs.setdefault('default_acl',      'publicRead')
                super().__init__(*args, **kwargs)

            def url(self, name):
                bucket = getattr(settings, 'GS_BUCKET_NAME', '')
                if not bucket or not name:
                    return ''
                # Strip any leading 'media/' prefix that GCS might add
                clean = name.lstrip('/')
                if clean.startswith('media/'):
                    clean = clean[len('media/'):]
                return f'https://storage.googleapis.com/{bucket}/media/{clean}'

        return _FirebaseStorage(*args, **kwargs)


# Legacy alias — keeps any existing imports working
FirebaseMediaStorage = FirebaseStorage