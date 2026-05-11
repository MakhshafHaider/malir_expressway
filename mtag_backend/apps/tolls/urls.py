from django.urls import path
from .views import (
    VehicleEntryView, VehicleExitView, TripHistoryView,
    PlazaListView, TollRateListView, AdminTripListView,
    AdminPlazaView, AdminPlazaDetailView, AdminLaneView,
    AdminTollRateView, AdminRateDetailView, AdminStatsView,
    AdminTripCloseView, AdminTripRefundView, AdminGateEventListView,
)

urlpatterns = [
    path('entry/', VehicleEntryView.as_view(), name='toll-entry'),
    path('exit/', VehicleExitView.as_view(), name='toll-exit'),
    path('plazas/', PlazaListView.as_view(), name='plaza-list'),
    path('rates/', TollRateListView.as_view(), name='rate-list'),
    path('trips/<uuid:vehicle_id>/', TripHistoryView.as_view(), name='trip-history'),
    path('admin/trips/', AdminTripListView.as_view(), name='admin-trips'),
    path('admin/trips/<uuid:trip_id>/close/', AdminTripCloseView.as_view(), name='admin-trip-close'),
    path('admin/trips/<uuid:trip_id>/refund/', AdminTripRefundView.as_view(), name='admin-trip-refund'),
    path('admin/stats/', AdminStatsView.as_view(), name='admin-stats'),
    path('admin/gate-events/', AdminGateEventListView.as_view(), name='admin-gate-events'),
    path('admin/plazas/', AdminPlazaView.as_view(), name='admin-plaza-list'),
    path('admin/plazas/<uuid:pk>/', AdminPlazaDetailView.as_view(), name='admin-plaza-detail'),
    path('admin/plazas/<uuid:plaza_id>/lanes/', AdminLaneView.as_view(), name='admin-lane-create'),
    path('admin/rates/', AdminTollRateView.as_view(), name='admin-rate-create'),
    path('admin/rates/<uuid:pk>/', AdminRateDetailView.as_view(), name='admin-rate-detail'),
]
