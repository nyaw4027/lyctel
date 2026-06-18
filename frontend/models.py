from django.db import models


class AboutPage(models.Model):
    """Singleton-style model — only one instance should ever exist.
    Enforced via AboutPageAdmin.has_add_permission in admin.py."""

    title = models.CharField(max_length=200, default="About Lynctel")
    subtitle = models.TextField(blank=True)

    hero_image = models.ImageField(upload_to='about/', blank=True, null=True)
    story_image = models.ImageField(upload_to='about/', blank=True, null=True)

    story_title = models.CharField(max_length=200, default="Our Story")
    story_text = models.TextField(blank=True)

    cta_title = models.CharField(max_length=200, default="Ready to experience Lynctel?")
    cta_text = models.TextField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "About Page"
        verbose_name_plural = "About Page"

    def __str__(self):
        return "About Page Content"

    def save(self, *args, **kwargs):
        # Enforce singleton at the model level too, as a safety net
        # beyond the admin-level has_add_permission lock.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        """Always returns the single AboutPage instance, creating it
        with sensible defaults on first access if it doesn't exist yet."""
        obj, _ = cls.objects.get_or_create(pk=1, defaults={
            'story_text': 'Lynctel was created to modernize ecommerce across '
                           'Ghana and Africa by building a reliable platform '
                           'where customers, vendors, and riders can thrive together.',
        })
        return obj


class AboutStat(models.Model):
    page = models.ForeignKey(AboutPage, on_delete=models.CASCADE, related_name="stats")
    label = models.CharField(max_length=100)
    value = models.CharField(max_length=50)
    icon = models.CharField(max_length=20, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.label


class AboutFeature(models.Model):
    page = models.ForeignKey(AboutPage, on_delete=models.CASCADE, related_name="features")
    title = models.CharField(max_length=100)
    description = models.TextField()
    icon = models.CharField(max_length=20, default="⭐")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.title


class TeamMember(models.Model):
    page = models.ForeignKey(AboutPage, on_delete=models.CASCADE, related_name="team")
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=100)
    bio = models.TextField(blank=True)
    image = models.ImageField(upload_to='team/', blank=True, null=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(
        default=True,
        help_text="Uncheck to hide this person from the live site without deleting them."
    )

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.name