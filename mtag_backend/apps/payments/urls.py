from django.urls import path
from .views import InitiateTopupView, JazzCashCallbackView, TopupHistoryView

urlpatterns = [
    path('topup/', InitiateTopupView.as_view(), name='initiate-topup'),
    path('jazzcash/callback/', JazzCashCallbackView.as_view(), name='jazzcash-callback'),
    path('history/<uuid:account_id>/', TopupHistoryView.as_view(), name='topup-history'),
]
