from django.contrib import admin

from .models import BatchConsumption, ProductionBatch, ProductionOverhead


class ConsumptionInline(admin.TabularInline):
    model = BatchConsumption
    extra = 0
    readonly_fields = ("lot", "quantity", "unit_cost")


class OverheadInline(admin.TabularInline):
    model = ProductionOverhead
    extra = 1


@admin.register(ProductionBatch)
class ProductionBatchAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "product",
        "recipe_version",
        "planned_quantity",
        "actual_quantity",
        "yield_percent",
        "status",
    )
    list_filter = ("status", "product")
    search_fields = ("number",)
    inlines = [ConsumptionInline, OverheadInline]
