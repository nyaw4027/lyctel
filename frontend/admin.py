from django.contrib import admin
from django.utils.html import format_html
from .models import AboutPage, AboutStat, AboutFeature, TeamMember


class StatInline(admin.TabularInline):
    model = AboutStat
    extra = 1
    fields = ('order', 'label', 'value', 'icon')


class FeatureInline(admin.TabularInline):
    model = AboutFeature
    extra = 1
    fields = ('order', 'icon', 'title', 'description')


class TeamInline(admin.TabularInline):
    model = TeamMember
    extra = 1
    fields = ('order', 'image_preview', 'image', 'name', 'role', 'bio', 'is_active')
    readonly_fields = ('image_preview',)

    def image_preview(self, obj):
        if obj.pk and obj.image:
            return format_html(
                '<img src="{}" style="width:48px;height:48px;border-radius:8px;'
                'object-fit:cover;" />',
                obj.image.url,
            )
        return "—"
    image_preview.short_description = "Preview"


@admin.register(AboutPage)
class AboutPageAdmin(admin.ModelAdmin):
    inlines = [StatInline, FeatureInline, TeamInline]
    fieldsets = (
        ('Hero Section', {
            'fields': ('title', 'subtitle', 'hero_image'),
        }),
        ('Our Story', {
            'fields': ('story_title', 'story_text', 'story_image'),
        }),
        ('Call To Action', {
            'fields': ('cta_title', 'cta_text'),
        }),
    )

    def has_add_permission(self, request):
        # Only one AboutPage should ever exist — this is a singleton
        # CMS-style model. Hide the "Add" button once one exists.
        return not AboutPage.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Prevent accidentally deleting the only AboutPage, which would
        # leave the live site with no content to render.
        return False