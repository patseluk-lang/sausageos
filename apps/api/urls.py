from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import views

router = DefaultRouter()
router.register("suppliers", views.SupplierViewSet)
router.register("materials", views.MaterialViewSet)
router.register("products", views.ProductViewSet)
router.register("warehouses", views.WarehouseViewSet)
router.register("recipes", views.RecipeViewSet)
router.register("recipe-versions", views.RecipeVersionViewSet)
router.register("lots", views.StockLotViewSet)
router.register("moves", views.StockMoveViewSet)
router.register("production/batches", views.ProductionBatchViewSet)
router.register("customers", views.CustomerViewSet)
router.register("orders", views.OrderViewSet)

urlpatterns = [
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("inventory/", views.InventoryView.as_view(), name="inventory"),
    path("inventory/low-stock/", views.LowStockView.as_view(), name="low-stock"),
    path("reports/profitability/", views.ProfitabilityView.as_view(), name="profitability"),
    path("reports/dashboard/", views.DashboardMetricsView.as_view(), name="dashboard-metrics"),
    path("audit/", views.AuditLogView.as_view(), name="audit"),
    path(
        "traceability/recall/<str:supplier_batch_code>/", views.RecallView.as_view(), name="recall"
    ),
    path("traceability/lot/<str:lot_code>/", views.TraceBackView.as_view(), name="trace-back"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("", include(router.urls)),
]
