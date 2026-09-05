from decimal import Decimal

import pytest

from apps.core.models import AuditLog
from apps.production import services as production
from apps.sales import services as sales
from apps.sales.models import Customer
from apps.traceability import services as traceability

pytestmark = pytest.mark.django_db


@pytest.fixture
def shipped_order(recipe_version, product, raw_warehouse, fg_warehouse, stocked):
    batch = production.create_batch(
        product=product,
        recipe_version=recipe_version,
        planned_quantity=Decimal("250"),
        source_warehouse=raw_warehouse,
        output_warehouse=fg_warehouse,
    )
    production.reserve_materials(batch)
    production.start(batch)
    production.finish(batch, actual_quantity=Decimal("244.2"))

    customer = Customer.objects.create(name="Smak Grocery")
    order = sales.create_order(
        customer=customer,
        warehouse=fg_warehouse,
        lines=[{"product": product, "quantity": Decimal("12"), "price": Decimal("222")}],
    )
    sales.confirm(order)
    sales.reserve(order)
    sales.mark_paid(order)
    sales.start_processing(order)
    sales.ship(order)
    return batch, order


def test_recall_finds_full_chain(shipped_order):
    batch, order = shipped_order
    result = traceability.recall("PORK-2026-0815")

    assert [b["number"] for b in result["production_batches"]] == [batch.number]
    assert result["affected_quantity"] == Decimal("244.200")
    assert result["orders"][0]["order"] == order.number
    assert result["orders"][0]["customer"] == "Smak Grocery"
    assert result["source_lots"][0]["material"] == "Pork"


def test_recall_for_unused_batch_is_empty(shipped_order):
    result = traceability.recall("PORK-2026-0828")
    assert result["production_batches"] == []
    assert result["affected_quantity"] == Decimal("0.000")


def test_recall_is_logged(shipped_order):
    traceability.recall("PORK-2026-0815")
    assert AuditLog.objects.filter(action="traceability.recall").exists()


def test_trace_back_from_finished_lot(shipped_order):
    batch, _ = shipped_order
    result = traceability.trace_back(f"FG-{batch.number}")

    assert result["production_batch"] == batch.number
    assert result["recipe_version"].endswith("v2.0")
    codes = {m["supplier_batch_code"] for m in result["materials"]}
    assert {"PORK-2026-0801", "PORK-2026-0815"} <= codes
