from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from audit_log.drf import AuditEntryViewSet

router = DefaultRouter()
router.register("audit", AuditEntryViewSet, basename="audit")


def health(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    path("health/", health),
]
