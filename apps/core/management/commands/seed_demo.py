"""Demo data: the full cycle from goods receipt to shipment."""

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Material, MaterialCategory, Product, Supplier, Unit
from apps.core.models import Role, User
from apps.inventory import services as inventory
from apps.inventory.models import Warehouse
from apps.production import services as production
from apps.recipes.models import LineBasis, Recipe, RecipeLine, RecipeVersion
from apps.sales import services as sales
from apps.sales.models import Customer


class Command(BaseCommand):
    help = "Populate the database with SausageOS demo data"

    @transaction.atomic
    def handle(self, *args, **options):
        for username, role in [
            ("admin", Role.ADMIN),
            ("technologist", Role.PRODUCTION_MANAGER),
            ("storekeeper", Role.WAREHOUSE_MANAGER),
            ("accountant", Role.ACCOUNTANT),
            ("sales", Role.SALES_MANAGER),
        ]:
            user, created = User.objects.get_or_create(username=username, defaults={"role": role})
            if created:
                user.set_password("demo12345")
                if username == "admin":
                    user.is_superuser = user.is_staff = True
                user.save()

        raw_wh, _ = Warehouse.objects.get_or_create(
            code="RAW", defaults={"name": "Raw material warehouse"}
        )
        fg_wh, _ = Warehouse.objects.get_or_create(
            code="FG", defaults={"name": "Finished goods warehouse"}
        )
        supplier, _ = Supplier.objects.get_or_create(
            name="Skhid Meat Plant", defaults={"tax_id": "32541698"}
        )

        specs = [
            ("Pork", "PORK", MaterialCategory.RAW, Unit.KG, 100, 5),
            ("Beef", "BEEF", MaterialCategory.RAW, Unit.KG, 50, 5),
            ("Pork backfat", "FAT", MaterialCategory.RAW, Unit.KG, 30, 10),
            ("Curing salt", "SALT-N", MaterialCategory.SPICE, Unit.KG, 10, 365),
            ("Black pepper", "PEPPER", MaterialCategory.SPICE, Unit.KG, 2, 365),
            ("Coriander", "CORIAND", MaterialCategory.SPICE, Unit.KG, 2, 365),
            ("Dried garlic", "GARLIC", MaterialCategory.SPICE, Unit.KG, 2, 365),
            ("Collagen casing 45", "CASING45", MaterialCategory.CASING, Unit.M, 200, 720),
            ("Vacuum bag", "VACBAG", MaterialCategory.PACKAGING, Unit.PCS, 200, 0),
        ]
        materials = {}
        for name, sku, category, unit, min_stock, shelf in specs:
            materials[sku], _ = Material.objects.get_or_create(
                sku=sku,
                defaults={
                    "name": name,
                    "category": category,
                    "unit": unit,
                    "min_stock": min_stock,
                    "shelf_life_days": shelf,
                    "default_supplier": supplier,
                },
            )

        product, _ = Product.objects.get_or_create(
            sku="KAVKAZ", defaults={"name": "Caucasian sausage", "target_margin": Decimal("33.30")}
        )
        recipe, _ = Recipe.objects.get_or_create(product=product)

        if not recipe.versions.exists():
            v1 = RecipeVersion.objects.create(
                recipe=recipe, version="v1.0", valid_from=date(2026, 6, 1)
            )
            RecipeLine.objects.create(
                version=v1,
                material=materials["PORK"],
                basis=LineBasis.PERCENT,
                quantity=Decimal("75"),
            )
            RecipeLine.objects.create(
                version=v1,
                material=materials["BEEF"],
                basis=LineBasis.PERCENT,
                quantity=Decimal("15"),
            )
            RecipeLine.objects.create(
                version=v1,
                material=materials["FAT"],
                basis=LineBasis.PERCENT,
                quantity=Decimal("10"),
            )
            v1.activate()

            v2 = RecipeVersion.objects.create(
                recipe=recipe,
                version="v2.0",
                valid_from=date(2026, 9, 1),
                yield_min=Decimal("98"),
                yield_max=Decimal("99"),
            )
            for sku, basis, qty in [
                ("PORK", LineBasis.PERCENT, "70"),
                ("BEEF", LineBasis.PERCENT, "20"),
                ("FAT", LineBasis.PERCENT, "10"),
                ("SALT-N", LineBasis.PER_100KG, "2"),
                ("PEPPER", LineBasis.PER_100KG, "0.3"),
                ("CORIAND", LineBasis.PER_100KG, "0.2"),
                ("GARLIC", LineBasis.PER_100KG, "0.5"),
                ("CASING45", LineBasis.PER_100KG, "12"),
                ("VACBAG", LineBasis.PER_100KG, "20"),
            ]:
                RecipeLine.objects.create(
                    version=v2, material=materials[sku], basis=basis, quantity=Decimal(qty)
                )
            v2.activate()

        active = recipe.active_version
        today = date(2026, 9, 1)

        pork_lots = [
            ("PORK-2026-0801", date(2026, 8, 1), "165", 200),
            ("PORK-2026-0815", date(2026, 8, 15), "172", 200),
            ("PORK-2026-0828", date(2026, 8, 28), "181", 200),
        ]
        for code, received, price, qty in pork_lots:
            inventory.receive(
                warehouse=raw_wh,
                lot_code=f"SL-{code}",
                material=materials["PORK"],
                supplier=supplier,
                supplier_batch_code=code,
                document=f"GRN-{code}",
                quantity=qty,
                unit_cost=price,
                received_at=received,
                expiry_date=received + timedelta(days=5),
            )

        other_lots = [
            ("BEEF", "BEEF-2026-0820", "245", 150),
            ("FAT", "FAT-2026-0820", "95", 100),
            ("SALT-N", "SALT-2026-0701", "48", 25),
            ("PEPPER", "PEP-2026-0701", "410", 5),
            ("CORIAND", "COR-2026-0701", "290", 5),
            ("GARLIC", "GAR-2026-0701", "320", 5),
            ("CASING45", "CAS-2026-0610", "6.5", 1000),
            ("VACBAG", "BAG-2026-0610", "3.2", 1000),
        ]
        for sku, code, price, qty in other_lots:
            inventory.receive(
                warehouse=raw_wh,
                lot_code=f"SL-{code}",
                material=materials[sku],
                supplier=supplier,
                supplier_batch_code=code,
                document=f"GRN-{code}",
                quantity=qty,
                unit_cost=price,
                received_at=today - timedelta(days=10),
                expiry_date=today + timedelta(days=materials[sku].shelf_life_days or 30),
            )

        batch = production.create_batch(
            product=product,
            recipe_version=active,
            planned_quantity=Decimal("250"),
            source_warehouse=raw_wh,
            output_warehouse=fg_wh,
        )
        production.reserve_materials(batch)
        production.start(batch)
        production.finish(
            batch, actual_quantity=Decimal("244.2"), expiry_date=today + timedelta(days=30)
        )

        customer, _ = Customer.objects.get_or_create(
            name="Smak Grocery", defaults={"address": "12 Sichovykh Striltsiv St, Kyiv"}
        )
        report = production.cost_report(batch)
        order = sales.create_order(
            customer=customer,
            warehouse=fg_wh,
            lines=[
                {
                    "product": product,
                    "quantity": Decimal("12"),
                    "price": report["recommended_price"],
                }
            ],
        )
        sales.confirm(order)
        sales.reserve(order)
        sales.mark_paid(order)
        sales.start_processing(order)
        sales.ship(order)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Batch {batch.number}: yield {batch.yield_percent}%, "
                f"cost {report['cost_per_kg']} UAH/kg, "
                f"recommended price {report['recommended_price']} UAH/kg. "
                f"Users: admin/technologist/storekeeper/accountant/sales, password demo12345."
            )
        )
