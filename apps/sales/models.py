from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.models import TimeStampedModel


class OrderStatus(models.TextChoices):
    NEW = "NEW", "New"
    CONFIRMED = "CONFIRMED", "Confirmed"
    RESERVED = "RESERVED", "Reserved"
    PAID = "PAID", "Paid"
    PROCESSING = "PROCESSING", "Processing"
    SHIPPED = "SHIPPED", "Shipped"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class Customer(TimeStampedModel):
    name = models.CharField(max_length=255, unique=True)
    contact = models.CharField(max_length=255, blank=True)
    address = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Customer"
        verbose_name_plural = "Customers"

    def __str__(self) -> str:
        return self.name


class Order(TimeStampedModel):
    number = models.CharField(max_length=32, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=16, choices=OrderStatus.choices, default=OrderStatus.NEW)
    warehouse = models.ForeignKey(
        "inventory.Warehouse", on_delete=models.PROTECT, related_name="orders"
    )
    ordered_at = models.DateField(default=timezone.localdate)
    shipped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-ordered_at", "-id")
        verbose_name = "Order"
        verbose_name_plural = "Orders"

    def __str__(self) -> str:
        return f"Order {self.number}"

    @property
    def total(self) -> Decimal:
        return sum((line.total for line in self.lines.all()), Decimal("0"))


class OrderLine(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_lines")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    price = models.DecimalField("Unit price, UAH", max_digits=12, decimal_places=2)

    class Meta:
        unique_together = ("order", "product")
        verbose_name = "Order line"
        verbose_name_plural = "Order lines"

    def __str__(self) -> str:
        return f"{self.product.name}: {self.quantity}"

    @property
    def total(self) -> Decimal:
        return (self.quantity * self.price).quantize(Decimal("0.01"))
