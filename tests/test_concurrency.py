"""Concurrent access to stock.

A reservation reads the balance and immediately changes it. Without row locks two
parallel requests can reserve the same material: both see 100 kg free and both
write a reservation for 60 kg.

SQLite has no row-level locking — it serializes writes at file level — so the
genuinely parallel tests run only on PostgreSQL (docker compose and CI).
"""

import threading
from decimal import Decimal

import pytest
from django.db import connection, connections, transaction
from django.test.utils import CaptureQueriesContext

from apps.core.exceptions import InsufficientStock
from apps.inventory import services as inventory
from apps.inventory.models import Reservation

pytestmark = pytest.mark.django_db

postgres_only = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="Row-level locking exists only on PostgreSQL"
)


def test_reserve_locks_rows_before_reading_stock(stocked, materials):
    """Reserving must lock the lots of the item inside the transaction."""
    with CaptureQueriesContext(connection) as ctx:
        inventory.reserve(
            quantity=Decimal("50"),
            purpose=Reservation.Purpose.PRODUCTION,
            material=materials["PORK"],
        )
    if connection.features.has_select_for_update:
        assert any("FOR UPDATE" in query["sql"] for query in ctx.captured_queries)
    else:
        pytest.skip("Backend without row-level locking — verified on PostgreSQL")


@pytest.mark.django_db(transaction=True)
def test_lock_lots_requires_transaction(stocked, materials):
    """Locking outside transaction.atomic is impossible — services must be atomic."""
    if not connection.features.has_select_for_update:
        pytest.skip("Backend without row-level locking")
    with pytest.raises(transaction.TransactionManagementError):
        inventory.lock_lots(material=materials["PORK"])


def test_sequential_reservations_respect_stock(stocked, materials):
    """The second reservation sees that the material is already booked."""
    inventory.reserve(
        quantity=Decimal("250"), purpose=Reservation.Purpose.PRODUCTION, material=materials["PORK"]
    )
    with pytest.raises(InsufficientStock):
        inventory.reserve(
            quantity=Decimal("100"),
            purpose=Reservation.Purpose.PRODUCTION,
            material=materials["PORK"],
        )


@postgres_only
@pytest.mark.django_db(transaction=True)
def test_parallel_reservations_do_not_oversell(stocked, materials):
    """Two simultaneous 200 kg reservations against 300 kg in stock: one must be refused."""
    barrier = threading.Barrier(2)
    results: list[object] = []

    def worker():
        barrier.wait()
        try:
            with transaction.atomic():
                inventory.reserve(
                    quantity=Decimal("200"),
                    purpose=Reservation.Purpose.PRODUCTION,
                    material=materials["PORK"],
                )
            results.append("ok")
        except InsufficientStock:
            results.append("rejected")
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["ok", "rejected"]
    assert inventory.available(material=materials["PORK"]) == Decimal("100")
