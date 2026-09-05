from rest_framework import serializers

from apps.catalog.models import Material, Product, Supplier
from apps.inventory.models import StockLot, StockMove, Warehouse
from apps.production.models import ProductionBatch
from apps.recipes.models import Recipe, RecipeLine, RecipeVersion
from apps.sales.models import Customer, Order, OrderLine


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ("id", "name", "tax_id", "contact", "is_active")


class MaterialSerializer(serializers.ModelSerializer):
    on_hand = serializers.SerializerMethodField()

    class Meta:
        model = Material
        fields = (
            "id",
            "name",
            "sku",
            "category",
            "unit",
            "min_stock",
            "shelf_life_days",
            "default_supplier",
            "is_active",
            "on_hand",
        )

    def get_on_hand(self, obj):
        from apps.inventory.services import on_hand

        return on_hand(material=obj)


class ProductSerializer(serializers.ModelSerializer):
    on_hand = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ("id", "name", "sku", "unit", "target_margin", "is_active", "on_hand")

    def get_on_hand(self, obj):
        from apps.inventory.services import on_hand

        return on_hand(product=obj)


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ("id", "code", "name")


class RecipeLineSerializer(serializers.ModelSerializer):
    material_name = serializers.CharField(source="material.name", read_only=True)

    class Meta:
        model = RecipeLine
        fields = ("id", "material", "material_name", "basis", "quantity")


class RecipeVersionSerializer(serializers.ModelSerializer):
    lines = RecipeLineSerializer(many=True, read_only=True)

    class Meta:
        model = RecipeVersion
        fields = (
            "id",
            "recipe",
            "version",
            "valid_from",
            "status",
            "yield_min",
            "yield_max",
            "notes",
            "lines",
        )


class RecipeSerializer(serializers.ModelSerializer):
    versions = RecipeVersionSerializer(many=True, read_only=True)

    class Meta:
        model = Recipe
        fields = ("id", "product", "description", "versions")


class StockLotSerializer(serializers.ModelSerializer):
    item = serializers.CharField(source="item_name", read_only=True)
    on_hand = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    available = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)

    class Meta:
        model = StockLot
        fields = (
            "id",
            "lot_code",
            "item",
            "warehouse",
            "material",
            "product",
            "supplier",
            "supplier_batch_code",
            "document",
            "received_at",
            "expiry_date",
            "unit_cost",
            "on_hand",
            "available",
        )


class StockMoveSerializer(serializers.ModelSerializer):
    lot_code = serializers.CharField(source="lot.lot_code", read_only=True)

    class Meta:
        model = StockMove
        fields = (
            "id",
            "lot",
            "lot_code",
            "move_type",
            "quantity",
            "occurred_at",
            "document",
            "note",
        )


class ReceiveSerializer(serializers.Serializer):
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.all())
    material = serializers.PrimaryKeyRelatedField(queryset=Material.objects.all(), required=False)
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all(), required=False)
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.all(), required=False)
    lot_code = serializers.CharField()
    supplier_batch_code = serializers.CharField(required=False, allow_blank=True)
    document = serializers.CharField(required=False, allow_blank=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=4)
    received_at = serializers.DateField()
    expiry_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        if bool(attrs.get("material")) == bool(attrs.get("product")):
            raise serializers.ValidationError("Specify either a material or a product.")
        return attrs


class ProductionBatchSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    yield_percent = serializers.DecimalField(
        max_digits=6, decimal_places=2, read_only=True, allow_null=True
    )

    class Meta:
        model = ProductionBatch
        fields = (
            "id",
            "number",
            "product",
            "product_name",
            "recipe_version",
            "planned_quantity",
            "actual_quantity",
            "status",
            "source_warehouse",
            "output_warehouse",
            "planned_date",
            "started_at",
            "finished_at",
            "yield_percent",
        )
        read_only_fields = ("number", "status", "actual_quantity", "started_at", "finished_at")


class FinishBatchSerializer(serializers.Serializer):
    actual_quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    expiry_date = serializers.DateField(required=False, allow_null=True)


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ("id", "name", "contact", "address")


class OrderLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = OrderLine
        fields = ("id", "product", "product_name", "quantity", "price")


class OrderSerializer(serializers.ModelSerializer):
    lines = OrderLineSerializer(many=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Order
        fields = (
            "id",
            "number",
            "customer",
            "status",
            "warehouse",
            "ordered_at",
            "shipped_at",
            "lines",
            "total",
        )
        read_only_fields = ("number", "status", "shipped_at")

    def create(self, validated_data):
        from apps.sales.services import create_order

        lines = validated_data.pop("lines")
        return create_order(
            customer=validated_data["customer"],
            warehouse=validated_data["warehouse"],
            lines=lines,
            user=self.context["request"].user,
        )
