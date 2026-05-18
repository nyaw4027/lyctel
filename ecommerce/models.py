import uuid

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from accounts.managers import UserManager


class User(AbstractUser):

    # ─────────────────────────────
    # ROLE SYSTEM
    # ─────────────────────────────
    class Role(models.TextChoices):
        CUSTOMER = 'customer', _('Customer')
        ADMIN = 'admin', _('Admin')
        STAFF = 'staff', _('Staff')
        RIDER = 'rider', _('Rider')
        VENDOR = 'vendor', _('Vendor')

    # ─────────────────────────────
    # SAFE UUID (NOT PRIMARY KEY)
    # ─────────────────────────────
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True
    )

    # ─────────────────────────────
    # ROLE
    # ─────────────────────────────
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CUSTOMER,
        db_index=True
    )

    # ─────────────────────────────
    # PHONE VALIDATION
    # ─────────────────────────────
    phone_validator = RegexValidator(
        regex=r'^\+?[0-9]{9,15}$',
        message=_("Enter a valid phone number.")
    )

    phone = models.CharField(
        max_length=20,
        unique=True,
        validators=[phone_validator],
        db_index=True
    )

    email = models.EmailField(
        unique=True,
        blank=True,
        null=True
    )

    # ─────────────────────────────
    # PROFILE
    # ─────────────────────────────
    profile_pic = models.ImageField(
        upload_to='profiles/',
        blank=True,
        null=True
    )

    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    region = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, default='Ghana')

    date_of_birth = models.DateField(blank=True, null=True)
    bio = models.TextField(blank=True, null=True)

    # ─────────────────────────────
    # STATUS
    # ─────────────────────────────
    is_verified = models.BooleanField(default=False)
    is_phone_verified = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)

    # ─────────────────────────────
    # TIMESTAMPS
    # ─────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_seen = models.DateTimeField(blank=True, null=True)

    # ─────────────────────────────
    # AUTH CONFIG
    # ─────────────────────────────
    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = ['username', 'email']

    objects = UserManager()

    # ─────────────────────────────
    # ROLE HELPERS
    # ─────────────────────────────
    def is_customer(self):
        return self.role == self.Role.CUSTOMER

    def is_admin(self):
        return self.role == self.Role.ADMIN

    def is_staff_role(self):
        return self.role == self.Role.STAFF

    def is_vendor(self):
        return self.role == self.Role.VENDOR

    def is_rider(self):
        return self.role == self.Role.RIDER

    # ─────────────────────────────
    # DISPLAY HELPERS
    # ─────────────────────────────
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def display_name(self):
        return self.full_name or self.username or self.phone

    @property
    def initials(self):
        return (
            f"{self.first_name[:1] if self.first_name else ''}"
            f"{self.last_name[:1] if self.last_name else ''}"
        ).upper()

    @property
    def profile_picture_url(self):
        return self.profile_pic.url if self.profile_pic else '/static/images/default-avatar.png'

    # ─────────────────────────────
    # SAVE LOGIC
    # ─────────────────────────────
    def clean(self):
        super().clean()
        # Enforce only one admin in the system
        if self.role == self.Role.ADMIN:
            qs = User.objects.filter(role=self.Role.ADMIN)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    {"role": _("An admin user already exists. Only one admin is allowed.")}
                )

    def save(self, *args, **kwargs):
        self.full_clean()  # triggers clean() before every save

        if self.role == self.Role.ADMIN:
            self.is_staff = True
            self.is_superuser = True
        elif self.role == self.Role.STAFF:
            self.is_staff = True
            self.is_superuser = False
        else:
            self.is_staff = False
            self.is_superuser = False

        super().save(*args, **kwargs)

    # ─────────────────────────────
    # META
    # ─────────────────────────────
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['role']),
            models.Index(fields=['phone']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.display_name} ({self.role})"