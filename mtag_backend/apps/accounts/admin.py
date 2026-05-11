from django.contrib import admin
from .models import Account, Transaction


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ['vehicle', 'user', 'balance', 'balance_updated_at']
    search_fields = ['vehicle__plate_number', 'user__phone']
    readonly_fields = ['balance_updated_at', 'created_at']


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['account', 'transaction_type', 'amount', 'balance_after', 'status', 'processed_at']
    list_filter = ['transaction_type', 'status']
    search_fields = ['account__vehicle__plate_number', 'tag_serial']
    readonly_fields = ['processed_at']
