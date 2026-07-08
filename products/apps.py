# products/apps.py
from django.apps import AppConfig

class ProductsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'products'

    def ready(self):
        try:
            from pillow_heif import register_heif_opener
        except ImportError:
            return

        register_heif_opener()