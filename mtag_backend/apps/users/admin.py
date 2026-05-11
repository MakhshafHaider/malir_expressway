from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['phone', 'full_name', 'user_role', 'status', 'created_at']
    list_filter = ['user_role', 'status']
    search_fields = ['phone', 'full_name', 'cnic']
    ordering = ['-id']
    fieldsets = (
        (None, {'fields': ('phone', 'password')}),
        ('Personal', {'fields': ('full_name', 'cnic')}),
        ('Permissions', {'fields': ('user_role', 'status', 'is_staff', 'is_superuser')}),
    )
    add_fieldsets = (
        (None, {'fields': ('phone', 'full_name', 'password1', 'password2')}),
    )
