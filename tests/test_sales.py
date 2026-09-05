from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessError
from apps.inventory import services as inventory
from apps.production import services as production
from apps.sales import services as sales
from apps.sales.models import Customer, OrderStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def finished_batch(recipe_version, product, raw_warehouse, fg_warehouse, stocked):
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
    return batch


@pytest.fixture
def customer(db):
    return Customer.objects.create(name="Smak Grocery", address="Kyiv")


@pytest.fixture
def order(customer, fg_warehouse, product, finished_batch):
    return sales.create_order(
        customer=customer,
        warehouse=fg_warehouse,
        lines=[{"product": product, "quantity": Decimal("12"), "price": Decimal("222")}],
    )


def test_order_total(order):
    assert order.total == Decimal("2664.00")


def test_full_order_cycle(order, product, fg_warehouse):
    sales.confirm(order)
    sales.reserve(order)
    assert order.status == OrderStatus.RESERVED
    assert inventory.available(product=product) == Decimal("232.2")
    assert inventory.on_hand(product=product) == Decimal("244.2")

    sales.mark_paid(order)
    sales.start_processing(order)
    sales.ship(order)
    assert order.status == OrderStatus.SHIPPED
    assert inventory.on_hand(product=product) == Decimal("232.2")

    sales.complete(order)
    assert order.status == OrderStatus.COMPLETED


def test_invalid_transition_is_rejected(order):
    with pytest.raises(BusinessError):
        sales.ship(order)


def test_cancel_releases_finished_goods(order, product):
    sales.confirm(order)
    sales.reserve(order)
    sales.cancel(order)
    assert order.status == OrderStatus.CANCELLED
    assert inventory.available(product=product) == Decimal("244.2")
