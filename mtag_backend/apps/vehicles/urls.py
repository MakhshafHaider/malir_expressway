from django.urls import path
from .views import VehicleListCreateView, VehicleDetailView, VehicleByPlateView, TagReissueView, AvailableTagsView, TagInventoryUploadView, TagCreateView, VehicleSuspendView

urlpatterns = [
    path('', VehicleListCreateView.as_view(), name='vehicle-list'),
    path('<uuid:pk>/', VehicleDetailView.as_view(), name='vehicle-detail'),
    path('<uuid:pk>/suspend/', VehicleSuspendView.as_view(), name='vehicle-suspend'),
    path('plate/<str:plate_number>/', VehicleByPlateView.as_view(), name='vehicle-by-plate'),
    path('tags/', TagCreateView.as_view(), name='tag-create'),
    path('tags/available/', AvailableTagsView.as_view(), name='available-tags'),
    path('tags/upload/', TagInventoryUploadView.as_view(), name='tag-upload'),
    path('tags/<uuid:vehicle_id>/reissue/', TagReissueView.as_view(), name='tag-reissue'),
]
