from django.contrib import admin

from .models import Reservation, StockLot, StockMove, Warehouse


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("code", "name")


@admin.register(StockLot)
class StockLotAdmin(admin.ModelAdmin):
    list_display = (
        "lot_code",
        "item_name",
        "warehouse",
        "supplier_batch_code",
        "expiry_date",
        "unit_cost",
        "on_hand",
        "available",
    )
    search_fields = ("lot_code", "supplier_batch_code")
    list_filter = ("warehouse",)


@admin.register(StockMove)
class StockMoveAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "lot", "move_type", "quantity", "document")
    list_filter = ("move_type",)


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ("lot", "quantity", "purpose", "status")
    list_filter = ("purpose", "status")
