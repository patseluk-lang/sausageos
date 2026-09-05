from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import DecimalField, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from apps.catalog.models import Material, Product, Supplier
from apps.core.models import TimeStampedModel


class Warehouse(TimeStampedModel):
    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=128)

    class Meta:
        ordering = ("code",)
        verbose_name = "Warehouse"
        verbose_name_plural = "Warehouses"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


QTY_FIELD = DecimalField(max_digits=14, decimal_places=3)


class StockLotQuerySet(models.QuerySet):
    """Balances are computed in the database, not by looping in Python."""

    def with_stock(self):
        moves = (
            StockMove.objects.filter(lot=OuterRef("pk"))
            .values("lot")
            .annotate(total=Sum("quantity"))
            .values("total")
        )
        reserved = (
            Reservation.objects.filter(lot=OuterRef("pk"), status=Reservation.Status.ACTIVE)
            .values("lot")
            .annotate(total=Sum("quantity"))
            .values("total")
        )
        zero = Value(0, output_field=QTY_FIELD)
        return self.annotate(
            on_hand_qty=Coalesce(Subquery(moves, output_field=QTY_FIELD), zero),
            reserved_qty=Coalesce(Subquery(reserved, output_field=QTY_FIELD), zero),
        ).annotate(available_qty=F("on_hand_qty") - F("reserved_qty"))

    def in_stock(self):
        return self.with_stock().filter(available_qty__gt=0)

    def fefo(self):
        """Lots with the nearest expiry date come first."""
        return self.order_by(F("expiry_date").asc(nulls_last=True), "received_at", "pk")


class StockLot(TimeStampedModel):
    """A stock lot: either raw material or finished product."""

    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="lots")
    material = models.ForeignKey(
        Material, null=True, blank=True, on_delete=models.PROTECT, related_name="lots"
    )
    product = models.ForeignKey(
        Product, null=True, blank=True, on_delete=models.PROTECT, related_name="lots"
    )
    lot_code = models.CharField("Internal lot code", max_length=64, unique=True)
    supplier = models.ForeignKey(
        Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name="lots"
    )
    supplier_batch_code = models.CharField("Supplier batch code", max_length=64, blank=True)
    document = models.CharField("Goods receipt note", max_length=64, blank=True)
    received_at = models.DateField()
    expiry_date = models.DateField(null=True, blank=True)
    unit_cost = models.DecimalField("Unit cost, UAH", max_digits=12, decimal_places=4)
    production_batch = models.ForeignKey(
        "production.ProductionBatch",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="output_lots",
    )

    objects = StockLotQuerySet.as_manager()

    class Meta:
        ordering = ("expiry_date", "received_at", "id")
        verbose_name = "Stock lot"
        verbose_name_plural = "Stock lots"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(material__isnull=False, product__isnull=True)
                    | Q(material__isnull=True, product__isnull=False)
                ),
                name="stocklot_material_xor_product",
            )
        ]

    def __str__(self) -> str:
        return f"{self.lot_code} ({self.item_name})"

    def clean(self):
        if bool(self.material_id) == bool(self.product_id):
            raise ValidationError("A lot must reference either a material or a product.")

    @property
    def item_name(self) -> str:
        return self.material.name if self.material_id else self.product.name

    @property
    def on_hand(self) -> Decimal:
        """Lot balance; uses the with_stock() annotation when it is present."""
        if (annotated := getattr(self, "on_hand_qty", None)) is not None:
            return annotated
        return self.moves.aggregate(q=Sum("quantity"))["q"] or Decimal("0")

    @property
    def reserved(self) -> Decimal:
        if (annotated := getattr(self, "reserved_qty", None)) is not None:
            return annotated
        return self.reservations.filter(status=Reservation.Status.ACTIVE).aggregate(
            q=Sum("quantity")
        )["q"] or Decimal("0")

    @property
    def available(self) -> Decimal:
        if (annotated := getattr(self, "available_qty", None)) is not None:
            return annotated
        return self.on_hand - self.reserved


class MoveType(models.TextChoices):
    IN = "IN", "Receipt"
    OUT = "OUT", "Issue"
    WRITE_OFF = "WRITE_OFF", "Write-off"
    TRANSFER = "TRANSFER", "Transfer"
    ADJUST = "ADJUST", "Stock take"


class StockMove(models.Model):
    """A stock move. The table is append-only: the balance is the sum of its moves."""

    lot = models.ForeignKey(StockLot, on_delete=models.PROTECT, related_name="moves")
    move_type = models.CharField(max_length=16, choices=MoveType.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    occurred_at = models.DateTimeField(auto_now_add=True)
    document = models.CharField(max_length=64, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ("-occurred_at", "-id")
        verbose_name = "Stock move"
        verbose_name_plural = "Stock moves"

    def __str__(self) -> str:
        return f"{self.move_type} {self.quantity:+} {self.lot.lot_code}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Stock moves are immutable — post a correcting move instead.")
        super().save(*args, **kwargs)


class Reservation(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        CONSUMED = "CONSUMED", "Consumed"
        RELEASED = "RELEASED", "Released"

    class Purpose(models.TextChoices):
        PRODUCTION = "PRODUCTION", "Production"
        SALES = "SALES", "Sales"

    lot = models.ForeignKey(StockLot, on_delete=models.PROTECT, related_name="reservations")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    purpose = models.CharField(max_length=16, choices=Purpose.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    production_batch = models.ForeignKey(
        "production.ProductionBatch",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="reservations",
    )
    order = models.ForeignKey(
        "sales.Order", null=True, blank=True, on_delete=models.CASCADE, related_name="reservations"
    )

    class Meta:
        verbose_name = "Reservation"
        verbose_name_plural = "Reservations"

    def __str__(self) -> str:
        return f"{self.lot.lot_code}: {self.quantity} ({self.get_purpose_display()})"
