from django.contrib import admin

from .models import Customer, Order, OrderLine


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    extra = 1


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "contact", "address")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "customer", "status", "ordered_at", "total")
    list_filter = ("status",)
    inlines = [OrderLineInline]
