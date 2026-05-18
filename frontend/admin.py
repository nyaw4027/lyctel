from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import AboutPage, AboutStat, AboutFeature, TeamMember

class StatInline(admin.TabularInline):
    model = AboutStat
    extra = 1

class FeatureInline(admin.TabularInline):
    model = AboutFeature
    extra = 1

class TeamInline(admin.TabularInline):
    model = TeamMember
    extra = 1


@admin.register(AboutPage)
class AboutPageAdmin(admin.ModelAdmin):
    inlines = [StatInline, FeatureInline, TeamInline]