from decimal import Decimal

import pytest

from apps.core.exceptions import InsufficientStock
from apps.inventory import services as inventory
from apps.inventory.models import Reservation

pytestmark = pytest.mark.django_db


def test_on_hand_is_sum_of_moves(stocked, materials):
    assert inventory.on_hand(material=materials["PORK"]) == Decimal("300")
    inventory.issue(quantity=Decimal("50"), material=materials["PORK"], document="TEST")
    assert inventory.on_hand(material=materials["PORK"]) == Decimal("250")


def test_allocation_follows_fefo(stocked, materials):
    plan = inventory.allocate_fefo(quantity=Decimal("150"), material=materials["PORK"])
    assert [lot.supplier_batch_code for lot, _ in plan] == ["PORK-2026-0801", "PORK-2026-0815"]
    assert [qty for _, qty in plan] == [Decimal("100.000"), Decimal("50.000")]


def test_reservation_reduces_availability_but_not_stock(stocked, materials):
    inventory.reserve(
        quantity=Decimal("120"), purpose=Reservation.Purpose.PRODUCTION, material=materials["PORK"]
    )
    assert inventory.on_hand(material=materials["PORK"]) == Decimal("300")
    assert inventory.available(material=materials["PORK"]) == Decimal("180")


def test_insufficient_stock_reports_deficit(stocked, materials):
    with pytest.raises(InsufficientStock) as err:
        inventory.allocate_fefo(quantity=Decimal("350"), material=materials["PORK"])
    assert err.value.details["deficit"] == "50.000"


def test_release_returns_availability(stocked, materials):
    reservations = inventory.reserve(
        quantity=Decimal("100"), purpose=Reservation.Purpose.PRODUCTION, material=materials["PORK"]
    )
    inventory.release(reservations)
    assert inventory.available(material=materials["PORK"]) == Decimal("300")


def test_write_off_reduces_stock(stocked):
    lot = stocked["PORK-2026-0801"]
    inventory.write_off(lot=lot, quantity=Decimal("10"), reason="Spoilage")
    assert lot.on_hand == Decimal("90")


def test_transfer_creates_lot_on_target_warehouse(stocked, fg_warehouse):
    lot = stocked["PORK-2026-0801"]
    new_lot = inventory.transfer(lot=lot, quantity=Decimal("40"), target=fg_warehouse)
    assert lot.on_hand == Decimal("60")
    assert new_lot.on_hand == Decimal("40")
    assert new_lot.supplier_batch_code == lot.supplier_batch_code


def test_stock_take_creates_adjustment(stocked):
    lot = stocked["PORK-2026-0801"]
    inventory.stock_take(lot=lot, counted_quantity=Decimal("98.5"))
    assert lot.on_hand == Decimal("98.5")


def test_low_stock_report(stocked, materials):
    inventory.issue(quantity=Decimal("250"), material=materials["PORK"])
    rows = inventory.low_stock_report()
    names = {row["material"].sku: row for row in rows}
    assert names["PORK"]["deficit"] == Decimal("50")


def test_lots_with_stock_uses_single_query(stocked, django_assert_num_queries):
    """N+1 regression: the balance and reservations are computed by the database."""
    with django_assert_num_queries(1):
        lots = inventory.lots_with_stock()
        assert [(lot.on_hand, lot.available) for lot in lots]


def test_low_stock_report_uses_single_query(stocked, materials, django_assert_num_queries):
    inventory.issue(quantity=Decimal("250"), material=materials["PORK"])
    with django_assert_num_queries(1):
        assert inventory.low_stock_report()


def test_annotated_and_plain_lot_agree(stocked, materials):
    """The annotation and the model property must agree."""
    inventory.reserve(
        quantity=Decimal("60"), purpose=Reservation.Purpose.PRODUCTION, material=materials["PORK"]
    )
    plain = stocked["PORK-2026-0801"]
    annotated = inventory.lots_with_stock(material=materials["PORK"])[0]
    assert annotated.pk == plain.pk
    assert annotated.on_hand == plain.on_hand
    assert annotated.reserved == plain.reserved
    assert annotated.available == plain.available


def test_aggregates_return_clean_decimals(stocked, materials):
    """SQLite emulates Decimal with floats — totals must come back with three decimals."""
    assert str(inventory.on_hand(material=materials["PORK"])) == "300.000"
    assert str(inventory.total_on_hand(kind="material")) == str(
        inventory.total_on_hand(kind="material")
    )
    assert inventory.total_on_hand(kind="material").as_tuple().exponent == -3
