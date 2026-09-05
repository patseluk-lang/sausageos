"""Production cycle: plan → reserve → consume → actual output → cost."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core.exceptions import BusinessError, InsufficientStock
from apps.core.services import log_action
from apps.inventory import services as inventory
from apps.inventory.models import Reservation

from .models import BatchConsumption, BatchStatus, ProductionBatch

MONEY = Decimal("0.01")


def next_batch_number(today=None) -> str:
    today = today or timezone.localdate()
    prefix = f"{today.year}-"
    last = ProductionBatch.objects.filter(number__startswith=prefix).aggregate(m=Max("number"))["m"]
    seq = int(last.split("-")[1]) + 1 if last else 1
    return f"{prefix}{seq:06d}"


@transaction.atomic
def create_batch(
    *, product, recipe_version, planned_quantity, source_warehouse, output_warehouse, user=None
) -> ProductionBatch:
    if recipe_version.recipe.product_id != product.id:
        raise BusinessError("This recipe does not belong to the product.")
    batch = ProductionBatch.objects.create(
        number=next_batch_number(),
        product=product,
        recipe_version=recipe_version,
        planned_quantity=Decimal(planned_quantity),
        source_warehouse=source_warehouse,
        output_warehouse=output_warehouse,
    )
    log_action("production.create", batch, user, planned=str(planned_quantity))
    return batch


def requirements(batch: ProductionBatch) -> dict:
    """Material requirements from the recipe for the planned quantity."""
    return batch.recipe_version.requirements(batch.planned_quantity)


def check_availability(batch: ProductionBatch) -> list[dict]:
    """Shortages, if any. An empty list means production can start."""
    deficits = []
    for material, need in requirements(batch).items():
        have = inventory.available(material=material, warehouse=batch.source_warehouse)
        if have < need:
            deficits.append(
                {
                    "material": material.name,
                    "required": need,
                    "available": have,
                    "deficit": (need - have).quantize(Decimal("0.001")),
                    "unit": material.get_unit_display(),
                }
            )
    return deficits


@transaction.atomic
def reserve_materials(batch: ProductionBatch, *, user=None) -> ProductionBatch:
    if batch.status != BatchStatus.PLANNED:
        raise BusinessError("Materials can only be reserved for a planned batch.")
    deficits = check_availability(batch)
    if deficits:
        lines = "; ".join(f"{d['material']}: {d['deficit']} {d['unit']}" for d in deficits)
        raise InsufficientStock(
            f"Cannot start production. Not enough — {lines}",
            details={"deficits": [{k: str(v) for k, v in d.items()} for d in deficits]},
        )
    for material, need in requirements(batch).items():
        inventory.reserve(
            quantity=need,
            purpose=Reservation.Purpose.PRODUCTION,
            material=material,
            warehouse=batch.source_warehouse,
            production_batch=batch,
            user=user,
        )
    batch.status = BatchStatus.RESERVED
    batch.save(update_fields=["status", "updated_at"])
    log_action("production.reserve", batch, user)
    return batch


@transaction.atomic
def start(batch: ProductionBatch, *, user=None) -> ProductionBatch:
    """Issue the reserved materials into production."""
    if batch.status != BatchStatus.RESERVED:
        raise BusinessError("Reserve the materials first.")
    reservations = batch.reservations.filter(status=Reservation.Status.ACTIVE).select_related("lot")
    for res in reservations:
        inventory.issue_reservation(res, document=batch.number, user=user)
        BatchConsumption.objects.create(
            batch=batch, lot=res.lot, quantity=res.quantity, unit_cost=res.lot.unit_cost
        )
    batch.status = BatchStatus.IN_PROGRESS
    batch.started_at = timezone.now()
    batch.save(update_fields=["status", "started_at", "updated_at"])
    log_action(
        "production.start", batch, user, consumed_lots=[r.lot.lot_code for r in reservations]
    )
    return batch


@transaction.atomic
def finish(
    batch: ProductionBatch, *, actual_quantity, expiry_date=None, user=None
) -> ProductionBatch:
    """Record the actual output and receive the finished goods into stock."""
    if batch.status != BatchStatus.IN_PROGRESS:
        raise BusinessError("Only a batch in progress can be completed.")
    actual_quantity = Decimal(actual_quantity)
    if actual_quantity <= 0:
        raise BusinessError("Actual output must be positive.")
    batch.actual_quantity = actual_quantity
    batch.status = BatchStatus.DONE
    batch.finished_at = timezone.now()
    batch.save(update_fields=["actual_quantity", "status", "finished_at", "updated_at"])

    report = cost_report(batch)
    inventory.receive(
        warehouse=batch.output_warehouse,
        lot_code=f"FG-{batch.number}",
        quantity=actual_quantity,
        unit_cost=report["cost_per_kg"],
        received_at=timezone.localdate(),
        product=batch.product,
        expiry_date=expiry_date,
        document=batch.number,
        production_batch=batch,
        user=user,
    )
    log_action(
        "production.finish",
        batch,
        user,
        actual=str(actual_quantity),
        yield_percent=str(batch.yield_percent),
        cost_per_kg=str(report["cost_per_kg"]),
    )
    return batch


def cost_report(batch: ProductionBatch) -> dict:
    """Actual batch cost, broken down by category."""
    by_category: dict[str, Decimal] = {}
    materials_total = Decimal("0")
    for line in batch.consumptions.select_related("lot__material"):
        category = line.lot.material.get_category_display() if line.lot.material else "Other"
        by_category[category] = by_category.get(category, Decimal("0")) + line.total_cost
        materials_total += line.total_cost

    overheads_total = sum((o.amount for o in batch.overheads.all()), Decimal("0"))
    total = (materials_total + overheads_total).quantize(MONEY)
    quantity = batch.actual_quantity or Decimal("0")
    cost_per_kg = (total / quantity).quantize(MONEY) if quantity > 0 else None

    margin = batch.product.target_margin or Decimal(str(settings.DEFAULT_TARGET_MARGIN))
    recommended_price = (
        (cost_per_kg / (Decimal("1") - margin / Decimal("100"))).quantize(MONEY)
        if cost_per_kg
        else None
    )
    return {
        "batch": batch.number,
        "by_category": {k: v.quantize(MONEY) for k, v in by_category.items()},
        "materials_total": materials_total.quantize(MONEY),
        "overheads_total": Decimal(overheads_total).quantize(MONEY),
        "total_cost": total,
        "produced_quantity": quantity,
        "cost_per_kg": cost_per_kg,
        "target_margin": margin,
        "recommended_price": recommended_price,
        "yield_percent": batch.yield_percent,
        "loss_quantity": batch.loss_quantity,
        "yield_norm": f"{batch.recipe_version.yield_min}–{batch.recipe_version.yield_max}%",
        "yield_below_norm": batch.yield_is_below_norm,
    }


@transaction.atomic
def cancel(batch: ProductionBatch, *, user=None) -> ProductionBatch:
    if batch.status in (BatchStatus.DONE, BatchStatus.CANCELLED):
        raise BusinessError("This batch is already completed or cancelled.")
    inventory.release(batch.reservations.filter(status=Reservation.Status.ACTIVE), user=user)
    batch.status = BatchStatus.CANCELLED
    batch.save(update_fields=["status", "updated_at"])
    log_action("production.cancel", batch, user)
    return batch


def profitability_report():
    """Profitability across completed batches."""
    rows = []
    for batch in ProductionBatch.objects.filter(status=BatchStatus.DONE).select_related("product"):
        report = cost_report(batch)
        rows.append(
            {
                "batch": batch.number,
                "product": batch.product.name,
                "quantity": batch.actual_quantity,
                "total_cost": report["total_cost"],
                "cost_per_kg": report["cost_per_kg"],
                "recommended_price": report["recommended_price"],
                "target_margin": report["target_margin"],
                "yield_percent": report["yield_percent"],
            }
        )
    return rows
