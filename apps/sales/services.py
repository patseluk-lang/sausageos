"""Order lifecycle: reserving finished goods and shipping them."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core.exceptions import BusinessError
from apps.core.services import log_action
from apps.inventory import services as inventory
from apps.inventory.models import Reservation

from .models import Order, OrderLine, OrderStatus

ALLOWED_TRANSITIONS = {
    OrderStatus.NEW: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.RESERVED, OrderStatus.CANCELLED},
    OrderStatus.RESERVED: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.PROCESSING, OrderStatus.CANCELLED},
    OrderStatus.PROCESSING: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.COMPLETED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}


def next_order_number() -> str:
    last = Order.objects.aggregate(m=Max("number"))["m"]
    return f"{int(last) + 1:04d}" if last and last.isdigit() else "5001"


@transaction.atomic
def create_order(*, customer, warehouse, lines: list[dict], user=None) -> Order:
    order = Order.objects.create(number=next_order_number(), customer=customer, warehouse=warehouse)
    for line in lines:
        OrderLine.objects.create(
            order=order,
            product=line["product"],
            quantity=Decimal(line["quantity"]),
            price=Decimal(line["price"]),
        )
    log_action("sales.create", order, user, customer=customer.name)
    return order


def _transition(order: Order, target: OrderStatus, user=None) -> Order:
    if target not in ALLOWED_TRANSITIONS[OrderStatus(order.status)]:
        raise BusinessError(
            f"Invalid status transition: {order.get_status_display()} → {OrderStatus(target).label}"
        )
    order.status = target
    order.save(update_fields=["status", "updated_at"])
    log_action("sales.status", order, user, status=target)
    return order


def confirm(order: Order, *, user=None) -> Order:
    if not order.lines.exists():
        raise BusinessError("An order without lines cannot be confirmed.")
    return _transition(order, OrderStatus.CONFIRMED, user)


@transaction.atomic
def reserve(order: Order, *, user=None) -> Order:
    """Reserve finished goods for the order using FEFO."""
    if order.status != OrderStatus.CONFIRMED:
        raise BusinessError("Only a confirmed order can be reserved.")
    for line in order.lines.select_related("product"):
        inventory.reserve(
            quantity=line.quantity,
            purpose=Reservation.Purpose.SALES,
            product=line.product,
            warehouse=order.warehouse,
            order=order,
            user=user,
        )
    return _transition(order, OrderStatus.RESERVED, user)


def mark_paid(order: Order, *, user=None) -> Order:
    return _transition(order, OrderStatus.PAID, user)


def start_processing(order: Order, *, user=None) -> Order:
    return _transition(order, OrderStatus.PROCESSING, user)


@transaction.atomic
def ship(order: Order, *, user=None) -> Order:
    """Shipment: issues the reserved finished-goods lots."""
    if order.status != OrderStatus.PROCESSING:
        raise BusinessError("Only an order in processing can be shipped.")
    for res in order.reservations.filter(status=Reservation.Status.ACTIVE).select_related("lot"):
        inventory.issue_reservation(res, document=order.number, user=user)
    order.shipped_at = timezone.now()
    order.save(update_fields=["shipped_at", "updated_at"])
    return _transition(order, OrderStatus.SHIPPED, user)


def complete(order: Order, *, user=None) -> Order:
    return _transition(order, OrderStatus.COMPLETED, user)


@transaction.atomic
def cancel(order: Order, *, user=None) -> Order:
    inventory.release(order.reservations.filter(status=Reservation.Status.ACTIVE), user=user)
    return _transition(order, OrderStatus.CANCELLED, user)
