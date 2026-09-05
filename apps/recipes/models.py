from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.catalog.models import Material, Product
from apps.core.models import TimeStampedModel


class RecipeVersionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    ARCHIVED = "ARCHIVED", "Archived"


class Recipe(TimeStampedModel):
    product = models.OneToOneField(Product, on_delete=models.PROTECT, related_name="recipe")
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Recipe"
        verbose_name_plural = "Recipes"

    def __str__(self) -> str:
        return f"Recipe: {self.product.name}"

    @property
    def active_version(self):
        return (
            self.versions.filter(status=RecipeVersionStatus.ACTIVE).order_by("-valid_from").first()
        )


class RecipeVersion(TimeStampedModel):
    """A recipe version. Active and archived versions must never be edited."""

    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="versions")
    version = models.CharField(max_length=16)
    valid_from = models.DateField()
    status = models.CharField(
        max_length=16, choices=RecipeVersionStatus.choices, default=RecipeVersionStatus.DRAFT
    )
    yield_min = models.DecimalField("Yield norm, min %", max_digits=5, decimal_places=2, default=98)
    yield_max = models.DecimalField("Yield norm, max %", max_digits=5, decimal_places=2, default=99)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-valid_from", "-version")
        unique_together = ("recipe", "version")
        verbose_name = "Recipe version"
        verbose_name_plural = "Recipe versions"

    def __str__(self) -> str:
        return f"{self.recipe.product.name} {self.version}"

    @property
    def is_locked(self) -> bool:
        return self.status != RecipeVersionStatus.DRAFT

    def activate(self) -> None:
        if not self.lines.exists():
            raise ValidationError("A version cannot be activated without recipe lines.")
        self.recipe.versions.filter(status=RecipeVersionStatus.ACTIVE).exclude(pk=self.pk).update(
            status=RecipeVersionStatus.ARCHIVED
        )
        self.status = RecipeVersionStatus.ACTIVE
        self.save(update_fields=["status", "updated_at"])

    def requirements(self, planned_qty: Decimal) -> dict:
        """Material requirements for a given output quantity (kg)."""
        planned_qty = Decimal(planned_qty)
        return {
            line.material: line.required_quantity(planned_qty)
            for line in self.lines.select_related("material")
        }


class LineBasis(models.TextChoices):
    PERCENT = "PERCENT", "% of batch weight"
    PER_100KG = "PER_100KG", "per 100 kg"


class RecipeLine(models.Model):
    version = models.ForeignKey(RecipeVersion, on_delete=models.CASCADE, related_name="lines")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="recipe_lines")
    basis = models.CharField(max_length=16, choices=LineBasis.choices, default=LineBasis.PERCENT)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)

    class Meta:
        unique_together = ("version", "material")
        verbose_name = "Recipe line"
        verbose_name_plural = "Recipe lines"

    def __str__(self) -> str:
        return f"{self.material.name}: {self.quantity} ({self.get_basis_display()})"

    def clean(self):
        if self.version_id and self.version.is_locked:
            raise ValidationError("This recipe version is locked — create a new version instead.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def required_quantity(self, planned_qty: Decimal) -> Decimal:
        planned_qty = Decimal(planned_qty)
        if self.basis == LineBasis.PERCENT:
            return (planned_qty * self.quantity / Decimal("100")).quantize(Decimal("0.001"))
        return (planned_qty / Decimal("100") * self.quantity).quantize(Decimal("0.001"))
