from django.urls import path
from .views import AccountDetailView, TransactionListView, AdminAccountListView, TransferView, OperatorTopupView, PlateTopupView

urlpatterns = [
    path('vehicle/<uuid:vehicle_id>/', AccountDetailView.as_view(), name='account-detail'),
    path('<uuid:account_id>/transactions/', TransactionListView.as_view(), name='transaction-list'),
    path('admin/all/', AdminAccountListView.as_view(), name='admin-accounts'),
    path('transfer/', TransferView.as_view(), name='balance-transfer'),
    path('operator/topup/', OperatorTopupView.as_view(), name='operator-topup'),
    path('topup/plate/', PlateTopupView.as_view(), name='plate-topup'),
]
