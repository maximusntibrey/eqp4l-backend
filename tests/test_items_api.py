"""B4.1 item API, B4.2 image upload: roles, branch-free scope, validation, workflow, FIX-1 key rules."""

import io
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from audit.models import AuditEvent
from inventory.models import Brand, Category, Item, ItemCost, ItemStatus, Subtype
from roles import constants as c
from roles.models import UserPermission
from stock_ledger.models import MovementType, SourceType
from stock_ledger.services import StockChange, post_stock_changes
from tests.api import call, client_as

ITEMS = "/api/v1/items/"
SPECS = {"processor": "Core i5", "ram_gb": 16, "storage_gb": 512, "storage_type": "NVMe SSD"}


@pytest.fixture(autouse=True)
def _media(settings: Any, tmp_path: Path) -> None:
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def brand(db: None) -> Brand:
    return Brand.objects.create(name="HP")


def body(brand: Brand, **over: Any) -> dict[str, Any]:
    category = Category.objects.get(name="Laptop")
    data: dict[str, Any] = {
        "name": "HP 250 G9 i5 16GB 512GB",
        "category_id": category.pk,
        "subtype_id": Subtype.objects.filter(category=category).first().pk,  # type: ignore[union-attr]
        "brand_id": brand.pk,
        "model_name": "250 G9",
        "mpn": "6S6D1EA",
        "condition": "new",
        "key_specs": dict(SPECS),
    }
    data.update(over)
    return data


def png(size: tuple[int, int] = (4, 4), fmt: str = "PNG") -> io.BytesIO:
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, fmt)
    buf.seek(0)
    buf.name = f"photo.{fmt.lower()}"
    return buf


def upload(client: Any, item_id: int, file: Any, *, key: str | None = None) -> Any:
    return client.put(
        f"{ITEMS}{item_id}/image/",
        {"image": file},
        format="multipart",
        HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
    )


def make_item(client: Any, brand: Brand, **over: Any) -> dict[str, Any]:
    response = call(client, "POST", ITEMS, body(brand, **over))
    assert response.status_code == 201, response.content
    return dict(response.json())


# ---- reference data ----


def test_categories_with_subtypes_and_field_definitions_for_everyone(users: dict[str, Any]) -> None:
    for key in ("sa", "wa", "ba", "fs"):
        cats = client_as(users[key]).get("/api/v1/item-categories/").json()
        assert [x["name"] for x in cats] == ["Laptop", "Laptop Part", "Accessory"]
        assert all(x["subtypes"] for x in cats)
    laptop = Category.objects.get(name="Laptop")
    defs = client_as(users["fs"]).get("/api/v1/item-field-definitions/", {"category_id": laptop.pk}).json()
    by_key = {d["key"]: d for d in defs}
    assert by_key["ram_gb"]["in_key_specs"] is True and by_key["ram_gb"]["required"] is True
    assert by_key["model_name"]["in_key_specs"] is False
    assert call(client_as(users["fs"]), "GET", "/api/v1/item-field-definitions/").status_code == 400
    assert (
        call(
            client_as(users["fs"]), "GET", "/api/v1/item-field-definitions/", {"category_id": 9999}
        ).status_code
        == 400
    )


def test_unauthenticated_requests_are_refused(api: Any) -> None:
    for url in (ITEMS, "/api/v1/costed-items/", "/api/v1/brands/", "/api/v1/item-categories/"):
        assert api.get(url).status_code == 401


# ---- create ----


@pytest.mark.parametrize("role", ["sa", "wa"])
def test_sa_and_wa_create_a_draft_with_a_generated_sku(
    users: dict[str, Any], brand: Brand, role: str
) -> None:
    created = make_item(client_as(users[role]), brand)
    assert created["status"] == "draft" and created["sku"].startswith("SKU-") and len(created["sku"]) == 10
    assert created["average_cost"] is None and created["warnings"] == [] and created["selling_price"] is None
    assert created["key_specs"] == SPECS and created["brand_name"] == "HP" and created["image_url"] is None
    second = make_item(client_as(users[role]), brand, name="Another", model_name="Other")
    assert int(second["sku"][4:]) == int(created["sku"][4:]) + 1
    event = AuditEvent.objects.get(action="item_created", target_ref=created["sku"])
    assert event.actor_id == users[role].pk and event.after_values["status"] == "draft"  # type: ignore[index]


@pytest.mark.parametrize("role", ["ba", "fs"])
def test_branch_roles_cannot_create_or_edit(users: dict[str, Any], brand: Brand, role: str) -> None:
    client = client_as(users[role])
    assert call(client, "POST", ITEMS, body(brand)).status_code == 403
    item = make_item(client_as(users["sa"]), brand)
    assert call(client, "PATCH", f"{ITEMS}{item['id']}/", {"name": "X"}).status_code == 403
    assert call(client, "POST", f"{ITEMS}{item['id']}/status/", {"status": "active"}).status_code == 403
    assert upload(client, item["id"], png()).status_code == 403
    assert call(client, "POST", "/api/v1/brands/", {"name": "Z"}).status_code == 403


def test_a_supplied_sku_is_kept_and_a_clash_is_409(users: dict[str, Any], brand: Brand) -> None:
    sa = client_as(users["sa"])
    assert make_item(sa, brand, sku="IMP-001")["sku"] == "IMP-001"
    clash = call(sa, "POST", ITEMS, body(brand, sku="imp-001"))
    assert clash.status_code == 409 and clash.json()["errors"][0]["field"] == "sku"


def test_generated_sku_skips_a_number_an_import_already_took(users: dict[str, Any], brand: Brand) -> None:
    sa = client_as(users["sa"])
    first = make_item(sa, brand)
    next_number = int(first["sku"][4:]) + 1
    make_item(sa, brand, sku=f"SKU-{next_number:06d}", name="Imported", model_name="Imp")
    assert int(make_item(sa, brand, name="Third", model_name="Th")["sku"][4:]) == next_number + 1


@pytest.mark.parametrize(
    "missing", ["name", "category_id", "subtype_id", "brand_id", "model_name", "mpn", "condition"]
)
def test_missing_required_field_is_a_validation_error(
    users: dict[str, Any], brand: Brand, missing: str
) -> None:
    data = body(brand)
    del data[missing]
    response = call(client_as(users["sa"]), "POST", ITEMS, data)
    assert response.status_code == 400
    assert response.json()["code"] == "validation_error" and response.json()["errors"][0]["field"] == missing


@pytest.mark.parametrize(
    "over, field",
    [
        ({"name": "   "}, "name"),
        ({"condition": "broken"}, "condition"),
        ({"grade": "D"}, "grade"),
        ({"category_id": 9999}, "category_id"),
        ({"subtype_id": 9999}, "subtype_id"),
        ({"brand_id": 9999}, "brand_id"),
        ({"selling_price": "-1.00"}, "selling_price"),
        ({"selling_price": "10.001"}, "selling_price"),
        ({"key_specs": {"ram_gb": "lots"}}, "key_specs.ram_gb"),
        ({"key_specs": {"ram_gb": True}}, "key_specs.ram_gb"),
        ({"key_specs": {"storage_type": "Tape"}}, "key_specs.storage_type"),
        ({"key_specs": {"colour": "x" * 201}}, "key_specs.colour"),
        ({"key_specs": {"screen_size_in": "wide"}}, "key_specs.screen_size_in"),
        ({"key_specs": {"touchscreen": "yes"}}, "key_specs.touchscreen"),
        ({"key_specs": {"made_up": 1}}, "key_specs.made_up"),
        ({"key_specs": ["ram_gb"]}, "key_specs"),
    ],
)
def test_bad_input_gets_the_standard_error(
    users: dict[str, Any], brand: Brand, over: dict[str, Any], field: str
) -> None:
    response = call(client_as(users["sa"]), "POST", ITEMS, body(brand, **over))
    assert response.status_code == 400, response.content
    assert response.json()["code"] == "validation_error"
    assert field in [e["field"] for e in response.json()["errors"]]
    assert Item.objects.count() == 0


def test_subtype_must_belong_to_the_category(users: dict[str, Any], brand: Brand) -> None:
    part = Subtype.objects.filter(category__name="Accessory").first()
    response = call(client_as(users["sa"]), "POST", ITEMS, body(brand, subtype_id=part.pk))  # type: ignore[union-attr]
    assert response.status_code == 400 and response.json()["errors"][0]["field"] == "subtype_id"


def test_key_specs_decimal_and_empty_values(users: dict[str, Any], brand: Brand) -> None:
    created = make_item(
        client_as(users["sa"]), brand, key_specs={**SPECS, "screen_size_in": 15.6, "colour": "", "os": None}
    )
    assert created["key_specs"]["screen_size_in"] == "15.6" and "colour" not in created["key_specs"]


def test_deactivated_brand_cannot_be_chosen_for_a_new_item(users: dict[str, Any], brand: Brand) -> None:
    Brand.objects.filter(pk=brand.pk).update(is_active=False)
    response = call(client_as(users["sa"]), "POST", ITEMS, body(brand))
    assert response.status_code == 400 and response.json()["errors"][0]["field"] == "brand_id"


def test_near_duplicate_name_and_model_is_a_warning_not_a_block(users: dict[str, Any], brand: Brand) -> None:
    sa = client_as(users["sa"])
    first = make_item(sa, brand)
    second = make_item(sa, brand, name="hp 250-g9 i5 16gb 512gb", model_name="250 g9")
    assert [(w["code"], w["item_id"]) for w in second["warnings"]] == [("duplicate_name_model", first["id"])]
    assert Item.objects.count() == 2


# ---- selling price (row 16, OQ-21) ----


def test_selling_price_needs_super_admin_or_manage_prices(users: dict[str, Any], brand: Brand) -> None:
    wa = client_as(users["wa"])
    denied = call(wa, "POST", ITEMS, body(brand, selling_price="3500.00"))
    assert denied.status_code == 403 and denied.json()["code"] == "permission_denied"
    assert Item.objects.count() == 0
    sa_item = make_item(client_as(users["sa"]), brand, selling_price="3500.5")
    assert sa_item["selling_price"] == "3500.50"
    wa_item = make_item(wa, brand, name="No price", model_name="NP")
    assert call(wa, "PATCH", f"{ITEMS}{wa_item['id']}/", {"selling_price": "10.00"}).status_code == 403
    UserPermission.objects.create(user=users["wa"], permission=c.MANAGE_PRICES)
    granted = call(wa, "PATCH", f"{ITEMS}{wa_item['id']}/", {"selling_price": "10.00"})
    assert granted.status_code == 200 and granted.json()["selling_price"] == "10.00"


# ---- idempotency (FIX-1) ----


def test_same_key_same_body_replays_and_creates_one_item(users: dict[str, Any], brand: Brand) -> None:
    sa = client_as(users["sa"])
    key = str(uuid.uuid4())
    first = call(sa, "POST", ITEMS, body(brand), key=key)
    again = call(sa, "POST", ITEMS, body(brand), key=key)
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    assert Item.objects.count() == 1


def test_same_key_other_body_is_409_idempotency_conflict(users: dict[str, Any], brand: Brand) -> None:
    sa = client_as(users["sa"])
    key = str(uuid.uuid4())
    call(sa, "POST", ITEMS, body(brand), key=key)
    clash = call(sa, "POST", ITEMS, body(brand, name="Different"), key=key)
    assert clash.status_code == 409 and clash.json()["code"] == "idempotency_conflict"
    assert Item.objects.count() == 1


def test_user_b_replaying_user_a_key_never_gets_a_stored_body(users: dict[str, Any], brand: Brand) -> None:
    key = str(uuid.uuid4())
    a = call(client_as(users["sa"]), "POST", ITEMS, body(brand), key=key)
    b = call(client_as(users["wa"]), "POST", ITEMS, body(brand, name="B item", model_name="B"), key=key)
    assert a.status_code == b.status_code == 201
    assert b.json()["id"] != a.json()["id"] and b.json()["name"] == "B item"
    assert Item.objects.count() == 2


def test_a_refused_request_stores_nothing_so_a_retry_runs(users: dict[str, Any], brand: Brand) -> None:
    sa, key = client_as(users["sa"]), str(uuid.uuid4())
    assert call(sa, "POST", ITEMS, body(brand, name=""), key=key).status_code == 400
    assert call(sa, "POST", ITEMS, body(brand, name=""), key=key).status_code == 400
    assert call(sa, "POST", ITEMS, body(brand), key=key).status_code == 201  # the refusals stored nothing
    assert call(sa, "POST", ITEMS, body(brand), key=False).status_code == 400  # header required


# ---- read and list ----


def test_cost_is_never_on_items_and_only_sa_wa_read_costed_items(users: dict[str, Any], brand: Brand) -> None:
    created = make_item(client_as(users["sa"]), brand)
    ItemCost.objects.create(item_id=created["id"], average_cost=Decimal("2800.1250"))
    for key in ("sa", "wa", "ba", "fs"):
        client = client_as(users[key])
        row = client.get(f"{ITEMS}{created['id']}/").json()
        listed = client.get(ITEMS).json()["results"][0]
        assert "average_cost" not in row and "average_cost" not in listed and "warnings" not in row
    for key in ("sa", "wa"):
        client = client_as(users[key])
        assert client.get(f"/api/v1/costed-items/{created['id']}/").json()["average_cost"] == "2800.13"
        assert client.get("/api/v1/costed-items/").json()["results"][0]["average_cost"] == "2800.13"
    for key in ("ba", "fs"):
        client = client_as(users[key])
        assert client.get("/api/v1/costed-items/").status_code == 403
        assert client.get(f"/api/v1/costed-items/{created['id']}/").status_code == 403


def test_list_search_filters_and_pagination(users: dict[str, Any], brand: Brand) -> None:
    sa = client_as(users["sa"])
    dell = Brand.objects.create(name="Dell")
    part = Category.objects.get(name="Laptop Part")
    a = make_item(sa, brand)
    b = make_item(sa, dell, name="Dell Latitude", model_name="5420", mpn="DL5420")
    make_item(
        sa,
        brand,
        name="Battery",
        mpn="BAT1",
        category_id=part.pk,
        subtype_id=Subtype.objects.filter(category=part).first().pk,  # type: ignore[union-attr]
        key_specs={},
    )
    Item.objects.filter(pk=a["id"]).update(status=ItemStatus.ACTIVE)
    ba = client_as(users["ba"])

    def ids(**params: Any) -> list[int]:
        return [r["id"] for r in ba.get(ITEMS, params).json()["results"]]

    assert len(ids()) == 3
    assert ids(q="dell") == [b["id"]]  # name or brand
    assert ids(q="DL5420") == [b["id"]] and ids(q=a["sku"]) == [a["id"]] and ids(q="6S6D1EA") == [a["id"]]
    assert ids(status="active") == [a["id"]] and len(ids(status="draft")) == 2
    assert ids(brand_id=dell.pk) == [b["id"]] and len(ids(category_id=part.pk)) == 1
    page = ba.get(ITEMS, {"page_size": 2}).json()
    assert page["count"] == 3 and len(page["results"]) == 2 and page["next"]
    assert ba.get(ITEMS, {"status": "bogus"}).status_code == 400
    assert ba.get(f"{ITEMS}99999/").status_code == 404


# ---- edit ----


def test_edit_audits_before_and_after_and_validates(users: dict[str, Any], brand: Brand) -> None:
    sa = client_as(users["wa"])
    created = make_item(sa, brand)
    url = f"{ITEMS}{created['id']}/"
    changed = call(sa, "PATCH", url, {"name": "Renamed", "description": "Nice", "key_specs": {"ram_gb": 32}})
    assert changed.status_code == 200 and changed.json()["name"] == "Renamed"
    assert changed.json()["key_specs"] == {"ram_gb": 32} and "warnings" in changed.json()
    event = AuditEvent.objects.get(action="item_updated", target_ref=created["sku"])
    assert event.before_values["name"] != "Renamed" and event.after_values["name"] == "Renamed"  # type: ignore[index]
    assert call(sa, "PATCH", url, {"key_specs": {"ram_gb": "x"}}).status_code == 400
    assert call(sa, "PATCH", f"{ITEMS}99999/", {"name": "X"}).status_code == 404
    other = Category.objects.get(name="Accessory")
    moved = call(sa, "PATCH", url, {"category_id": other.pk})  # sub-type no longer matches
    assert moved.status_code == 400 and moved.json()["errors"][0]["field"] == "subtype_id"
    ok = call(
        sa,
        "PATCH",
        url,
        {"category_id": other.pk, "subtype_id": Subtype.objects.filter(category=other).first().pk},  # type: ignore[union-attr]
    )
    assert (
        ok.status_code == 200 and ok.json()["key_specs"] == {}
    )  # the old category's specs do not carry over


def test_an_existing_inactive_brand_stays_but_cannot_be_newly_chosen(
    users: dict[str, Any], brand: Brand
) -> None:
    wa = client_as(users["wa"])
    created = make_item(wa, brand)
    other = Brand.objects.create(name="Other", is_active=False)
    Brand.objects.filter(pk=brand.pk).update(is_active=False)
    url = f"{ITEMS}{created['id']}/"
    assert call(wa, "PATCH", url, {"brand_id": brand.pk, "name": "Same brand"}).status_code == 200
    assert call(wa, "PATCH", url, {"brand_id": other.pk}).status_code == 400


def test_sku_is_immutable_once_used_in_a_transaction(
    users: dict[str, Any], brand: Brand, locations: dict[str, Any]
) -> None:
    wa = client_as(users["wa"])
    created = make_item(wa, brand)
    url = f"{ITEMS}{created['id']}/"
    assert call(wa, "PATCH", url, {"sku": "NEW-1"}).json()["sku"] == "NEW-1"  # unused: may change
    item = Item.objects.get(pk=created["id"])
    post_stock_changes(
        [
            StockChange(
                locations["wh"], item, "on_hand", 3, MovementType.OPENING_BALANCE, SourceType.CSV_IMPORT, 1, 1
            )
        ],
        actor=None,
    )
    refused = call(wa, "PATCH", url, {"sku": "NEW-2"})
    assert refused.status_code == 400 and refused.json()["errors"][0]["field"] == "sku"
    assert call(wa, "PATCH", url, {"sku": "NEW-1", "name": "Same SKU ok"}).status_code == 200


def test_discontinued_items_cannot_be_edited(users: dict[str, Any], brand: Brand) -> None:
    wa = client_as(users["wa"])
    created = make_item(wa, brand)
    Item.objects.filter(pk=created["id"]).update(status=ItemStatus.DISCONTINUED)
    assert call(wa, "PATCH", f"{ITEMS}{created['id']}/", {"name": "X"}).status_code == 409
    assert upload(wa, created["id"], png()).status_code == 409


# ---- status workflow ----


def test_activation_needs_the_image_and_required_specs_then_discontinue_is_final(
    users: dict[str, Any], brand: Brand
) -> None:
    wa = client_as(users["wa"])
    created = make_item(wa, brand, key_specs={"processor": "Core i5"})
    url = f"{ITEMS}{created['id']}/status/"
    refused = call(wa, "POST", url, {"status": "active"})
    fields = {e["field"] for e in refused.json()["errors"]}
    assert refused.status_code == 400 and fields == {
        "image",
        "key_specs.ram_gb",
        "key_specs.storage_gb",
        "key_specs.storage_type",
    }
    call(wa, "PATCH", f"{ITEMS}{created['id']}/", {"key_specs": SPECS})
    assert upload(wa, created["id"], png()).status_code == 200
    active = call(wa, "POST", url, {"status": "active"})
    assert (
        active.status_code == 200 and active.json()["status"] == "active" and "average_cost" in active.json()
    )
    assert call(wa, "POST", url, {"status": "active"}).status_code == 409  # not a move
    done = call(wa, "POST", url, {"status": "discontinued"})
    assert done.status_code == 200 and done.json()["status"] == "discontinued"
    assert call(wa, "POST", url, {"status": "active"}).status_code == 409  # final
    assert call(wa, "POST", url, {"status": "draft"}).status_code == 400
    assert AuditEvent.objects.filter(action="item_status_changed", target_ref=created["sku"]).count() == 2


def test_a_draft_cannot_jump_to_discontinued_and_activation_needs_no_price(
    users: dict[str, Any], brand: Brand
) -> None:
    wa = client_as(users["wa"])
    created = make_item(wa, brand)
    assert call(wa, "POST", f"{ITEMS}{created['id']}/status/", {"status": "discontinued"}).status_code == 409
    upload(wa, created["id"], png())
    ok = call(wa, "POST", f"{ITEMS}{created['id']}/status/", {"status": "active"})
    assert ok.status_code == 200 and ok.json()["selling_price"] is None
    assert call(wa, "POST", f"{ITEMS}99999/status/", {"status": "active"}).status_code == 404


# ---- image (B4.2) ----


@pytest.mark.parametrize("fmt, ext", [("PNG", "png"), ("JPEG", "jpg"), ("WEBP", "webp")])
def test_allowed_image_types_are_stored_under_a_server_name(
    users: dict[str, Any], brand: Brand, settings: Any, fmt: str, ext: str
) -> None:
    wa = client_as(users["wa"])
    created = make_item(wa, brand)
    file = png(fmt=fmt)
    file.name = "../../evil name.exe"  # the client's name is never used
    response = upload(wa, created["id"], file)
    assert response.status_code == 200
    url = response.json()["image_url"]
    assert url.startswith("/media/items/") and url.endswith(f".{ext}") and "evil" not in url
    assert (Path(settings.MEDIA_ROOT) / url.removeprefix("/media/")).is_file()
    assert client_as(users["fs"]).get(f"{ITEMS}{created['id']}/").json()["image_url"] == url
    assert AuditEvent.objects.filter(action="item_image_set", target_ref=created["sku"]).exists()


def test_a_second_upload_replaces_the_image(users: dict[str, Any], brand: Brand) -> None:
    wa = client_as(users["wa"])
    created = make_item(wa, brand)
    first = upload(wa, created["id"], png()).json()["image_url"]
    second = upload(wa, created["id"], png((8, 8))).json()["image_url"]
    assert first != second


def test_wrong_content_is_refused_whatever_the_extension(users: dict[str, Any], brand: Brand) -> None:
    wa = client_as(users["wa"])
    created = make_item(wa, brand)
    fake = io.BytesIO(b"<?php echo 1; ?>")
    fake.name = "photo.png"
    assert upload(wa, created["id"], fake).status_code == 400
    gif = png(fmt="GIF")
    assert upload(wa, created["id"], gif).status_code == 400
    truncated = png()
    truncated = io.BytesIO(truncated.getvalue()[:20])
    truncated.name = "cut.png"
    response = upload(wa, created["id"], truncated)
    assert response.status_code == 400 and response.json()["errors"][0]["field"] == "image"
    assert Item.objects.get(pk=created["id"]).image == ""


def test_image_over_5mb_is_413_and_exactly_5mb_is_accepted(users: dict[str, Any], brand: Brand) -> None:
    wa = client_as(users["wa"])
    created = make_item(wa, brand)
    big = png()
    big.seek(0, io.SEEK_END)
    big.write(b"\0" * (5 * 1024 * 1024 + 1 - big.tell()))  # trailing padding keeps it a valid PNG
    big.seek(0)
    big.name = "big.png"
    response = upload(wa, created["id"], big)
    assert response.status_code == 413 and response.json()["code"] == "file_too_large"
    exact = png()
    exact.seek(0, io.SEEK_END)
    exact.write(b"\0" * (5 * 1024 * 1024 - exact.tell()))
    exact.seek(0)
    exact.name = "exact.png"
    assert upload(wa, created["id"], exact).status_code == 200


def test_upload_without_a_file_or_for_a_missing_item(users: dict[str, Any], brand: Brand) -> None:
    wa = client_as(users["wa"])
    created = make_item(wa, brand)
    empty = wa.put(
        f"{ITEMS}{created['id']}/image/", {}, format="multipart", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())
    )
    assert empty.status_code == 400
    assert upload(wa, 99999, png()).status_code == 404


# ---- brands ----


def test_brand_add_rename_deactivate_reactivate(users: dict[str, Any]) -> None:
    wa = client_as(users["wa"])
    created = call(wa, "POST", "/api/v1/brands/", {"name": "Acer"})
    assert created.status_code == 201 and created.json()["is_active"] is True
    brand_id = created.json()["id"]
    assert call(wa, "POST", "/api/v1/brands/", {"name": "acer"}).status_code == 400  # unique, any case
    assert call(wa, "POST", "/api/v1/brands/", {}).status_code == 400
    assert call(wa, "PATCH", f"/api/v1/brands/{brand_id}/", {"name": "Acer Inc"}).json()["name"] == "Acer Inc"
    assert call(wa, "PATCH", f"/api/v1/brands/{brand_id}/", {"is_active": False}).json()["is_active"] is False
    assert call(wa, "PATCH", f"/api/v1/brands/{brand_id}/", {"is_active": True}).json()["is_active"] is True
    assert call(wa, "PATCH", f"/api/v1/brands/{brand_id}/", {}).status_code == 400
    Brand.objects.create(name="Taken")
    assert call(wa, "PATCH", f"/api/v1/brands/{brand_id}/", {"name": "taken"}).status_code == 400
    assert call(wa, "PATCH", "/api/v1/brands/99999/", {"name": "Q"}).status_code == 404
    names = [b["name"] for b in client_as(users["fs"]).get("/api/v1/brands/").json()]
    assert "Acer Inc" in names
    assert AuditEvent.objects.filter(action="brand_created").count() == 1
    assert AuditEvent.objects.filter(action="brand_updated").count() == 3


def test_condition_filter_and_patch_key_specs_replaces_the_object(
    users: dict[str, Any], brand: Brand
) -> None:
    wa = client_as(users["wa"])
    new = make_item(wa, brand)
    used = make_item(wa, brand, name="Used one", model_name="U1", condition="used")
    for path in (ITEMS, "/api/v1/costed-items/"):
        ids = [r["id"] for r in wa.get(path, {"condition": "used"}).json()["results"]]
        assert ids == [used["id"]] and new["id"] not in ids
        assert wa.get(path, {"condition": "broken"}).status_code == 400
    url = f"{ITEMS}{new['id']}/"
    assert call(wa, "PATCH", url, {"key_specs": {"ram_gb": 8}}).json()["key_specs"] == {
        "ram_gb": 8
    }  # not merged
    assert call(wa, "PATCH", url, {"name": "Only name"}).json()["key_specs"] == {"ram_gb": 8}  # omitted: kept


def test_me_exposes_the_set_price_permission(users: dict[str, Any]) -> None:
    def perms(key: str) -> list[str]:
        return client_as(users[key]).get("/api/v1/auth/me/").json()["permissions"]

    assert "prices.manage" in perms("sa") and "prices.manage" not in perms("wa")
    UserPermission.objects.create(user=users["wa"], permission=c.MANAGE_PRICES)
    assert "prices.manage" in perms("wa")


# ---- end-of-day review fixes (FIX-38, FIX-40)


def test_same_key_and_file_name_but_different_image_bytes_is_409(users: dict[str, Any], brand: Brand) -> None:
    wa = client_as(users["wa"])
    created = make_item(wa, brand)
    key = str(uuid.uuid4())
    assert upload(wa, created["id"], png((4, 4)), key=key).status_code == 200
    again = upload(wa, created["id"], png((4, 4)), key=key)  # identical bytes: a replay
    assert again.status_code == 200
    other = upload(wa, created["id"], png((9, 9)), key=key)  # same name, other bytes
    assert other.status_code == 409 and other.json()["code"] == "idempotency_conflict"


def test_a_failed_upload_leaves_no_file_behind(
    users: dict[str, Any], brand: Brand, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inventory import services

    wa = client_as(users["wa"])
    created = make_item(wa, brand)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit down")

    monkeypatch.setattr(services, "_audit", boom)
    wa.raise_request_exception = False
    assert upload(wa, created["id"], png()).status_code == 500
    assert list(Path(settings.MEDIA_ROOT).rglob("*.png")) == []
    assert Item.objects.get(pk=created["id"]).image == ""
