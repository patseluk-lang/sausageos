from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.production import services as production

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return APIClient()


def auth(client, user):
    response = client.post(
        "/api/token/", {"username": user.username, "password": "test12345"}, format="json"
    )
    assert response.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return client


def test_token_required(client):
    assert client.get("/api/products/").status_code == 401


def test_jwt_gives_access(client, users, product):
    response = auth(client, users["technologist"]).get("/api/products/")
    assert response.status_code == 200
    assert response.data["results"][0]["sku"] == "KAVKAZ"


def test_warehouse_manager_cannot_create_production_batch(
    client, users, product, recipe_version, raw_warehouse, fg_warehouse
):
    payload = {
        "product": product.id,
        "recipe_version": recipe_version.id,
        "planned_quantity": "250",
        "source_warehouse": raw_warehouse.id,
        "output_warehouse": fg_warehouse.id,
    }
    assert (
        auth(client, users["storekeeper"])
        .post("/api/production/batches/", payload, format="json")
        .status_code
        == 403
    )
    assert (
        auth(client, users["technologist"])
        .post("/api/production/batches/", payload, format="json")
        .status_code
        == 201
    )


def test_production_manager_cannot_create_material(client, users, supplier):
    response = auth(client, users["technologist"]).post(
        "/api/materials/", {"name": "Chicken", "sku": "CHICK", "unit": "KG"}, format="json"
    )
    assert response.status_code == 403


def test_batch_availability_endpoint_reports_deficit(
    client, users, product, recipe_version, raw_warehouse, fg_warehouse, stocked
):
    batch = production.create_batch(
        product=product,
        recipe_version=recipe_version,
        planned_quantity=Decimal("500"),
        source_warehouse=raw_warehouse,
        output_warehouse=fg_warehouse,
    )
    response = auth(client, users["technologist"]).get(
        f"/api/production/batches/{batch.id}/availability/"
    )
    assert response.status_code == 200
    assert response.data["can_start"] is False
    assert response.data["deficits"][0]["deficit"] == Decimal("50.000")


def test_reserve_endpoint_returns_400_on_deficit(
    client, users, product, recipe_version, raw_warehouse, fg_warehouse, stocked
):
    batch = production.create_batch(
        product=product,
        recipe_version=recipe_version,
        planned_quantity=Decimal("500"),
        source_warehouse=raw_warehouse,
        output_warehouse=fg_warehouse,
    )
    response = auth(client, users["technologist"]).post(
        f"/api/production/batches/{batch.id}/reserve/"
    )
    assert response.status_code == 400
    assert "Cannot start production" in response.data["detail"]


def test_full_production_cycle_via_api(
    client, users, product, recipe_version, raw_warehouse, fg_warehouse, stocked
):
    api = auth(client, users["technologist"])
    created = api.post(
        "/api/production/batches/",
        {
            "product": product.id,
            "recipe_version": recipe_version.id,
            "planned_quantity": "250",
            "source_warehouse": raw_warehouse.id,
            "output_warehouse": fg_warehouse.id,
        },
        format="json",
    )
    batch_id = created.data["id"]
    assert api.post(f"/api/production/batches/{batch_id}/reserve/").status_code == 200
    assert api.post(f"/api/production/batches/{batch_id}/start/").status_code == 200
    finished = api.post(
        f"/api/production/batches/{batch_id}/finish/", {"actual_quantity": "244.2"}, format="json"
    )
    assert finished.status_code == 200
    assert Decimal(finished.data["yield_percent"]) == Decimal("97.68")

    cost = api.get(f"/api/production/batches/{batch_id}/cost/")
    assert cost.data["cost_per_kg"] == Decimal("182.72")


def test_inventory_and_recall_endpoints(
    client, users, product, recipe_version, raw_warehouse, fg_warehouse, stocked
):
    batch = production.create_batch(
        product=product,
        recipe_version=recipe_version,
        planned_quantity=Decimal("250"),
        source_warehouse=raw_warehouse,
        output_warehouse=fg_warehouse,
    )
    production.reserve_materials(batch)
    production.start(batch)
    production.finish(batch, actual_quantity=Decimal("244.2"))

    api = auth(client, users["storekeeper"])
    inventory_response = api.get("/api/inventory/")
    assert inventory_response.status_code == 200
    assert any(
        row["lot_code"] == f"FG-{batch.number}" for row in inventory_response.data["results"]
    )

    recall = api.get("/api/traceability/recall/PORK-2026-0815/")
    assert recall.status_code == 200
    assert recall.data["affected_quantity"] == Decimal("244.200")


def test_swagger_schema_available(client, users):
    response = auth(client, users["admin"]).get("/api/schema/")
    assert response.status_code == 200


def test_dashboard_page_renders(client, users, product):
    client.force_login(users["technologist"])
    response = client.get("/")
    assert response.status_code == 200
    assert "SausageOS" in response.content.decode()
