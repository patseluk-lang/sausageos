from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from apps.inventory.models import MoveType, StockLot

pytestmark = pytest.mark.django_db


@pytest.fixture
def storekeeper_client(users):
    client = Client()
    client.force_login(users["storekeeper"])
    return client


def test_page_is_closed_for_production_manager(users):
    client = Client()
    client.force_login(users["technologist"])
    assert client.get(reverse("warehouse")).status_code == 302


def test_page_lists_lots_with_stock(storekeeper_client, stocked):
    response = storekeeper_client.get(reverse("warehouse"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "SL-PORK-2026-0801" in content
    assert "Goods receipt" in content


def test_search_filters_lots(storekeeper_client, stocked):
    response = storekeeper_client.get(reverse("warehouse-lots"), {"q": "PORK-2026-0815"})
    content = response.content.decode()
    assert "SL-PORK-2026-0815" in content
    assert "SL-PORK-2026-0801" not in content


def test_receive_creates_lot_and_triggers_refresh(
    storekeeper_client, raw_warehouse, materials, supplier
):
    response = storekeeper_client.post(
        reverse("warehouse-receive"),
        {
            "warehouse": raw_warehouse.id,
            "material": materials["PORK"].id,
            "supplier": supplier.id,
            "lot_code": "SL-PORK-2026-0902",
            "supplier_batch_code": "PORK-2026-0902",
            "document": "GRN-118",
            "quantity": "120",
            "unit_cost": "178",
            "received_at": "2026-09-02",
            "expiry_date": "2026-09-08",
        },
    )
    assert response.status_code == 200
    assert response["HX-Trigger"] == "lotsChanged"
    lot = StockLot.objects.get(lot_code="SL-PORK-2026-0902")
    assert lot.on_hand == Decimal("120")
    assert lot.moves.first().move_type == MoveType.IN


def test_receive_rejects_duplicate_lot_code(storekeeper_client, raw_warehouse, materials, stocked):
    response = storekeeper_client.post(
        reverse("warehouse-receive"),
        {
            "warehouse": raw_warehouse.id,
            "material": materials["PORK"].id,
            "lot_code": "SL-PORK-2026-0801",
            "quantity": "50",
            "unit_cost": "170",
            "received_at": "2026-09-02",
        },
    )
    assert response.status_code == 400
    assert "already exists" in response.content.decode()


def test_stock_take_creates_adjustment(storekeeper_client, stocked):
    lot = stocked["PORK-2026-0801"]
    response = storekeeper_client.post(
        reverse("warehouse-stock-take", args=[lot.pk]), {"counted_quantity": "97.5"}
    )
    assert response.status_code == 200
    assert lot.on_hand == Decimal("97.5")
    assert lot.moves.filter(move_type=MoveType.ADJUST).exists()


def test_write_off_reduces_stock(storekeeper_client, stocked):
    lot = stocked["PORK-2026-0815"]
    response = storekeeper_client.post(
        reverse("warehouse-write-off", args=[lot.pk]),
        {"quantity": "8", "reason": "Spoilage in storage"},
    )
    assert response.status_code == 200
    assert lot.on_hand == Decimal("92")


def test_write_off_more_than_available_shows_error(storekeeper_client, stocked):
    lot = stocked["PORK-2026-0801"]
    response = storekeeper_client.post(
        reverse("warehouse-write-off", args=[lot.pk]), {"quantity": "500", "reason": "Mistake"}
    )
    assert response.status_code == 400
    assert "Cannot write off" in response.content.decode()
    assert lot.on_hand == Decimal("100")


def test_reserved_quantity_is_visible(storekeeper_client, stocked, materials):
    from apps.inventory import services as inventory
    from apps.inventory.models import Reservation

    inventory.reserve(
        quantity=Decimal("60"), purpose=Reservation.Purpose.PRODUCTION, material=materials["PORK"]
    )
    lot = stocked["PORK-2026-0801"]
    assert lot.reserved == Decimal("60")
    assert lot.available == Decimal("40")

    response = storekeeper_client.get(reverse("warehouse-lots"), {"q": "PORK-2026-0801"})
    row = next(r for r in response.context["rows"] if r["lot"].pk == lot.pk)
    assert row["reserved"] == Decimal("60")
    assert row["available"] == Decimal("40")
    assert row["lot"].lot_code in response.content.decode()


def test_expiry_warning_marks_expired_lot(storekeeper_client, raw_warehouse, materials):
    from apps.inventory import services as inventory

    inventory.receive(
        warehouse=raw_warehouse,
        lot_code="SL-OLD",
        material=materials["PORK"],
        quantity=10,
        unit_cost="160",
        received_at=date(2026, 1, 1),
        expiry_date=date(2026, 1, 5),
    )
    response = storekeeper_client.get(reverse("warehouse-lots"), {"q": "SL-OLD"})
    assert "⚠" in response.content.decode()
