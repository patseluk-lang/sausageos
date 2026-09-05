from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.catalog.models import Material, MaterialCategory, Product, Supplier, Unit
from apps.core.models import Role, User
from apps.inventory import services as inventory
from apps.inventory.models import Warehouse
from apps.recipes.models import LineBasis, Recipe, RecipeLine, RecipeVersion

TODAY = date(2026, 9, 1)


@pytest.fixture
def raw_warehouse(db):
    return Warehouse.objects.create(code="RAW", name="Raw material warehouse")


@pytest.fixture
def fg_warehouse(db):
    return Warehouse.objects.create(code="FG", name="Finished goods warehouse")


@pytest.fixture
def supplier(db):
    return Supplier.objects.create(name="Skhid Meat Plant", tax_id="32541698")


@pytest.fixture
def materials(db, supplier):
    specs = [
        ("Pork", "PORK", MaterialCategory.RAW, Unit.KG, 100),
        ("Beef", "BEEF", MaterialCategory.RAW, Unit.KG, 50),
        ("Pork backfat", "FAT", MaterialCategory.RAW, Unit.KG, 30),
        ("Curing salt", "SALT-N", MaterialCategory.SPICE, Unit.KG, 5),
        ("Collagen casing 45", "CASING45", MaterialCategory.CASING, Unit.M, 100),
        ("Vacuum bag", "VACBAG", MaterialCategory.PACKAGING, Unit.PCS, 100),
    ]
    return {
        sku: Material.objects.create(
            name=name,
            sku=sku,
            category=cat,
            unit=unit,
            min_stock=min_stock,
            default_supplier=supplier,
            shelf_life_days=30,
        )
        for name, sku, cat, unit, min_stock in specs
    }


@pytest.fixture
def product(db):
    return Product.objects.create(
        name="Caucasian sausage", sku="KAVKAZ", target_margin=Decimal("33.30")
    )


@pytest.fixture
def recipe_version(db, product, materials):
    recipe = Recipe.objects.create(product=product)
    version = RecipeVersion.objects.create(
        recipe=recipe,
        version="v2.0",
        valid_from=TODAY,
        yield_min=Decimal("98"),
        yield_max=Decimal("99"),
    )
    for sku, basis, qty in [
        ("PORK", LineBasis.PERCENT, "70"),
        ("BEEF", LineBasis.PERCENT, "20"),
        ("FAT", LineBasis.PERCENT, "10"),
        ("SALT-N", LineBasis.PER_100KG, "2"),
        ("CASING45", LineBasis.PER_100KG, "12"),
        ("VACBAG", LineBasis.PER_100KG, "20"),
    ]:
        RecipeLine.objects.create(
            version=version, material=materials[sku], basis=basis, quantity=Decimal(qty)
        )
    version.activate()
    version.refresh_from_db()
    return version


@pytest.fixture
def stocked(db, raw_warehouse, supplier, materials):
    """Material in stock: pork in three lots at different prices."""
    lots = {}
    for code, price, qty, days in [
        ("PORK-2026-0801", "165", 100, 3),
        ("PORK-2026-0815", "172", 100, 6),
        ("PORK-2026-0828", "181", 100, 9),
    ]:
        lots[code] = inventory.receive(
            warehouse=raw_warehouse,
            lot_code=f"SL-{code}",
            material=materials["PORK"],
            supplier=supplier,
            supplier_batch_code=code,
            document=f"GRN-{code}",
            quantity=qty,
            unit_cost=price,
            received_at=TODAY,
            expiry_date=TODAY + timedelta(days=days),
        )
    for sku, code, price, qty in [
        ("BEEF", "BEEF-2026-0820", "245", 100),
        ("FAT", "FAT-2026-0820", "95", 100),
        ("SALT-N", "SALT-2026-0701", "48", 20),
        ("CASING45", "CAS-2026-0610", "6.5", 500),
        ("VACBAG", "BAG-2026-0610", "3.2", 500),
    ]:
        lots[code] = inventory.receive(
            warehouse=raw_warehouse,
            lot_code=f"SL-{code}",
            material=materials[sku],
            supplier=supplier,
            supplier_batch_code=code,
            document=f"GRN-{code}",
            quantity=qty,
            unit_cost=price,
            received_at=TODAY,
            expiry_date=TODAY + timedelta(days=60),
        )
    return lots

