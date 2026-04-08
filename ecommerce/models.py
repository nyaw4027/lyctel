from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        CUSTOMER = 'customer', 'Customer'
        ADMIN    = 'admin',    'Admin'
        RIDER    = 'rider',    'Rider'

    role        = models.CharField(max_length=10, choices=Role.choices, default=Role.CUSTOMER)
    phone       = models.CharField(max_length=15, unique=True)
    profile_pic = models.ImageField(upload_to='profiles/', blank=True, null=True)
    address     = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD  = 'phone'
    REQUIRED_FIELDS = ['username', 'email']

    def is_customer(self): return self.role == self.Role.CUSTOMER
    def is_admin(self):    return self.role == self.Role.ADMIN
    def is_rider(self):    return self.role == self.Role.RIDER

    def __str__(self):
        return f"{self.get_full_name()} ({self.role}) — {self.phone}"