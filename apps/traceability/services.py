"""Traceability: from a supplier batch down to the customer, and back."""

from __future__ import annotations

from decimal import Decimal

from apps.core.services import log_action
from apps.inventory.models import Reservation, StockLot
from apps.production.models import BatchConsumption


def trace_forward(supplier_batch_code: str) -> dict:
    """What was produced from a supplier material batch."""
    source_lots = StockLot.objects.filter(
        supplier_batch_code=supplier_batch_code, material__isnull=False
    ).select_related("material", "supplier")

    consumptions = BatchConsumption.objects.filter(lot__in=source_lots).select_related(
        "batch__product", "lot"
    )
    batches = {c.batch for c in consumptions}
    output_lots = StockLot.objects.filter(production_batch__in=batches).select_related("product")

    reservations = (
        Reservation.objects.filter(lot__in=output_lots, order__isnull=False)
        .exclude(status=Reservation.Status.RELEASED)
        .select_related("order__customer", "lot__product")
    )

    affected_quantity = sum(
        (b.actual_quantity or Decimal("0") for b in batches), Decimal("0")
    ).quantize(Decimal("0.001"))

    return {
        "supplier_batch_code": supplier_batch_code,
        "source_lots": [
            {
                "lot_code": lot.lot_code,
                "material": lot.material.name,
                "supplier": lot.supplier.name if lot.supplier else "",
                "document": lot.document,
                "received_at": lot.received_at,
                "expiry_date": lot.expiry_date,
            }
            for lot in source_lots
        ],
        "production_batches": [
            {
                "number": b.number,
                "product": b.product.name,
                "recipe_version": str(b.recipe_version),
                "produced_quantity": b.actual_quantity,
                "status": b.status,
            }
            for b in sorted(batches, key=lambda x: x.number)
        ],
        "finished_lots": [
            {
                "lot_code": lot.lot_code,
                "product": lot.product.name if lot.product else "",
                "on_hand": lot.on_hand,
                "expiry_date": lot.expiry_date,
            }
            for lot in output_lots
        ],
        "orders": [
            {
                "order": res.order.number,
                "customer": res.order.customer.name,
                "product": res.lot.product.name if res.lot.product else "",
                "quantity": res.quantity,
                "status": res.order.status,
            }
            for res in reservations
        ],
        "affected_quantity": affected_quantity,
    }


def trace_back(lot_code: str) -> dict:
    """The origin history of one finished-goods lot."""
    lot = StockLot.objects.select_related("product", "production_batch__recipe_version").get(
        lot_code=lot_code, product__isnull=False
    )
    batch = lot.production_batch
    if batch is None:
        return {"finished_lot": lot.lot_code, "production_batch": None, "materials": []}
    materials = [
        {
            "material": c.lot.material.name if c.lot.material else "",
            "lot_code": c.lot.lot_code,
            "supplier": c.lot.supplier.name if c.lot.supplier else "",
            "supplier_batch_code": c.lot.supplier_batch_code,
            "document": c.lot.document,
            "quantity": c.quantity,
            "unit_cost": c.lot.unit_cost,
        }
        for c in batch.consumptions.select_related("lot__material", "lot__supplier")
    ]
    return {
        "finished_lot": lot.lot_code,
        "product": lot.product.name,
        "production_batch": batch.number,
        "recipe_version": str(batch.recipe_version),
        "produced_quantity": batch.actual_quantity,
        "materials": materials,
    }


def recall(supplier_batch_code: str, *, user=None) -> dict:
    """RECALL: the full impact chain of a material batch, recorded in the audit log."""
    result = trace_forward(supplier_batch_code)
    log_action(
        "traceability.recall",
        None,
        user,
        supplier_batch_code=supplier_batch_code,
        affected_quantity=str(result["affected_quantity"]),
        batches=[b["number"] for b in result["production_batches"]],
        customers=sorted({o["customer"] for o in result["orders"]}),
    )
    return result
