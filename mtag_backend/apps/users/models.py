import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from .managers import UserManager


class UserRole(models.TextChoices):
    USER = 'user', 'User'
    ADMIN = 'admin', 'Admin'
    OPERATOR = 'operator', 'Operator'


class UserStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    INACTIVE = 'inactive', 'Inactive'
    BLOCKED = 'blocked', 'Blocked'


class User(AbstractBaseUser, PermissionsMixin):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    full_name = models.CharField(max_length=100)
    cnic = models.CharField(max_length=15, unique=True, null=True, blank=True)
    phone = models.CharField(max_length=20, unique=True)
    user_role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.USER)
    status = models.CharField(max_length=20, choices=UserStatus.choices, default=UserStatus.ACTIVE)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='created_users'
    )
    last_login_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = ['full_name']

    class Meta:
        db_table = 'users'
        indexes = [
            models.Index(fields=['phone']),
            models.Index(fields=['cnic']),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.phone})"
