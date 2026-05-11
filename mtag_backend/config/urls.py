from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/auth/', include('apps.users.urls')),
    path('api/v1/vehicles/', include('apps.vehicles.urls')),
    path('api/v1/accounts/', include('apps.accounts.urls')),
    path('api/v1/tolls/', include('apps.tolls.urls')),
    path('api/v1/payments/', include('apps.payments.urls')),
]
