from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.catalog.models import Material, MaterialCategory, Product, Supplier, Unit
from apps.core.models import Role, User
from apps.recipes.models import LineBasis, Recipe, RecipeLine, RecipeVersion

TODAY = date(2026, 9, 1)


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

