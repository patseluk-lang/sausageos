from decimal import Decimal

from django.db.models import F, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Material, Product, Supplier
from apps.core.models import AuditLog, Role
from apps.core.permissions import RoleBasedPermission
from apps.inventory import services as inventory
from apps.inventory.models import StockLot, StockMove, Warehouse
from apps.production import services as production
from apps.production.models import ProductionBatch
from apps.recipes.models import Recipe, RecipeVersion
from apps.sales import services as sales
from apps.sales.models import Customer, Order
from apps.traceability import services as traceability

from . import serializers as s


class BaseViewSet(viewsets.ModelViewSet):
    permission_classes = [RoleBasedPermission]


class SupplierViewSet(BaseViewSet):
    queryset = Supplier.objects.all()
    serializer_class = s.SupplierSerializer
    search_fields = ("name", "tax_id")
    write_roles = (Role.WAREHOUSE_MANAGER,)


class MaterialViewSet(BaseViewSet):
    queryset = Material.objects.all()
    serializer_class = s.MaterialSerializer
    search_fields = ("name", "sku")
    filterset_fields = ("category", "is_active")
    write_roles = (Role.WAREHOUSE_MANAGER,)


class ProductViewSet(BaseViewSet):
    queryset = Product.objects.all()
    serializer_class = s.ProductSerializer
    search_fields = ("name", "sku")
    write_roles = (Role.PRODUCTION_MANAGER,)


class WarehouseViewSet(BaseViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = s.WarehouseSerializer
    write_roles = (Role.WAREHOUSE_MANAGER,)


class RecipeViewSet(BaseViewSet):
    queryset = Recipe.objects.prefetch_related("versions__lines")
    serializer_class = s.RecipeSerializer
    write_roles = (Role.PRODUCTION_MANAGER,)


class RecipeVersionViewSet(BaseViewSet):
    queryset = RecipeVersion.objects.prefetch_related("lines")
    serializer_class = s.RecipeVersionSerializer
    filterset_fields = ("recipe", "status")
    write_roles = (Role.PRODUCTION_MANAGER,)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        version = self.get_object()
        version.activate()
        return Response(self.get_serializer(version).data)


class StockLotViewSet(BaseViewSet):
    queryset = StockLot.objects.select_related("material", "product", "warehouse")
    serializer_class = s.StockLotSerializer
    search_fields = ("lot_code", "supplier_batch_code")
    filterset_fields = ("warehouse", "material", "product")
    write_roles = (Role.WAREHOUSE_MANAGER,)

    @extend_schema(request=s.ReceiveSerializer, responses=s.StockLotSerializer)
    @action(detail=False, methods=["post"])
    def receive(self, request):
        payload = s.ReceiveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        lot = inventory.receive(**payload.validated_data, user=request.user)
        return Response(s.StockLotSerializer(lot).data, status=status.HTTP_201_CREATED)


class StockMoveViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = StockMove.objects.select_related("lot")
    serializer_class = s.StockMoveSerializer
    permission_classes = [RoleBasedPermission]
    filterset_fields = ("move_type", "lot")


class InventoryView(APIView):
    """Stock balances by lot, with totals."""

    permission_classes = [RoleBasedPermission]

    def get(self, request):
        rows = []
        lots = StockLot.objects.with_stock().select_related("material", "product", "warehouse")
        for lot in lots:
            on_hand = lot.on_hand
            if on_hand == 0 and request.query_params.get("all") != "1":
                continue
            rows.append(
                {
                    "lot_code": lot.lot_code,
                    "item": lot.item_name,
                    "kind": "material" if lot.material_id else "product",
                    "warehouse": lot.warehouse.code,
                    "supplier_batch_code": lot.supplier_batch_code,
                    "expiry_date": lot.expiry_date,
                    "on_hand": on_hand,
                    "reserved": lot.reserved,
                    "available": lot.available,
                    "unit_cost": lot.unit_cost,
                }
            )
        return Response({"count": len(rows), "results": rows})


class LowStockView(APIView):
    permission_classes = [RoleBasedPermission]

    def get(self, request):
        rows = [
            {
                "material": r["material"].name,
                "on_hand": r["on_hand"],
                "min_stock": r["min_stock"],
                "deficit": r["deficit"],
            }
            for r in inventory.low_stock_report()
        ]
        return Response(rows)


class ProductionBatchViewSet(BaseViewSet):
    queryset = ProductionBatch.objects.select_related("product", "recipe_version")
    serializer_class = s.ProductionBatchSerializer
    filterset_fields = ("status", "product")
    search_fields = ("number",)
    write_roles = (Role.PRODUCTION_MANAGER,)

    def perform_create(self, serializer):
        data = serializer.validated_data
        batch = production.create_batch(
            product=data["product"],
            recipe_version=data["recipe_version"],
            planned_quantity=data["planned_quantity"],
            source_warehouse=data["source_warehouse"],
            output_warehouse=data["output_warehouse"],
            user=self.request.user,
        )
        serializer.instance = batch

    @action(detail=True, methods=["get"])
    def requirements(self, request, pk=None):
        batch = self.get_object()
        return Response(
            [
                {"material": m.name, "required": qty, "unit": m.get_unit_display()}
                for m, qty in production.requirements(batch).items()
            ]
        )

    @action(detail=True, methods=["get"])
    def availability(self, request, pk=None):
        deficits = production.check_availability(self.get_object())
        return Response({"can_start": not deficits, "deficits": deficits})

    @action(detail=True, methods=["post"])
    def reserve(self, request, pk=None):
        batch = production.reserve_materials(self.get_object(), user=request.user)
        return Response(self.get_serializer(batch).data)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        batch = production.start(self.get_object(), user=request.user)
        return Response(self.get_serializer(batch).data)

    @extend_schema(request=s.FinishBatchSerializer, responses=s.ProductionBatchSerializer)
    @action(detail=True, methods=["post"])
    def finish(self, request, pk=None):
        payload = s.FinishBatchSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        batch = production.finish(self.get_object(), user=request.user, **payload.validated_data)
        return Response(self.get_serializer(batch).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        batch = production.cancel(self.get_object(), user=request.user)
        return Response(self.get_serializer(batch).data)

    @action(detail=True, methods=["get"])
    def cost(self, request, pk=None):
        return Response(production.cost_report(self.get_object()))


class CustomerViewSet(BaseViewSet):
    queryset = Customer.objects.all()
    serializer_class = s.CustomerSerializer
    write_roles = (Role.SALES_MANAGER,)


class OrderViewSet(BaseViewSet):
    queryset = Order.objects.select_related("customer").prefetch_related("lines")
    serializer_class = s.OrderSerializer
    filterset_fields = ("status", "customer")
    search_fields = ("number",)
    write_roles = (Role.SALES_MANAGER,)

    def _apply(self, request, func):
        order = func(self.get_object(), user=request.user)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        return self._apply(request, sales.confirm)

    @action(detail=True, methods=["post"])
    def reserve(self, request, pk=None):
        return self._apply(request, sales.reserve)

    @action(detail=True, methods=["post"], url_path="pay")
    def pay(self, request, pk=None):
        return self._apply(request, sales.mark_paid)

    @action(detail=True, methods=["post"])
    def process(self, request, pk=None):
        return self._apply(request, sales.start_processing)

    @action(detail=True, methods=["post"])
    def ship(self, request, pk=None):
        return self._apply(request, sales.ship)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._apply(request, sales.complete)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._apply(request, sales.cancel)


class ProfitabilityView(APIView):
    permission_classes = [RoleBasedPermission]
    read_roles = (Role.ACCOUNTANT, Role.PRODUCTION_MANAGER, Role.SALES_MANAGER)

    def get(self, request):
        return Response(production.profitability_report())


class RecallView(APIView):
    permission_classes = [RoleBasedPermission]

    def get(self, request, supplier_batch_code: str):
        return Response(traceability.recall(supplier_batch_code, user=request.user))


class TraceBackView(APIView):
    permission_classes = [RoleBasedPermission]

    def get(self, request, lot_code: str):
        return Response(traceability.trace_back(lot_code))


class AuditLogView(APIView):
    permission_classes = [RoleBasedPermission]
    read_roles = (Role.ACCOUNTANT, Role.PRODUCTION_MANAGER, Role.WAREHOUSE_MANAGER)

    def get(self, request):
        logs = AuditLog.objects.all()[:200]
        return Response(
            [
                {
                    "created_at": log.created_at,
                    "action": log.action,
                    "object": f"{log.object_type}#{log.object_id}",
                    "actor": log.actor.username if log.actor else None,
                    "payload": log.payload,
                }
                for log in logs
            ]
        )


class DashboardMetricsView(APIView):
    permission_classes = [RoleBasedPermission]

    def get(self, request):
        from apps.production.models import BatchStatus
        from apps.sales.models import OrderLine, OrderStatus

        produced_today = Decimal(
            ProductionBatch.objects.filter(
                status=BatchStatus.DONE, finished_at__date=timezone.localdate()
            ).aggregate(q=Sum("actual_quantity"))["q"]
            or 0
        ).quantize(Decimal("0.001"))
        finished_goods = inventory.total_on_hand(kind="product")
        raw_materials = inventory.total_on_hand(kind="material")
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
        return Response(
            {
                "produced_today": produced_today,
                "finished_goods": finished_goods,
                "raw_materials": raw_materials,
                "revenue": revenue,
                "low_stock": len(inventory.low_stock_report()),
            }
        )
