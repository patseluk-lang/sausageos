from django.urls import path

from . import warehouse
from .views import dashboard

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("warehouse/", warehouse.index, name="warehouse"),
    path("warehouse/lots/", warehouse.lot_table, name="warehouse-lots"),
    path("warehouse/receive/", warehouse.receive, name="warehouse-receive"),
    path("warehouse/lots/<int:pk>/stock-take/", warehouse.stock_take, name="warehouse-stock-take"),
    path("warehouse/lots/<int:pk>/write-off/", warehouse.write_off, name="warehouse-write-off"),
]
