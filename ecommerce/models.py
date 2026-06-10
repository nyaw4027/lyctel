import uuid

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from accounts.managers import UserManager


class User(AbstractUser):

    # ═══════════════════════════════
    # ROLE SYSTEM
    # ═══════════════════════════════
    class Role(models.TextChoices):
        CUSTOMER = 'customer', _('Customer')
        ADMIN    = 'admin',    _('Admin')
        STAFF    = 'staff',    _('Staff')
        RIDER    = 'rider',    _('Rider')
        VENDOR   = 'vendor',   _('Vendor')

    # ═══════════════════════════════
    # UUID
    # ═══════════════════════════════
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True
    )

    # ═══════════════════════════════
    # ROLE
    # ═══════════════════════════════
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CUSTOMER,
        db_index=True
    )

    # ═══════════════════════════════
    # GHANA PHONE VALIDATOR
    # ═══════════════════════════════
    phone_validator = RegexValidator(
        regex=r'^(?:\+233\d{9}|233\d{9}|0\d{9})$',
        message=_(
            "Enter a valid Ghana phone number. "
            "Example: 0558040216 or +233558040216"
        )
    )

    # ═══════════════════════════════
    # PHONE
    # ═══════════════════════════════
    phone = models.CharField(
        max_length=15,
        unique=True,
        validators=[phone_validator],
        db_index=True,
        blank=True,
        null=True
    )

    # ═══════════════════════════════
    # EMAIL  — NULL so multiple users
    # can have no email without
    # hitting the unique constraint
    # ═══════════════════════════════
    email = models.EmailField(
        unique=True,
        blank=True,
        null=True,
        default=None,     # ← store NULL, never empty string ""
    )

    # ═══════════════════════════════
    # PROFILE
    # ═══════════════════════════════
    profile_pic = models.ImageField(
        upload_to='profiles/',
        blank=True,
        null=True
    )

    address        = models.TextField(blank=True, null=True)
    city           = models.CharField(max_length=100, blank=True, null=True)
    region         = models.CharField(max_length=100, blank=True, null=True)
    country        = models.CharField(max_length=100, default='Ghana')
    date_of_birth  = models.DateField(blank=True, null=True)
    bio            = models.TextField(blank=True, null=True)

    # ═══════════════════════════════
    # STATUS
    # ═══════════════════════════════
    is_verified       = models.BooleanField(default=False)
    is_phone_verified = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)

    # ═══════════════════════════════
    # TIMESTAMPS
    # ═══════════════════════════════
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_seen  = models.DateTimeField(blank=True, null=True)

    # ═══════════════════════════════
    # AUTH CONFIG
    # ═══════════════════════════════
    USERNAME_FIELD  = 'phone'
    REQUIRED_FIELDS = ['username']
    objects         = UserManager()

    # ═══════════════════════════════
    # ROLE HELPERS
    # ═══════════════════════════════
    def is_customer(self):    return self.role == self.Role.CUSTOMER
    def is_admin_role(self):  return self.role == self.Role.ADMIN
    def is_staff_role(self):  return self.role == self.Role.STAFF
    def is_vendor(self):      return self.role == self.Role.VENDOR
    def is_rider(self):       return self.role == self.Role.RIDER

    # ═══════════════════════════════
    # DISPLAY HELPERS
    # ═══════════════════════════════
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def display_name(self):
        return self.full_name or self.username or self.phone or "User"

    @property
    def initials(self):
        return (
            f"{self.first_name[:1] if self.first_name else ''}"
            f"{self.last_name[:1]  if self.last_name  else ''}"
        ).upper()

    @property
    def profile_picture_url(self):
        if self.profile_pic:
            return self.profile_pic.url
        return '/static/images/default-avatar.png'

    # ═══════════════════════════════
    # CLEAN VALIDATION
    # ═══════════════════════════════
    def clean(self):
        super().clean()

        # Normalise: convert empty string email → None
        # so the unique constraint only fires on real emails,
        # not on multiple users with email=""
        if self.email == '':
            self.email = None

        # Enforce single-admin rule
        if self.role == self.Role.ADMIN:
            qs = User.objects.filter(role=self.Role.ADMIN)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({
                    "role": _("Only one admin user is allowed.")
                })

    # ═══════════════════════════════
    # SAVE LOGIC
    # ═══════════════════════════════
    def save(self, *args, **kwargs):

        # Auto-generate username if empty
        if not self.username and self.phone:
            self.username = self.phone

        # Normalise empty email → None BEFORE full_clean
        if self.email == '':
            self.email = None

        # Permission mapping by role
        if self.role == self.Role.ADMIN:
            self.is_staff      = True
            self.is_superuser  = True
        elif self.role == self.Role.STAFF:
            self.is_staff      = True
            self.is_superuser  = False
        else:
            self.is_staff      = False
            self.is_superuser  = False

        # Run validation — but EXCLUDE email from uniqueness check
        # when email is None (multiple null values are allowed in postgres/sqlite)
        exclude = []
        if not self.email:
            exclude.append('email')
        self.full_clean(exclude=exclude)

        super().save(*args, **kwargs)

    # ═══════════════════════════════
    # META
    # ═══════════════════════════════
    class Meta:
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['role']),
            models.Index(fields=['phone']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.display_name} ({self.role})"