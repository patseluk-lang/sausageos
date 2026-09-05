from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.recipes.models import LineBasis, RecipeLine, RecipeVersion, RecipeVersionStatus

pytestmark = pytest.mark.django_db


def test_requirements_calculated_from_percentages(recipe_version, materials):
    req = recipe_version.requirements(Decimal("250"))
    assert req[materials["PORK"]] == Decimal("175.000")
    assert req[materials["BEEF"]] == Decimal("50.000")
    assert req[materials["FAT"]] == Decimal("25.000")


def test_requirements_per_100kg_basis(recipe_version, materials):
    req = recipe_version.requirements(Decimal("250"))
    assert req[materials["SALT-N"]] == Decimal("5.000")
    assert req[materials["CASING45"]] == Decimal("30.000")


def test_active_version_cannot_be_edited(recipe_version, materials):
    assert recipe_version.is_locked
    with pytest.raises(ValidationError):
        RecipeLine.objects.create(
            version=recipe_version,
            material=materials["SALT-N"],
            basis=LineBasis.PER_100KG,
            quantity=Decimal("3"),
        )


def test_new_version_archives_previous(recipe_version, materials):
    new_version = RecipeVersion.objects.create(
        recipe=recipe_version.recipe, version="v3.0", valid_from=recipe_version.valid_from
    )
    RecipeLine.objects.create(
        version=new_version,
        material=materials["PORK"],
        basis=LineBasis.PERCENT,
        quantity=Decimal("100"),
    )
    new_version.activate()
    recipe_version.refresh_from_db()
    assert recipe_version.status == RecipeVersionStatus.ARCHIVED
    assert recipe_version.recipe.active_version == new_version


def test_version_without_lines_cannot_be_activated(recipe_version):
    empty = RecipeVersion.objects.create(
        recipe=recipe_version.recipe, version="v9.9", valid_from=recipe_version.valid_from
    )
    with pytest.raises(ValidationError):
        empty.activate()
