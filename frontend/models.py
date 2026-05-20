from django.db import models

# Create your models here.
from django.db import models

class AboutPage(models.Model):
    title = models.CharField(max_length=200, default="About Lynctel")
    subtitle = models.TextField(blank=True)

    hero_image = models.ImageField(upload_to='about/', blank=True, null=True)
    story_image = models.ImageField(upload_to='about/', blank=True, null=True)

    story_title = models.CharField(max_length=200, default="Our Story")
    story_text = models.TextField()

    cta_title = models.CharField(max_length=200, default="Ready to experience Lynctel?")
    cta_text = models.TextField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "About Page Content"


class AboutStat(models.Model):
    page = models.ForeignKey(AboutPage, on_delete=models.CASCADE, related_name="stats")
    label = models.CharField(max_length=100)
    value = models.CharField(max_length=50)
    icon = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.label


class AboutFeature(models.Model):
    page = models.ForeignKey(AboutPage, on_delete=models.CASCADE, related_name="features")
    title = models.CharField(max_length=100)
    description = models.TextField()
    icon = models.CharField(max_length=20, default="⭐")

    def __str__(self):
        return self.title


class TeamMember(models.Model):
    page = models.ForeignKey(AboutPage, on_delete=models.CASCADE, related_name="team")
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=100)
    bio = models.TextField(blank=True)
    image = models.ImageField(upload_to='team/')

    def __str__(self):
        return self.name