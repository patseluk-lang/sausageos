from celery import shared_task

from apps.core.services import log_action

from .models import BatchStatus, ProductionBatch
from .services import cost_report


@shared_task
def recalculate_batch_cost(batch_id: int) -> str:
    """Recalculate the batch cost in the background."""
    batch = ProductionBatch.objects.get(pk=batch_id)
    report = cost_report(batch)
    log_action("production.cost_recalculated", batch, None, total=str(report["total_cost"]))
    return str(report["total_cost"])


@shared_task
def check_yield_deviations() -> int:
    count = 0
    for batch in ProductionBatch.objects.filter(status=BatchStatus.DONE):
        if batch.yield_is_below_norm:
            log_action("alert.low_yield", batch, None, yield_percent=str(batch.yield_percent))
            count += 1
    return count
