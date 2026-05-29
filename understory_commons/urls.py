from django.contrib import admin
from django.urls import include, path

from core.views import healthz

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz, name="healthz"),
    path("auth/", include("accounts.urls")),
    path("coordinator/programs/", include("attendance.urls")),
    path("programs/", include("discovery.urls")),
]
