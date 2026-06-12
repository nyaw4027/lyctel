from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    """
    Custom manager for the User model.

    KEY FIX: The original manager never set `username`, which caused
    full_clean() inside User.save() to raise a validation error silently —
    meaning users appeared to sign up successfully but were never written
    to the database.
    """

    def create_user(self, phone, password=None, **extra_fields):
        if not phone:
            raise ValueError("Phone number is required")

        # ── username is in REQUIRED_FIELDS so it must always be set.
        # Default it to the phone number if the caller didn't supply one.
        if not extra_fields.get('username'):
            extra_fields['username'] = phone

        # ── Normalise empty email → None so the unique constraint does
        # not fire when multiple users have no email address.
        if extra_fields.get('email') == '':
            extra_fields['email'] = None

        # ── is_active must default to True or the user can't log in.
        extra_fields.setdefault('is_active', True)

        user = self.model(phone=phone, **extra_fields)
        user.set_password(password)

        # User.save() already calls full_clean() internally, so we call
        # save() without using=self._db to go through that path and pick
        # up the role → is_staff / is_superuser permission mapping too.
        user.save()

        return user

    def create_superuser(self, phone, password=None, **extra_fields):
        extra_fields.setdefault('role',         'admin')
        extra_fields.setdefault('is_staff',     True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active',    True)

        # Ensure username is set for the superuser too
        if not extra_fields.get('username'):
            extra_fields['username'] = phone

        return self.create_user(phone, password, **extra_fields)