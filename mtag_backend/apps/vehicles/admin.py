from django.contrib import admin
from .models import Vehicle, Tag


class TagInline(admin.StackedInline):
    model = Tag
    extra = 0


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ['plate_number', 'owner', 'vehicle_type', 'status', 'registered_at']
    list_filter = ['vehicle_type', 'status']
    search_fields = ['plate_number', 'owner__phone']
    inlines = [TagInline]


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['tag_serial', 'vehicle', 'status', 'expiry_date', 'last_scanned_at']
    list_filter = ['status']
    search_fields = ['tag_serial']
