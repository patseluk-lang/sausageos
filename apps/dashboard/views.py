from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import F, Sum
from django.shortcuts import render
from django.utils import timezone

from apps.inventory.services import low_stock_report, total_on_hand
from apps.production.models import BatchStatus, ProductionBatch
from apps.production.services import cost_report
from apps.sales.models import Order, OrderLine, OrderStatus


@login_required
def dashboard(request):
    today = timezone.localdate()
    done = ProductionBatch.objects.filter(status=BatchStatus.DONE)
    produced_today = Decimal(
        done.filter(finished_at__date=today).aggregate(q=Sum("actual_quantity"))["q"] or 0
    ).quantize(Decimal("0.001"))
    finished_goods = total_on_hand(kind="product")
    raw_materials = total_on_hand(kind="material")
    paid_statuses = [
        OrderStatus.PAID,
        OrderStatus.PROCESSING,
        OrderStatus.SHIPPED,
        OrderStatus.COMPLETED,
    ]
    revenue = Decimal(
        OrderLine.objects.filter(order__status__in=paid_statuses).aggregate(
            total=Sum(F("quantity") * F("price"))
        )["total"]
        or 0
    ).quantize(Decimal("0.01"))

    recent = done.select_related("product", "recipe_version").prefetch_related(
        "consumptions__lot__material", "overheads"
    )[:10]
    batches = []
    for batch in recent:
        report = cost_report(batch)
        batches.append(
            {
                "number": batch.number,
                "product": batch.product.name,
                "quantity": batch.actual_quantity,
                "cost_per_kg": report["cost_per_kg"],
                "recommended_price": report["recommended_price"],
                "yield_percent": report["yield_percent"],
                "below_norm": report["yield_below_norm"],
            }
        )

    context = {
        "produced_today": produced_today,
        "finished_goods": finished_goods,
        "raw_materials": raw_materials,
        "revenue": revenue,
        "batches": batches,
        "low_stock": low_stock_report(),
        "orders": Order.objects.select_related("customer").prefetch_related("lines")[:10],
    }
    return render(request, "dashboard.html", context)
