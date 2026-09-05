from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.core.services import log_action

from .models import StockLot
from .services import low_stock_report


@shared_task
def check_low_stock() -> int:
    rows = low_stock_report()
    for row in rows:
        log_action(
            "alert.low_stock",
            row["material"],
            None,
            on_hand=str(row["on_hand"]),
            min_stock=str(row["min_stock"]),
        )
    return len(rows)


@shared_task
def check_expiring_lots(days: int = 7) -> int:
    limit = timezone.localdate() + timedelta(days=days)
    count = 0
    for lot in StockLot.objects.filter(expiry_date__lte=limit).exclude(expiry_date=None):
        if lot.on_hand > 0:
            log_action("alert.expiring_lot", lot, None, expiry_date=str(lot.expiry_date))
            count += 1
    return count
