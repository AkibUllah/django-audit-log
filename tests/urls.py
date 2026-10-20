from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from audit_log.drf import AuditEntryViewSet
from tests.testapp.models import Book

router = DefaultRouter()
router.register("audit", AuditEntryViewSet, basename="audit")


def rename_book(request, pk):
    book = Book.objects.get(pk=pk)
    book.title = request.GET.get("title", book.title)
    book.save()
    return JsonResponse({"id": book.pk, "title": book.title})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    path("books/<int:pk>/rename/", rename_book),
]
