"""Stock operations: receipts, FEFO allocation, reservations, write-offs."""

from __future__ import annotations

from decimal import Decimal

from django.db import connection, transaction
from django.db.models import DecimalField, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from apps.core.exceptions import InsufficientStock
from apps.core.services import log_action

from .models import MoveType, Reservation, StockLot, StockMove, Warehouse

ZERO = Decimal("0")
QTY = Decimal("0.001")


def _q(value) -> Decimal:
    return Decimal(value).quantize(QTY)


@transaction.atomic
def receive(
    *,
    warehouse: Warehouse,
    lot_code: str,
    quantity,
    unit_cost,
    received_at,
    material=None,
    product=None,
    supplier=None,
    supplier_batch_code: str = "",
    document: str = "",
    expiry_date=None,
    production_batch=None,
    user=None,
) -> StockLot:
    """Receive a new lot into a warehouse."""
    quantity = _q(quantity)
    if quantity <= ZERO:
        raise InsufficientStock("Received quantity must be positive.")
    lot = StockLot.objects.create(
        warehouse=warehouse,
        material=material,
        product=product,
        lot_code=lot_code,
        supplier=supplier,
        supplier_batch_code=supplier_batch_code,
        document=document,
        received_at=received_at,
        expiry_date=expiry_date,
        unit_cost=Decimal(unit_cost),
        production_batch=production_batch,
    )
    StockMove.objects.create(
        lot=lot, move_type=MoveType.IN, quantity=quantity, document=document, created_by=user
    )
    log_action("inventory.receive", lot, user, quantity=quantity, unit_cost=unit_cost)
    return lot


def _candidate_lots(*, material=None, product=None, warehouse=None):
    qs = StockLot.objects.all()
    if material is not None:
        qs = qs.filter(material=material)
    if product is not None:
        qs = qs.filter(product=product)
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    return qs


def lock_lots(*, material=None, product=None, warehouse=None) -> list[int]:
    """Lock the lots of one item until the end of the transaction (SELECT ... FOR UPDATE).

    Locks are taken in a single query ordered by pk — the same order for every
    transaction, which rules out deadlocks. Must be called inside transaction.atomic.

    SQLite has no row-level locking (it serializes writes at file level), so there
    this call does nothing; on PostgreSQL the lock is real.
    """
    pks = list(
        _candidate_lots(material=material, product=product, warehouse=warehouse)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    if pks and connection.features.has_select_for_update:
        list(StockLot.objects.filter(pk__in=pks).order_by("pk").select_for_update())
    return pks


def lock_lot(lot: StockLot) -> None:
    """Lock a single lot until the end of the transaction."""
    if connection.features.has_select_for_update:
        StockLot.objects.filter(pk=lot.pk).select_for_update().exists()


def lots_with_stock(*, material=None, product=None, warehouse=None, lock=False):
    """Lots with available stock, ordered by FEFO (nearest expiry first).

    The balance and reservations are computed by the database in a single query —
    no N+1 per lot. With lock=True the lots are locked first and the balance is
    read only after the lock is held.
    """
    if lock:
        lock_lots(material=material, product=product, warehouse=warehouse)
    qs = _candidate_lots(material=material, product=product, warehouse=warehouse)
    return list(qs.in_stock().fefo())


def on_hand(*, material=None, product=None, warehouse=None) -> Decimal:
    qs = StockMove.objects.all()
    if material is not None:
        qs = qs.filter(lot__material=material)
    if product is not None:
        qs = qs.filter(lot__product=product)
    if warehouse is not None:
        qs = qs.filter(lot__warehouse=warehouse)
    return _q(qs.aggregate(q=Sum("quantity"))["q"] or ZERO)


def available(*, material=None, product=None, warehouse=None) -> Decimal:
    reserved = Reservation.objects.filter(status=Reservation.Status.ACTIVE)
    if material is not None:
        reserved = reserved.filter(lot__material=material)
    if product is not None:
        reserved = reserved.filter(lot__product=product)
    if warehouse is not None:
        reserved = reserved.filter(lot__warehouse=warehouse)
    reserved_qty = reserved.aggregate(q=Sum("quantity"))["q"] or ZERO
    return _q(on_hand(material=material, product=product, warehouse=warehouse) - reserved_qty)


def allocate_fefo(*, quantity, material=None, product=None, warehouse=None, lock=False):
    """Allocate the requested quantity across lots using FEFO.

    Returns a list of (lot, quantity) tuples or raises InsufficientStock.
    With lock=True the lots stay locked until the end of the transaction, so a
    concurrent request cannot reserve the same material between check and write.
    """
    need = _q(quantity)
    item = material or product
    plan: list[tuple[StockLot, Decimal]] = []
    for lot in lots_with_stock(material=material, product=product, warehouse=warehouse, lock=lock):
        if need <= ZERO:
            break
        take = min(need, lot.available)
        if take > ZERO:
            plan.append((lot, _q(take)))
            need -= take
    if need > ZERO:
        raise InsufficientStock(
            f"Not enough {getattr(item, 'name', item)}: "
            f"short by {need} {getattr(item, 'unit', '')}",
            details={"item": str(item), "deficit": str(need)},
        )
    return plan


@transaction.atomic
def reserve(
    *,
    quantity,
    purpose,
    material=None,
    product=None,
    warehouse=None,
    production_batch=None,
    order=None,
    user=None,
) -> list[Reservation]:
    """Reserve a quantity using FEFO. A reservation lowers availability, not the balance."""
    reservations = []
    for lot, qty in allocate_fefo(
        quantity=quantity, material=material, product=product, warehouse=warehouse, lock=True
    ):
        reservations.append(
            Reservation.objects.create(
                lot=lot,
                quantity=qty,
                purpose=purpose,
                production_batch=production_batch,
                order=order,
            )
        )
    log_action(
        "inventory.reserve",
        production_batch or order,
        user,
        item=str(material or product),
        quantity=str(_q(quantity)),
    )
    return reservations


@transaction.atomic
def release(reservations, *, user=None) -> None:
    for res in reservations:
        if res.status == Reservation.Status.ACTIVE:
            res.status = Reservation.Status.RELEASED
            res.save(update_fields=["status", "updated_at"])
    log_action("inventory.release", None, user, count=len(list(reservations)))


@transaction.atomic
def issue_reservation(reservation: Reservation, *, document: str = "", user=None) -> StockMove:
    """Issue a reserved quantity from stock."""
    lock_lot(reservation.lot)
    reservation.refresh_from_db()
    if reservation.status != Reservation.Status.ACTIVE:
        raise InsufficientStock("This reservation is already consumed or released.")
    move = StockMove.objects.create(
        lot=reservation.lot,
        move_type=MoveType.OUT,
        quantity=-reservation.quantity,
        document=document,
        created_by=user,
    )
    reservation.status = Reservation.Status.CONSUMED
    reservation.save(update_fields=["status", "updated_at"])
    return move


@transaction.atomic
def issue(*, quantity, material=None, product=None, warehouse=None, document="", user=None):
    """Direct FEFO issue without a prior reservation."""
    moves = []
    for lot, qty in allocate_fefo(
        quantity=quantity, material=material, product=product, warehouse=warehouse, lock=True
    ):
        moves.append(
            StockMove.objects.create(
                lot=lot, move_type=MoveType.OUT, quantity=-qty, document=document, created_by=user
            )
        )
    return moves


@transaction.atomic
def write_off(*, lot: StockLot, quantity, reason: str, user=None) -> StockMove:
    lock_lot(lot)
    quantity = _q(quantity)
    if quantity > lot.available:
        raise InsufficientStock(
            f"Cannot write off {quantity}: only {lot.available} available in lot {lot.lot_code}."
        )
    move = StockMove.objects.create(
        lot=lot, move_type=MoveType.WRITE_OFF, quantity=-quantity, note=reason, created_by=user
    )
    log_action("inventory.write_off", lot, user, quantity=str(quantity), reason=reason)
    return move


@transaction.atomic
def transfer(*, lot: StockLot, quantity, target: Warehouse, user=None) -> StockLot:
    """Transfer between warehouses: an issue from the source lot, a receipt into a new one."""
    lock_lot(lot)
    quantity = _q(quantity)
    if quantity > lot.available:
        raise InsufficientStock(
            f"Cannot transfer {quantity}: only {lot.available} available in lot {lot.lot_code}."
        )
    StockMove.objects.create(
        lot=lot,
        move_type=MoveType.TRANSFER,
        quantity=-quantity,
        note=f"→ {target.code}",
        created_by=user,
    )
    new_lot = StockLot.objects.create(
        warehouse=target,
        material=lot.material,
        product=lot.product,
        lot_code=f"{lot.lot_code}/{target.code}",
        supplier=lot.supplier,
        supplier_batch_code=lot.supplier_batch_code,
        document=lot.document,
        received_at=lot.received_at,
        expiry_date=lot.expiry_date,
        unit_cost=lot.unit_cost,
        production_batch=lot.production_batch,
    )
    StockMove.objects.create(
        lot=new_lot,
        move_type=MoveType.TRANSFER,
        quantity=quantity,
        note=f"← {lot.warehouse.code}",
        created_by=user,
    )
    log_action("inventory.transfer", lot, user, quantity=str(quantity), target=target.code)
    return new_lot


@transaction.atomic
def stock_take(*, lot: StockLot, counted_quantity, user=None) -> StockMove | None:
    """Stock take: a correcting move for the difference between counted and recorded."""
    lock_lot(lot)
    diff = _q(counted_quantity) - lot.on_hand
    if diff == ZERO:
        return None
    move = StockMove.objects.create(
        lot=lot, move_type=MoveType.ADJUST, quantity=diff, note="Stock take", created_by=user
    )
    log_action("inventory.stock_take", lot, user, diff=str(diff))
    return move


def low_stock_report():
    """Materials below their minimum stock level. One query for the whole catalog."""
    from apps.catalog.models import Material

    qty_field = DecimalField(max_digits=14, decimal_places=3)
    moves = (
        StockMove.objects.filter(lot__material=OuterRef("pk"))
        .values("lot__material")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    materials = (
        Material.objects.filter(is_active=True)
        .annotate(
            stock=Coalesce(
                Subquery(moves, output_field=qty_field), Value(0, output_field=qty_field)
            )
        )
        .filter(stock__lt=F("min_stock"))
    )
    return [
        {
            "material": material,
            "on_hand": _q(material.stock),
            "min_stock": material.min_stock,
            "deficit": _q(material.min_stock - material.stock),
        }
        for material in materials
    ]


def total_on_hand(*, kind: str) -> Decimal:
    """Total balance across all materials ("material") or all products ("product")."""
    condition = (
        Q(lot__material__isnull=False) if kind == "material" else Q(lot__product__isnull=False)
    )
    return _q(StockMove.objects.filter(condition).aggregate(q=Sum("quantity"))["q"] or ZERO)
