from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.models import TimeStampedModel
from apps.recipes.models import RecipeVersion


class BatchStatus(models.TextChoices):
    PLANNED = "PLANNED", "Planned"
    RESERVED = "RESERVED", "Materials reserved"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    DONE = "DONE", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


class ProductionBatch(TimeStampedModel):
    number = models.CharField("Batch number", max_length=32, unique=True)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="batches")
    recipe_version = models.ForeignKey(
        RecipeVersion, on_delete=models.PROTECT, related_name="batches"
    )
    planned_quantity = models.DecimalField("Planned, kg", max_digits=12, decimal_places=3)
    actual_quantity = models.DecimalField(
        "Actual, kg", max_digits=12, decimal_places=3, null=True, blank=True
    )
    status = models.CharField(
        max_length=16, choices=BatchStatus.choices, default=BatchStatus.PLANNED
    )
    source_warehouse = models.ForeignKey(
        "inventory.Warehouse", on_delete=models.PROTECT, related_name="production_source"
    )
    output_warehouse = models.ForeignKey(
        "inventory.Warehouse", on_delete=models.PROTECT, related_name="production_output"
    )
    planned_date = models.DateField(default=timezone.localdate)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-planned_date", "-id")
        verbose_name = "Production batch"
        verbose_name_plural = "Production batches"

    def __str__(self) -> str:
        return f"Batch {self.number} — {self.product.name}"

    @property
    def loaded_quantity(self) -> Decimal:
        """Weight of the primary raw material loaded into the mince.

        The yield norm is measured against the meat raw material (category RAW);
        spices, casing and packaging are not part of the yield base.
        """
        from apps.catalog.models import MaterialCategory

        total = Decimal("0")
        for line in self.consumptions.select_related("lot__material"):
            if line.lot.material and line.lot.material.category == MaterialCategory.RAW:
                total += line.quantity
        return total

    @property
    def yield_percent(self) -> Decimal | None:
        loaded = self.loaded_quantity
        if not self.actual_quantity or loaded <= 0:
            return None
        return (self.actual_quantity / loaded * Decimal("100")).quantize(Decimal("0.01"))

    @property
    def loss_quantity(self) -> Decimal | None:
        if self.actual_quantity is None:
            return None
        return (self.loaded_quantity - self.actual_quantity).quantize(Decimal("0.001"))

    @property
    def yield_is_below_norm(self) -> bool:
        y = self.yield_percent
        return y is not None and y < self.recipe_version.yield_min


class BatchConsumption(models.Model):
    """Material actually consumed by a batch — the basis of costing and traceability."""

    batch = models.ForeignKey(
        ProductionBatch, on_delete=models.CASCADE, related_name="consumptions"
    )
    lot = models.ForeignKey(
        "inventory.StockLot", on_delete=models.PROTECT, related_name="consumptions"
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4)

    class Meta:
        verbose_name = "Material consumption"
        verbose_name_plural = "Material consumption"

    def __str__(self) -> str:
        return f"{self.batch.number}: {self.lot.lot_code} — {self.quantity}"

    @property
    def total_cost(self) -> Decimal:
        return (self.quantity * self.unit_cost).quantize(Decimal("0.01"))


class ProductionOverhead(models.Model):
    """Additional batch costs (labour, energy, depreciation)."""

    batch = models.ForeignKey(ProductionBatch, on_delete=models.CASCADE, related_name="overheads")
    name = models.CharField(max_length=128)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Overhead"
        verbose_name_plural = "Overheads"

    def __str__(self) -> str:
        return f"{self.name}: {self.amount}"
