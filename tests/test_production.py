from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessError, InsufficientStock
from apps.inventory import services as inventory
from apps.production import services as production
from apps.production.models import BatchStatus, ProductionOverhead

pytestmark = pytest.mark.django_db


@pytest.fixture
def batch(recipe_version, product, raw_warehouse, fg_warehouse):
    return production.create_batch(
        product=product,
        recipe_version=recipe_version,
        planned_quantity=Decimal("250"),
        source_warehouse=raw_warehouse,
        output_warehouse=fg_warehouse,
    )


def test_batch_number_format(batch):
    assert batch.number.startswith("2026-")
    assert len(batch.number.split("-")[1]) == 6


def test_requirements_of_batch(batch, materials):
    req = production.requirements(batch)
    assert req[materials["PORK"]] == Decimal("175.000")


def test_availability_deficit_message(
    recipe_version, product, raw_warehouse, fg_warehouse, stocked
):
    big = production.create_batch(
        product=product,
        recipe_version=recipe_version,
        planned_quantity=Decimal("500"),
        source_warehouse=raw_warehouse,
        output_warehouse=fg_warehouse,
    )
    deficits = production.check_availability(big)
    pork = next(d for d in deficits if d["material"] == "Pork")
    assert pork["deficit"] == Decimal("50.000")
    with pytest.raises(InsufficientStock) as err:
        production.reserve_materials(big)
    assert "Cannot start production" in err.value.message


def test_reserve_then_start_consumes_materials(batch, stocked, materials):
    production.reserve_materials(batch)
    assert batch.status == BatchStatus.RESERVED
    assert inventory.available(material=materials["PORK"]) == Decimal("125")
    assert inventory.on_hand(material=materials["PORK"]) == Decimal("300")

    production.start(batch)
    assert batch.status == BatchStatus.IN_PROGRESS
    assert inventory.on_hand(material=materials["PORK"]) == Decimal("125")
    assert batch.consumptions.count() == 7  # pork from two lots + 5 other items


def test_finish_creates_finished_goods_and_yield(batch, stocked, product, fg_warehouse):
    production.reserve_materials(batch)
    production.start(batch)
    production.finish(batch, actual_quantity=Decimal("244.2"))

    assert batch.status == BatchStatus.DONE
    assert batch.loaded_quantity == Decimal("250.000")
    assert batch.loss_quantity == Decimal("5.800")
    assert batch.yield_percent == Decimal("97.68")
    assert batch.yield_is_below_norm is True
    assert inventory.on_hand(product=product, warehouse=fg_warehouse) == Decimal("244.2")


def test_cost_report_uses_actual_lot_prices(batch, stocked):
    production.reserve_materials(batch)
    production.start(batch)
    production.finish(batch, actual_quantity=Decimal("244.2"))
    ProductionOverhead.objects.create(batch=batch, name="Labour", amount=Decimal("1500"))

    report = production.cost_report(batch)
    # pork: 100 kg × 165 + 75 kg × 172 = 29,400 UAH (FEFO across two lots)
    assert report["by_category"]["Raw material"] == Decimal("44025.00")
    assert report["materials_total"] == Decimal("44620.00")
    assert report["overheads_total"] == Decimal("1500.00")
    assert report["total_cost"] == Decimal("46120.00")
    assert report["cost_per_kg"] == Decimal("188.86")
    assert report["recommended_price"] == Decimal("283.15")
    assert report["yield_below_norm"] is True


def test_cancel_releases_reservations(batch, stocked, materials):
    production.reserve_materials(batch)
    production.cancel(batch)
    assert batch.status == BatchStatus.CANCELLED
    assert inventory.available(material=materials["PORK"]) == Decimal("300")


def test_cannot_start_without_reservation(batch, stocked):
    with pytest.raises(BusinessError):
        production.start(batch)
