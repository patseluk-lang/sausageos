from django.contrib import admin

from .models import Material, Product, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "tax_id", "contact", "is_active")
    search_fields = ("name", "tax_id")


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "category", "unit", "min_stock", "default_supplier")
    list_filter = ("category", "unit", "is_active")
    search_fields = ("name", "sku")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "unit", "target_margin", "is_active")
    search_fields = ("name", "sku")
