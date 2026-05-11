from django.contrib import admin
from .models import Plaza, TollLane, TollRate, TollTrip


class TollLaneInline(admin.TabularInline):
    model = TollLane
    extra = 0


@admin.register(Plaza)
class PlazaAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'is_active']
    inlines = [TollLaneInline]


@admin.register(TollRate)
class TollRateAdmin(admin.ModelAdmin):
    list_display = ['entry_plaza', 'exit_plaza', 'vehicle_type', 'rate', 'peak_multiplier', 'effective_from']
    list_filter = ['vehicle_type', 'entry_plaza', 'exit_plaza']


@admin.register(TollTrip)
class TollTripAdmin(admin.ModelAdmin):
    list_display = ['vehicle', 'entry_plaza', 'exit_plaza', 'charge_amount', 'status', 'entry_time']
    list_filter = ['status']
    search_fields = ['vehicle__plate_number']
    readonly_fields = ['entry_time', 'exit_time']
