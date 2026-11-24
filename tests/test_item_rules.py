"""Unit tests for the item rules that the endpoint tests cannot reach directly (B4.5)."""

import importlib
from pathlib import Path
from typing import Any

import pytest
from django.db import IntegrityError
from django.urls import clear_url_caches
from rest_framework.exceptions import ValidationError

from config.errors import ApiError
from inventory import services
from inventory.models import Brand, Category, Item, Subtype
from tests.test_items_api import body


def test_key_specs_must_be_an_object_and_valid_booleans_are_kept() -> None:
    with pytest.raises(ValidationError):
        services.validate_key_specs("Laptop", ["ram_gb"])
    assert services.validate_key_specs("Laptop", {"touchscreen": True, "ram_gb": 0}) == {
        "touchscreen": True,
        "ram_gb": 0,
    }
    with pytest.raises(ValidationError):
        services.validate_key_specs("Laptop", {"ram_gb": -1})
    assert services.validate_key_specs("Unknown category", {}) == {}


def test_a_create_without_a_category_is_refused() -> None:
    with pytest.raises(ApiError) as caught:
        services._clean({}, None)
    assert caught.value.status == 400 and caught.value.message == "Choose a category."


@pytest.mark.parametrize("operation", ["create", "update", "brand"])
def test_a_lost_unique_race_is_a_409_or_400_not_a_500(
    users: dict[str, Any], monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    brand = Brand.objects.create(name="HP")
    sa = users["sa"]
    request = None  # the audit client meta tolerates no request

    def racing(*args: Any, **kwargs: Any) -> Any:
        raise IntegrityError("unique")

    if operation == "create":
        monkeypatch.setattr(Item.objects, "create", racing)
        with pytest.raises(ApiError) as caught:
            services.create_item(request, sa, body(brand))  # type: ignore[arg-type]
        assert caught.value.status == 409 and caught.value.code == "conflict"
    elif operation == "update":
        item = Item.objects.create(
            sku="S1",
            name="N",
            category=Category.objects.get(name="Laptop"),
            subtype=Subtype.objects.filter(category__name="Laptop").first(),
            brand=brand,
        )
        monkeypatch.setattr(Item, "save", racing)
        with pytest.raises(ApiError) as caught:
            services.update_item(request, sa, item.pk, {"name": "X"})  # type: ignore[arg-type]
        assert caught.value.status == 409
    else:
        monkeypatch.setattr(Brand, "save", racing)
        with pytest.raises(ApiError) as caught:
            services.save_brand(request, sa, {"name": "Racer"})  # type: ignore[arg-type]
        assert caught.value.status == 400 and caught.value.field == "name"


def test_uploaded_images_are_served_only_in_debug(settings: Any, tmp_path: Path) -> None:
    import config.urls

    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "x.txt").write_text("hi")
    settings.MEDIA_ROOT, settings.DEBUG = tmp_path, True
    try:
        importlib.reload(config.urls)
        clear_url_caches()
        from django.test import Client

        assert Client().get("/media/items/x.txt").status_code == 200
    finally:
        settings.DEBUG = False
        importlib.reload(config.urls)
        clear_url_caches()
