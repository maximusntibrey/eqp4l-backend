"""Every operation in docs/api/openapi.yaml, for every role: permitted -> 2xx, refused -> 403, never a 5xx.

Also: every write needs a valid Idempotency-Key (400 without or with a malformed one, same key replays),
and the CORS preflight a browser sends for every write path is answered 200 with the headers allowed.
The expected role sets below are written from docs/design/PERMISSION_TABLE.md, not read from the code.
"""

import io
import re
import uuid
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from inventory.models import Brand, Category, Item, ItemPrice, ItemStatus
from tests.api import client_as
from tests.test_b6_sales import stock
from tests.test_items_api import body as item_body

SPEC = yaml.safe_load((Path(__file__).resolve().parent.parent / "docs/api/openapi.yaml").read_text("utf-8"))
WRITE = {"post", "put", "patch", "delete"}
SA, WA, BA, FS, CW = "sa", "wa", "ba", "fs", "cw"
EVERYONE = {"sa", "wa", "ba", "fs", "cw"}
NO_KEY = {
    ("POST", "/api/v1/auth/login/"),
    ("POST", "/api/v1/auth/logout/"),
    ("POST", "/api/v1/auth/password/"),
}
pytestmark = pytest.mark.django_db

Built = tuple[str, Any, str]  # url, body (dict or query for GET), format: json | multipart


def png() -> SimpleUploadedFile:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, "PNG")
    return SimpleUploadedFile("photo.png", buf.getvalue(), content_type="image/png")


def csv_upload(w: dict[str, Any]) -> dict[str, Any]:
    header = "sku,name,category,subtype,brand,model_name,mpn,condition,opening_quantity,unit_cost"
    text = f"{header}\n,Matrix Laptop,Laptop,Business,HP,M1,MPN-M1,new,3,100.00\n"
    return {"file": SimpleUploadedFile("s.csv", text.encode()), "dry_run": "true", "location_id": w["wh"].pk}


def _inactive_branch(w: dict[str, Any]) -> str:
    """Activate needs an inactive branch."""
    type(w["b"]).objects.filter(pk=w["b"].pk).update(is_active=False)
    return f"/api/v1/branches/{w['b'].pk}/activate/"


# (method, path template) -> (roles that may do it, builder(w, role) -> (url, body, format))
def u(path: str, **ids: Any) -> str:
    return path.format(**ids)


OPS: dict[tuple[str, str], tuple[set[str], Callable[[dict[str, Any], str], Built]]] = {
    ("GET", "/health/"): (EVERYONE, lambda w, r: ("/health/", None, "json")),
    ("GET", "/api/v1/auth/csrf/"): (EVERYONE, lambda w, r: ("/api/v1/auth/csrf/", None, "json")),
    ("POST", "/api/v1/auth/login/"): (EVERYONE, lambda w, r: ("/api/v1/auth/login/", {}, "json")),  # own test
    ("POST", "/api/v1/auth/logout/"): (EVERYONE, lambda w, r: ("/api/v1/auth/logout/", {}, "json")),
    ("GET", "/api/v1/auth/me/"): (EVERYONE, lambda w, r: ("/api/v1/auth/me/", None, "json")),
    ("POST", "/api/v1/auth/password/"): (
        EVERYONE,
        lambda w, r: (
            "/api/v1/auth/password/",
            {"current_password": w["password"], "new_password": "n" * 12},
            "json",
        ),
    ),
    ("GET", "/api/v1/working-branch/"): ({SA, FS}, lambda w, r: ("/api/v1/working-branch/", None, "json")),
    ("PUT", "/api/v1/working-branch/"): (
        {SA, FS},
        lambda w, r: ("/api/v1/working-branch/", {"branch_id": w["a"].pk}, "json"),
    ),
    ("GET", "/api/v1/branches/"): (EVERYONE, lambda w, r: ("/api/v1/branches/", None, "json")),
    ("POST", "/api/v1/branches/"): (
        {SA},
        lambda w, r: (
            "/api/v1/branches/",
            {"code": "NEW", "name": "New Branch", "branch_type": "branch"},
            "json",
        ),
    ),
    ("GET", "/api/v1/branches/{id}/"): (
        EVERYONE,
        lambda w, r: (f"/api/v1/branches/{w['b'].pk}/", None, "json"),
    ),
    ("PATCH", "/api/v1/branches/{id}/"): (
        {SA},
        lambda w, r: (f"/api/v1/branches/{w['b'].pk}/", {"name": "Renamed B"}, "json"),
    ),
    ("POST", "/api/v1/branches/{id}/deactivate/"): (
        {SA},
        lambda w, r: (f"/api/v1/branches/{w['b'].pk}/deactivate/", {}, "json"),
    ),
    ("POST", "/api/v1/branches/{id}/activate/"): (
        {SA},
        lambda w, r: (_inactive_branch(w), {}, "json"),
    ),
    ("GET", "/api/v1/users/"): ({SA, WA, BA}, lambda w, r: ("/api/v1/users/", None, "json")),
    ("POST", "/api/v1/users/"): (
        {SA},
        lambda w, r: (
            "/api/v1/users/",
            {"full_name": "Matrix Person", "roles": ["central_warehouse"]},
            "json",
        ),
    ),
    ("GET", "/api/v1/users/{id}/"): (
        {SA, WA, BA},
        lambda w, r: (
            f"/api/v1/users/{w['users'][r].pk}/",
            None,
            "json",
        ),  # their own record is in their scope
    ),
    ("PATCH", "/api/v1/users/{id}/"): (
        {SA},
        lambda w, r: (f"/api/v1/users/{w['target'].pk}/", {"full_name": "Renamed Person"}, "json"),
    ),
    ("POST", "/api/v1/users/{id}/reset-password/"): (
        {SA},
        lambda w, r: (f"/api/v1/users/{w['target'].pk}/reset-password/", {}, "json"),
    ),
    ("POST", "/api/v1/users/{id}/status/"): (
        {SA},
        lambda w, r: (f"/api/v1/users/{w['target'].pk}/status/", {"status": "suspended"}, "json"),
    ),
    ("GET", "/api/v1/users/{id}/permissions/"): (
        {SA},
        lambda w, r: (f"/api/v1/users/{w['target'].pk}/permissions/", None, "json"),
    ),
    ("PUT", "/api/v1/users/{id}/permissions/"): (
        {SA},
        lambda w, r: (
            f"/api/v1/users/{w['target'].pk}/permissions/",
            {"permissions": ["manage_prices"]},
            "json",
        ),
    ),
    ("GET", "/api/v1/dashboard/"): ({SA, WA, BA}, lambda w, r: ("/api/v1/dashboard/", None, "json")),
    ("GET", "/api/v1/item-categories/"): (EVERYONE, lambda w, r: ("/api/v1/item-categories/", None, "json")),
    ("GET", "/api/v1/brands/"): (EVERYONE, lambda w, r: ("/api/v1/brands/", None, "json")),
    ("POST", "/api/v1/brands/"): ({SA, WA}, lambda w, r: ("/api/v1/brands/", {"name": "Acer"}, "json")),
    ("PATCH", "/api/v1/brands/{id}/"): (
        {SA, WA},
        lambda w, r: (f"/api/v1/brands/{w['brand'].pk}/", {"name": "HP Inc"}, "json"),
    ),
    ("GET", "/api/v1/item-field-definitions/"): (
        EVERYONE,
        lambda w, r: ("/api/v1/item-field-definitions/", {"category_id": w["item"].category_id}, "json"),
    ),
    ("GET", "/api/v1/items/"): (EVERYONE, lambda w, r: ("/api/v1/items/", None, "json")),
    ("POST", "/api/v1/items/"): (
        {SA, WA},
        lambda w, r: ("/api/v1/items/", item_body(w["brand"], name="Matrix New Laptop"), "json"),
    ),
    ("GET", "/api/v1/costed-items/"): ({SA, WA}, lambda w, r: ("/api/v1/costed-items/", None, "json")),
    ("GET", "/api/v1/costed-items/{id}/"): (
        {SA, WA},
        lambda w, r: (f"/api/v1/costed-items/{w['item'].pk}/", None, "json"),
    ),
    ("GET", "/api/v1/items/{id}/"): (EVERYONE, lambda w, r: (f"/api/v1/items/{w['item'].pk}/", None, "json")),
    ("PATCH", "/api/v1/items/{id}/"): (
        {SA, WA},
        lambda w, r: (f"/api/v1/items/{w['item'].pk}/", {"model_name": "Changed"}, "json"),
    ),
    ("POST", "/api/v1/items/{id}/status/"): (
        {SA, WA},
        lambda w, r: (f"/api/v1/items/{w['item'].pk}/status/", {"status": "discontinued"}, "json"),
    ),
    ("PUT", "/api/v1/items/{id}/image/"): (
        {SA, WA},
        lambda w, r: (f"/api/v1/items/{w['item'].pk}/image/", {"image": png()}, "multipart"),
    ),
    ("GET", "/api/v1/items/{id}/branch-availability/"): (
        EVERYONE,
        lambda w, r: (f"/api/v1/items/{w['item'].pk}/branch-availability/", None, "json"),
    ),
    ("GET", "/api/v1/stock/"): (EVERYONE, lambda w, r: ("/api/v1/stock/", None, "json")),
    ("GET", "/api/v1/stock/movements/"): (EVERYONE, lambda w, r: ("/api/v1/stock/movements/", None, "json")),
    ("GET", "/api/v1/costed-stock/"): ({SA, WA}, lambda w, r: ("/api/v1/costed-stock/", None, "json")),
    ("GET", "/api/v1/goods-receipts/"): (
        {SA, WA, CW},
        lambda w, r: ("/api/v1/goods-receipts/", None, "json"),
    ),
    ("POST", "/api/v1/goods-receipts/"): (
        {SA, WA},
        lambda w, r: (
            "/api/v1/goods-receipts/",
            {
                "warehouse_id": w["wh"].pk,
                "supplier_name": "Acme",
                "lines": [{"item_id": w["item"].pk, "quantity": 1, "unit_cost": "10.00"}],
            },
            "json",
        ),
    ),
    ("GET", "/api/v1/goods-receipts/{id}/"): (
        {SA, WA, CW},
        lambda w, r: (f"/api/v1/goods-receipts/{w['grn']}/", None, "json"),
    ),
    ("GET", "/api/v1/dispatches/"): (EVERYONE, lambda w, r: ("/api/v1/dispatches/", None, "json")),
    ("POST", "/api/v1/dispatches/"): (
        {SA, WA},
        lambda w, r: (
            "/api/v1/dispatches/",
            {
                "warehouse_id": w["wh"].pk,
                "destination_id": w["a"].pk,
                "lines": [{"item_id": w["item"].pk, "quantity": 1}],
            },
            "json",
        ),
    ),
    ("GET", "/api/v1/dispatches/waiting/"): (
        {SA, BA, FS},
        lambda w, r: ("/api/v1/dispatches/waiting/", {"branch_id": w["a"].pk} if r == SA else None, "json"),
    ),
    ("GET", "/api/v1/dispatches/{id}/"): (
        EVERYONE,
        lambda w, r: (f"/api/v1/dispatches/{w['d1']}/", None, "json"),
    ),
    ("POST", "/api/v1/dispatches/{id}/receive/"): (
        {SA, BA},  # FS only holds this with the Receive stock grant (own test)
        lambda w, r: (
            f"/api/v1/dispatches/{w['d1']}/receive/",
            {
                "decision": "approve_all",
                "lines": [{"line_id": w["d1_line"], "qty_received": 2, "qty_accepted": 2}],
            },
            "json",
        ),
    ),
    ("GET", "/api/v1/shortfalls/"): ({SA, WA, BA}, lambda w, r: ("/api/v1/shortfalls/", None, "json")),
    ("POST", "/api/v1/shortfalls/{id}/resolve/"): (
        {SA, WA, BA},
        lambda w, r: (
            f"/api/v1/shortfalls/{w['short_line']}/resolve/",
            {"resolution": "return_to_sender", "quantity": 1, "note": "Back to the warehouse"},
            "json",
        ),
    ),
    ("GET", "/api/v1/activity-log/"): ({SA, WA, BA}, lambda w, r: ("/api/v1/activity-log/", None, "json")),
    ("GET", "/api/v1/activity-log/export/"): (
        {SA, WA, BA},
        lambda w, r: ("/api/v1/activity-log/export/", None, "json"),
    ),
    ("GET", "/api/v1/sales/"): ({SA, BA, FS}, lambda w, r: ("/api/v1/sales/", None, "json")),
    ("POST", "/api/v1/sales/"): (
        {SA, BA, FS},
        lambda w, r: (
            "/api/v1/sales/",
            {"payment_method": "cash", "lines": [{"item_id": w["item"].pk, "quantity": 1}]},
            "json",
        ),
    ),
    ("GET", "/api/v1/sales/{id}/"): (
        {SA, BA, FS},
        lambda w, r: (f"/api/v1/sales/{w['sale']}/", None, "json"),
    ),
    ("POST", "/api/v1/sales/{id}/cancel/"): (
        {SA, BA},
        lambda w, r: (f"/api/v1/sales/{w['sale']}/cancel/", {"reason": "Customer changed mind"}, "json"),
    ),
    ("GET", "/api/v1/costed-sales/"): ({SA}, lambda w, r: ("/api/v1/costed-sales/", None, "json")),
    ("GET", "/api/v1/costed-sales/{id}/"): (
        {SA},
        lambda w, r: (f"/api/v1/costed-sales/{w['sale']}/", None, "json"),
    ),
    ("POST", "/api/v1/item-imports/"): (
        {SA, WA},
        lambda w, r: ("/api/v1/item-imports/", csv_upload(w), "multipart"),
    ),
}
# login is exercised by its own test (it needs the user's login id, and cannot be run while logged in)
LOGIN = ("POST", "/api/v1/auth/login/")
ROLES = ["sa", "wa", "ba", "fs", "cw"]


@pytest.fixture(autouse=True)
def _media(settings: Any, tmp_path: Path) -> None:
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def w(users: dict[str, Any], locations: dict[str, Any], make_user: Callable[..., Any]) -> dict[str, Any]:
    """One world: an Active item with stock and a price, a receipt, an in-transit dispatch, a short dispatch
    with an open shortfall, one completed sale at branch A, and a user to administer."""
    from tests.conftest import PASSWORD

    brand = Brand.objects.create(name="HP")
    item = Item.objects.create(
        sku="SKU-MX",
        name="Matrix item",
        category=Category.objects.get(name="Laptop"),
        brand=brand,
        status=ItemStatus.ACTIVE,
    )
    ItemPrice.objects.create(item=item, selling_price=Decimal("3500.00"))
    wh, a = locations["wh"], locations["a"]
    sa = client_as(users["sa"])
    assert (
        sa.put(
            "/api/v1/working-branch/",
            {"branch_id": a.pk},
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        ).status_code
        == 200
    )

    def post(url: str, data: dict[str, Any]) -> dict[str, Any]:
        response = sa.post(url, data, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        assert response.status_code in (200, 201), (url, response.content)
        return dict(response.json())

    grn = post(
        "/api/v1/goods-receipts/",
        {"supplier_name": "Acme", "lines": [{"item_id": item.pk, "quantity": 20, "unit_cost": "10.00"}]},
    )
    stock(a, item, 10)
    lines = [{"item_id": item.pk, "quantity": 2}]
    d1 = post("/api/v1/dispatches/", {"destination_id": a.pk, "lines": lines})
    d2 = post("/api/v1/dispatches/", {"destination_id": a.pk, "lines": lines})
    done = post(
        f"/api/v1/dispatches/{d2['id']}/receive/",
        {
            "decision": "approve_partial",
            "note": "One missing",
            "lines": [{"line_id": d2["lines"][0]["id"], "qty_received": 1, "qty_accepted": 1}],
        },
    )
    sale = post("/api/v1/sales/", {"payment_method": "cash", "lines": [{"item_id": item.pk, "quantity": 1}]})
    return {
        "brand": brand,
        "item": item,
        "wh": wh,
        "a": a,
        "b": locations["b"],
        "users": users,
        "target": make_user("front_staff"),
        "grn": grn["id"],
        "d1": d1["id"],
        "d1_line": d1["lines"][0]["id"],
        "short_line": done["lines"][0]["id"],
        "sale": sale["id"],
        "password": PASSWORD,
    }


def client_for(role: str, w: dict[str, Any]) -> APIClient:
    client = client_as(w["users"][role])
    if role in (SA, FS):  # Front Staff must pick a branch; SA picks one so sales and waiting have a context
        r = client.put(
            "/api/v1/working-branch/",
            {"branch_id": w["a"].pk},
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        assert r.status_code == 200, r.content
    return client


def send(client: APIClient, method: str, built: Built, key: str | bool | None = True) -> Any:
    url, payload, fmt = built
    if method == "GET":
        return client.get(url, payload)
    extra = {} if key is False else {"HTTP_IDEMPOTENCY_KEY": str(uuid.uuid4()) if key is True else str(key)}
    return getattr(client, method.lower())(url, payload, format=fmt, **extra)


def test_the_table_covers_every_operation_in_the_contract() -> None:
    spec_ops = {(m.upper(), p) for p, item in SPEC["paths"].items() for m in item if m in WRITE | {"get"}}
    assert spec_ops == set(OPS)


CASES = [(op, role) for op in OPS if op != LOGIN for role in ROLES]


@pytest.mark.parametrize(("op", "role"), CASES, ids=[f"{m} {p} {r}" for (m, p), r in CASES])
def test_operation_per_role(op: tuple[str, str], role: str, w: dict[str, Any]) -> None:
    allowed, build = OPS[op]
    client = client_for(role, w)
    response = send(client, op[0], build(w, role))
    assert response.status_code < 500, (op, role, response.content)
    if role in allowed:
        assert 200 <= response.status_code < 300, (op, role, response.status_code, response.content)
    else:
        assert response.status_code == 403, (op, role, response.status_code, response.content)
        assert response.json()["code"] in ("permission_denied", "wrong_branch")
    anonymous = send(APIClient(), op[0], build(w, role), key=True)
    if op[1] not in ("/health/", "/api/v1/auth/csrf/"):
        assert anonymous.status_code in (401, 403), (op, anonymous.status_code)  # CSRF refusal is also a 403


def test_public_operations_work_without_logging_in() -> None:
    assert APIClient().get("/health/").status_code == 200
    assert APIClient().get("/api/v1/auth/csrf/").status_code == 200


@pytest.mark.parametrize("role", ROLES)
def test_login_for_every_role(role: str, w: dict[str, Any]) -> None:
    client = APIClient()
    token = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
    user = w["users"][role]
    ok = client.post(
        "/api/v1/auth/login/",
        {"login_id": user.login_id, "password": w["password"]},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert ok.status_code == 200 and ok.json()["user"]["login_id"] == user.login_id
    bad = APIClient().post(
        "/api/v1/auth/login/", {"login_id": user.login_id, "password": "wrong-password-1"}, format="json"
    )
    assert 400 <= bad.status_code < 500


WRITES = [
    (op, built) for op, built in OPS.items() if op[0] in {m.upper() for m in WRITE} and op not in NO_KEY
]


@pytest.mark.parametrize(("op", "spec"), WRITES, ids=[f"{m} {p}" for (m, p), _ in WRITES])
def test_every_write_needs_a_valid_idempotency_key(op: tuple[str, str], spec: Any, w: dict[str, Any]) -> None:
    allowed, build = spec
    role = sorted(allowed)[0]
    client = client_for(role, w)
    for key in (False, "not-a-uuid", ""):
        response = send(client, op[0], build(w, role), key=key)
        assert response.status_code == 400, (op, key, response.status_code, response.content)
        assert response.json()["code"] in (
            "validation_error",
            "idempotency_key_required",
            "bad_idempotency_key",
        ) or ("Idempotency" in str(response.json()))
    first = send(client, op[0], build(w, role), key="11111111-1111-4111-8111-111111111111")
    assert 200 <= first.status_code < 300, (op, first.status_code, first.content)
    again = send(client, op[0], build(w, role), key="11111111-1111-4111-8111-111111111111")
    assert again.status_code < 500  # a replay never crashes (the stored answer, or a documented 4xx)


@pytest.mark.parametrize(("op", "spec"), WRITES, ids=[f"{m} {p}" for (m, p), _ in WRITES])
def test_cors_preflight_for_every_write_path(op: tuple[str, str], spec: Any, settings: Any) -> None:
    origin = "http://localhost:5173"
    settings.CORS_ALLOWED_ORIGINS = [origin]
    path = re.sub(r"\{id\}", "1", op[1])
    response = APIClient().options(
        path,
        HTTP_ORIGIN=origin,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD=op[0],
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,x-csrftoken,idempotency-key",
    )
    assert response.status_code == 200, (op, response.status_code)
    allowed = {h.strip() for h in response["Access-Control-Allow-Headers"].lower().split(",")}
    assert {"content-type", "x-csrftoken", "idempotency-key"} <= allowed
    assert response["Access-Control-Allow-Origin"] == origin
    assert response["Access-Control-Allow-Credentials"] == "true"
    assert op[0] in response["Access-Control-Allow-Methods"]


def test_front_staff_with_the_receive_stock_grant_can_receive(w: dict[str, Any]) -> None:
    from roles.models import UserPermission

    UserPermission.objects.create(
        user=w["users"]["fs"], permission="receive_stock", granted_by=w["users"]["sa"]
    )
    client = client_for("fs", w)
    built = OPS[("POST", "/api/v1/dispatches/{id}/receive/")][1](w, "fs")
    assert send(client, "POST", built).status_code == 200


# ---- real responses against the published schemas (seed data included: nulls, empty lists) ----------


def _inline(node: Any) -> Any:
    """Resolve $refs in place and turn OpenAPI 3.0 `nullable` into a JSON Schema union."""
    if isinstance(node, list):
        return [_inline(n) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        target: Any = SPEC
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return _inline(target)
    out = {k: _inline(v) for k, v in node.items() if k != "nullable"}
    if node.get("nullable"):
        out = {"anyOf": [out, {"type": "null"}]}
    return out


@pytest.fixture
def seeded(settings: Any) -> None:
    from django.core.management import call_command

    settings.DEBUG = True
    settings.DEV_SEED_PASSWORDS = {
        "SA": "seed-pass-sa-1",
        "WA": "seed-pass-wa-1",
        "BA": "seed-pass-ba-1",
        "FS": "seed-pass-fs-1",
    }
    call_command("seed_dev", stdout=io.StringIO())


GETS = [(op, role) for (op, (allowed, _)) in OPS.items() if op[0] == "GET" for role in sorted(allowed)]


@pytest.mark.parametrize(("op", "role"), GETS, ids=[f"{m} {p} {r}" for (m, p), r in GETS])
def test_get_responses_match_the_published_schema(
    op: tuple[str, str], role: str, w: dict[str, Any], seeded: None
) -> None:
    import jsonschema  # type: ignore[import-untyped]

    content = SPEC["paths"][op[1]]["get"]["responses"]["200"].get("content", {})
    if "application/json" not in content:
        pytest.skip("not JSON")
    client = client_for(role, w)
    response = send(client, "GET", OPS[op][1](w, role))
    assert response.status_code == 200, (op, role, response.content)
    schema = _inline(content["application/json"]["schema"])
    jsonschema.validate(response.json(), schema)
    if op[1] == "/api/v1/items/":  # real data: seeded items have a null subtype or image
        assert response.json()["results"]
