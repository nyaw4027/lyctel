from django.apps import AppConfig


class FraudConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'fraud'

    def ready(self):
        import fraud.signals  # noqa: F401  (registers the pre_save/post_save hooks)