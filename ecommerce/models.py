import re
import uuid

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from accounts.managers import UserManager


def normalize_phone(raw_phone):
    """
    Strip spaces, dashes, and any other formatting characters that people
    naturally type into a phone number — e.g. "024 665 2183" or
    "024-665-2183" both become "0246652183". Keeps digits and a leading
    '+' (for the +233... international format) only.

    This MUST be used consistently everywhere a phone number is created
    OR looked up (signup, login, password reset), otherwise a user who
    types their number with spaces at signup but without spaces at login
    (or vice versa) will silently fail to match.
    """
    if not raw_phone:
        return raw_phone
    return re.sub(r'[^\d+]', '', raw_phone)


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
        db_index=True,
    )

    # ═══════════════════════════════
    # ROLE
    # ═══════════════════════════════
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CUSTOMER,
        db_index=True,
    )

    # ═══════════════════════════════
    # GHANA PHONE VALIDATOR
    # ═══════════════════════════════
    phone_validator = RegexValidator(
        regex=r'^(?:\+233\d{9}|233\d{9}|0\d{9})$',
        message=_(
            "Enter a valid Ghana phone number. "
            "Example: 0558040216 or +233558040216"
        ),
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
        null=True,
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
        default=None,
    )

    # ═══════════════════════════════
    # PROFILE
    # ═══════════════════════════════
    profile_pic = models.ImageField(
        upload_to='profiles/',
        blank=True,
        null=True,
    )

    address       = models.TextField(blank=True, null=True)
    city          = models.CharField(max_length=100, blank=True, null=True)
    region        = models.CharField(max_length=100, blank=True, null=True)
    country       = models.CharField(max_length=100, default='Ghana')
    date_of_birth = models.DateField(blank=True, null=True)
    bio           = models.TextField(blank=True, null=True)

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
    def is_customer(self):   return self.role == self.Role.CUSTOMER
    def is_admin_role(self): return self.role == self.Role.ADMIN
    def is_staff_role(self): return self.role == self.Role.STAFF
    def is_vendor(self):     return self.role == self.Role.VENDOR
    def is_rider(self):      return self.role == self.Role.RIDER

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

        # Normalise: convert empty string email → None so the unique
        # constraint only fires on real emails.
        if self.email == '':
            self.email = None

        # Enforce single-admin rule
        if self.role == self.Role.ADMIN:
            qs = User.objects.filter(role=self.Role.ADMIN)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({
                    'role': _('Only one admin user is allowed.')
                })

    # ═══════════════════════════════
    # SAVE LOGIC
    # ═══════════════════════════════
    def save(self, *args, **kwargs):

        # ── Normalize phone FIRST — strip spaces/dashes that people
        # naturally type (e.g. "024 665 2183" → "0246652183"). This must
        # happen before full_clean() validates the format, and before
        # username is derived from it below.
        if self.phone:
            self.phone = normalize_phone(self.phone)

        # ── username always mirrors the normalized phone in this app —
        # every signup/apply flow passes username=phone anyway, so this
        # keeps them in sync as a single source of truth rather than
        # silently carrying forward a stale, unnormalized value that was
        # set before this point (e.g. via create_user's username=phone).
        if self.phone:
            self.username = self.phone

        # ── Normalise empty email → None BEFORE full_clean
        if self.email == '':
            self.email = None

        # ── Permission mapping by role
        if self.role == self.Role.ADMIN:
            self.is_staff     = True
            self.is_superuser = True
        elif self.role == self.Role.STAFF:
            self.is_staff     = True
            self.is_superuser = False
        else:
            self.is_staff     = False
            self.is_superuser = False

        # ── Run validation.
        # Always exclude 'email' (NULL is valid for multiple users).
        # Also exclude 'phone' when it is blank so that admin-created
        # users without a phone don't blow up on the validator.
        # Also exclude 'username' uniqueness check here — Django's
        # AbstractUser validator raises an error during create because
        # it tries to validate uniqueness before the row exists; the
        # database unique constraint handles it correctly anyway.
        exclude = ['email']
        if not self.phone:
            exclude.append('phone')

        try:
            self.full_clean(exclude=exclude)
        except ValidationError as e:
            # Re-raise everything EXCEPT the username uniqueness error
            # that Django's own validator fires spuriously during creation.
            errors = e.message_dict if hasattr(e, 'message_dict') else {}
            filtered = {
                field: msgs
                for field, msgs in errors.items()
                if not (field == 'username' and any(
                    'already exists' in str(m) for m in msgs
                ))
            }
            if filtered:
                raise ValidationError(filtered)

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




class PushSubscription(models.Model):
    """Stores browser push subscription info per user per device."""
    user       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='push_subscriptions',
    )
    endpoint   = models.TextField(unique=True)
    p256dh     = models.TextField()
    auth       = models.TextField()
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def to_dict(self):
        """Returns subscription info dict for pywebpush."""
        return {
            'endpoint': self.endpoint,
            'keys': {
                'p256dh': self.p256dh,
                'auth':   self.auth,
            },
        }

    def __str__(self):
        return f"{self.user.username} - {self.endpoint[:50]}"
