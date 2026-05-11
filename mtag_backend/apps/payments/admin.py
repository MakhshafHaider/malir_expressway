from django.contrib import admin
from .models import TopupRequest


@admin.register(TopupRequest)
class TopupRequestAdmin(admin.ModelAdmin):
    list_display = ['account', 'user', 'amount', 'status', 'jazzcash_txn_id', 'requested_at']
    list_filter = ['status']
    search_fields = ['account__vehicle__plate_number', 'jazzcash_txn_id']
    readonly_fields = ['requested_at', 'completed_at']
