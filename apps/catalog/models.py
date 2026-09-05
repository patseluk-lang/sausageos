from django.db import models

from apps.core.models import TimeStampedModel


class Unit(models.TextChoices):
    KG = "KG", "kg"
    G = "G", "g"
    L = "L", "l"
    PCS = "PCS", "pcs"
    M = "M", "m"


class MaterialCategory(models.TextChoices):
    RAW = "RAW", "Raw material"
    SPICE = "SPICE", "Spices"
    CASING = "CASING", "Casing"
    PACKAGING = "PACKAGING", "Packaging"
    OTHER = "OTHER", "Other"


class Supplier(TimeStampedModel):
    name = models.CharField(max_length=255, unique=True)
    tax_id = models.CharField("Tax ID", max_length=16, blank=True)
    contact = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Supplier"
        verbose_name_plural = "Suppliers"

    def __str__(self) -> str:
        return self.name


class Material(TimeStampedModel):
    """Raw material catalog. The price is not fixed here — it belongs to the stock lot."""

    name = models.CharField(max_length=255, unique=True)
    sku = models.CharField("SKU", max_length=32, unique=True)
    category = models.CharField(
        max_length=16, choices=MaterialCategory.choices, default=MaterialCategory.RAW
    )
    unit = models.CharField(max_length=8, choices=Unit.choices, default=Unit.KG)
    min_stock = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    shelf_life_days = models.PositiveIntegerField("Shelf life, days", default=0)
    default_supplier = models.ForeignKey(
        Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="materials"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Material"
        verbose_name_plural = "Materials"

    def __str__(self) -> str:
        return f"{self.name} ({self.sku})"


class Product(TimeStampedModel):
    """Finished product."""

    name = models.CharField(max_length=255, unique=True)
    sku = models.CharField("SKU", max_length=32, unique=True)
    unit = models.CharField(max_length=8, choices=Unit.choices, default=Unit.KG)
    target_margin = models.DecimalField(
        "Target margin, %", max_digits=5, decimal_places=2, default=33.30
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Finished product"
        verbose_name_plural = "Finished products"

    def __str__(self) -> str:
        return self.name
