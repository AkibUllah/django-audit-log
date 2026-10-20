from django.contrib import admin

from .models import Customer, Order, Product, Tag


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "price_bdt", "is_active")
    filter_horizontal = ("tags",)


admin.site.register(Tag)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "product", "quantity", "status", "total_bdt")
    list_filter = ("status",)
