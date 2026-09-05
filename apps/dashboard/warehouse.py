"""Warehouse workspace: receipts, stock takes and write-offs (HTMX)."""

from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.exceptions import BusinessError
from apps.core.models import Role
from apps.inventory import services as inventory
from apps.inventory.models import StockLot, Warehouse

from .forms import ReceiveForm, StockTakeForm, WriteOffForm


def is_warehouse_staff(user) -> bool:
    return user.is_authenticated and user.has_role(Role.WAREHOUSE_MANAGER)


warehouse_required = user_passes_test(is_warehouse_staff, login_url="login")


def _lots(request):
    query = request.GET.get("q", "").strip()
    warehouse_id = request.GET.get("warehouse", "")
    kind = request.GET.get("kind", "")

    lots = StockLot.objects.with_stock().select_related(
        "material", "product", "warehouse", "supplier"
    )
    if query:
        lots = lots.filter(lot_code__icontains=query) | lots.filter(
            supplier_batch_code__icontains=query
        )
    if warehouse_id:
        lots = lots.filter(warehouse_id=warehouse_id)
    if kind == "material":
        lots = lots.filter(material__isnull=False)
    elif kind == "product":
        lots = lots.filter(product__isnull=False)

    today = timezone.localdate()
    rows = []
    for lot in lots.distinct():
        on_hand = lot.on_hand
        if on_hand <= 0 and request.GET.get("all") != "1":
            continue
        rows.append(
            {
                "lot": lot,
                "on_hand": on_hand,
                "reserved": lot.reserved,
                "available": lot.available,
                "expires_soon": bool(lot.expiry_date and (lot.expiry_date - today).days <= 7),
                "expired": bool(lot.expiry_date and lot.expiry_date < today),
            }
        )
    return rows


@login_required
@warehouse_required
@require_GET
def index(request):
    context = {
        "rows": _lots(request),
        "warehouses": Warehouse.objects.all(),
        "receive_form": ReceiveForm(initial={"received_at": timezone.localdate()}),
        "low_stock": inventory.low_stock_report(),
        "selected_warehouse": request.GET.get("warehouse", ""),
        "query": request.GET.get("q", ""),
    }
    return render(request, "warehouse/index.html", context)


@login_required
@warehouse_required
@require_GET
def lot_table(request):
    """Partial refresh of the stock table (HTMX)."""
    return render(request, "warehouse/partials/lot_table.html", {"rows": _lots(request)})


@login_required
@warehouse_required
@require_POST
def receive(request):
    form = ReceiveForm(request.POST)
    if not form.is_valid():
        return render(
            request, "warehouse/partials/receive_form.html", {"receive_form": form}, status=400
        )
    lot = inventory.receive(**form.cleaned_data, user=request.user)
    response = render(
        request,
        "warehouse/partials/receive_form.html",
        {
            "receive_form": ReceiveForm(initial={"received_at": timezone.localdate()}),
            "message": f"Lot {lot.lot_code} received.",
        },
    )
    response["HX-Trigger"] = "lotsChanged"
    return response


@login_required
@warehouse_required
@require_POST
def stock_take(request, pk: int):
    lot = get_object_or_404(StockLot, pk=pk)
    form = StockTakeForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "warehouse/partials/lot_row.html",
            {"row": _row(lot), "error": "Invalid quantity."},
            status=400,
        )
    inventory.stock_take(
        lot=lot, counted_quantity=form.cleaned_data["counted_quantity"], user=request.user
    )
    return render(request, "warehouse/partials/lot_row.html", {"row": _row(lot)})


@login_required
@warehouse_required
@require_POST
def write_off(request, pk: int):
    lot = get_object_or_404(StockLot, pk=pk)
    form = WriteOffForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "warehouse/partials/lot_row.html",
            {"row": _row(lot), "error": "Fill in both quantity and reason."},
            status=400,
        )
    try:
        inventory.write_off(
            lot=lot,
            quantity=form.cleaned_data["quantity"],
            reason=form.cleaned_data["reason"],
            user=request.user,
        )
    except BusinessError as error:
        return render(
            request,
            "warehouse/partials/lot_row.html",
            {"row": _row(lot), "error": error.message},
            status=400,
        )
    return render(request, "warehouse/partials/lot_row.html", {"row": _row(lot)})


def _row(lot: StockLot) -> dict:
    today = timezone.localdate()
    return {
        "lot": lot,
        "on_hand": lot.on_hand,
        "reserved": lot.reserved,
        "available": lot.available,
        "expires_soon": bool(lot.expiry_date and (lot.expiry_date - today).days <= 7),
        "expired": bool(lot.expiry_date and lot.expiry_date < today),
    }
