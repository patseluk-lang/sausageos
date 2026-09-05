import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("sausageos")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "low-stock-check": {
        "task": "apps.inventory.tasks.check_low_stock",
        "schedule": crontab(hour=7, minute=0),
    },
    "expiring-lots-check": {
        "task": "apps.inventory.tasks.check_expiring_lots",
        "schedule": crontab(hour=7, minute=10),
    },
}
