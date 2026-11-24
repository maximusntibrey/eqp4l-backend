"""B3.5: every role against every B3 endpoint (matrix from PERMISSION_TABLE rows 4-12, 40), the
password-change gate, anonymous access, and the generated schema against the published contract."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from django.core.management import call_command
from rest_framework.test import APIClient

from accounts.models import User, UserStatus
from branches.models import Location
from tests.api import call, client_as

pytestmark = pytest.mark.django_db
SA, WA, BA, FS = "sa", "wa", "ba", "fs"
ALL, ADMINS = {SA, WA, BA, FS}, {SA, WA, BA}
CONTRACT = Path(__file__).resolve().parent.parent / "docs" / "api" / "openapi.yaml"

# (method, url with {a}=branch A, {off}=inactive branch, {me}=caller, {fs}=the FS user, body, roles allowed,
#  status when allowed). The rows come from the approved table, not from the code under test.
ENDPOINTS: list[tuple[str, str, Any, set[str], int]] = [
    ("GET", "/api/v1/working-branch/", None, {SA, FS}, 200),  # row 10
    ("PUT", "/api/v1/working-branch/", {"branch_id": "{a}"}, {SA, FS}, 200),  # row 10
    ("GET", "/api/v1/branches/", None, ALL, 200),  # row 12
    ("GET", "/api/v1/branches/{a}/", None, ALL, 200),  # row 12
    ("POST", "/api/v1/branches/", {"code": "C", "name": "Branch C"}, {SA}, 201),  # row 11
    ("PATCH", "/api/v1/branches/{a}/", {"name": "Renamed"}, {SA}, 200),  # row 11
    ("POST", "/api/v1/branches/{a}/deactivate/", None, {SA}, 200),  # row 11
    ("POST", "/api/v1/branches/{off}/activate/", None, {SA}, 200),  # row 11
    ("GET", "/api/v1/users/", None, ADMINS, 200),  # row 9
    ("GET", "/api/v1/users/{me}/", None, ADMINS, 200),  # row 9
    ("POST", "/api/v1/users/", {"full_name": "N N", "roles": ["front_staff"]}, {SA}, 201),  # rows 4, 6
    ("PATCH", "/api/v1/users/{fs}/", {"full_name": "Renamed"}, {SA}, 200),  # row 4
    ("POST", "/api/v1/users/{fs}/reset-password/", None, {SA}, 200),  # row 5
    ("POST", "/api/v1/users/{fs}/status/", {"status": "suspended"}, {SA}, 200),  # row 4
    ("GET", "/api/v1/users/{fs}/permissions/", None, {SA}, 200),  # row 8
    ("PUT", "/api/v1/users/{fs}/permissions/", {"permissions": ["manage_prices"]}, {SA}, 200),  # row 8
    ("GET", "/api/v1/dashboard/", None, ADMINS, 200),  # row 40
]


def fill(value: Any, ids: dict[str, int]) -> Any:
    """Replace "{a}" style placeholders; a whole-string placeholder becomes the integer id."""
    if isinstance(value, str):
        return ids[value[1:-1]] if value in {"{" + k + "}" for k in ids} else value.format(**ids)
    if isinstance(value, dict):
        return {k: fill(v, ids) for k, v in value.items()}
    return value


def ids_for(role: str, users: dict[str, Any], locations: Any) -> dict[str, int]:
    off = Location.objects.create(kind="branch", code="OFF", name="Off", is_active=False)
    return {"a": locations["a"].pk, "off": off.pk, "me": users[role].pk, "fs": users[FS].pk}


@pytest.mark.parametrize(("method", "url", "body", "allowed", "ok"), ENDPOINTS)
@pytest.mark.parametrize("role", [SA, WA, BA, FS])
def test_permission_matrix(
    role: str,
    method: str,
    url: str,
    body: Any,
    allowed: set[str],
    ok: int,
    users: dict[str, Any],
    locations: Any,
) -> None:
    ids = ids_for(role, users, locations)
    response = call(client_as(users[role]), method, url.format(**ids), fill(body, ids))
    if role in allowed:
        assert response.status_code == ok, (role, method, url, response.content)
    else:
        assert response.status_code == 403, (role, method, url, response.status_code)
        assert response.json()["code"] == "permission_denied"


@pytest.mark.parametrize(("method", "url", "body", "allowed", "ok"), ENDPOINTS)
def test_anonymous_gets_401_and_a_pending_password_change_gets_403(
    method: str,
    url: str,
    body: Any,
    allowed: set[str],
    ok: int,
    users: dict[str, Any],
    locations: Any,
    make_user: Any,
) -> None:
    ids = ids_for(SA, users, locations)
    target, data = url.format(**ids), fill(body, ids)
    anonymous = call(APIClient(), method, target, data)
    assert anonymous.status_code == 401 and anonymous.json()["code"] == "not_authenticated"
    pending = make_user("super_admin", status=UserStatus.PENDING_ACTIVATION, must_change_password=True)
    response = call(client_as(pending), method, target, data)
    assert response.status_code == 403 and response.json()["code"] == "password_change_required"


@pytest.mark.parametrize("state", ["suspended", "deactivated"])
def test_suspended_or_deactivated_user_is_refused_everywhere(
    state: str, users: dict[str, Any], locations: Any
) -> None:
    client, ids = client_as(users[SA]), ids_for(SA, users, locations)
    User.objects.filter(pk=users[SA].pk).update(status=state)
    for method, url, body, _, _ in ENDPOINTS:
        assert call(client, method, url.format(**ids), fill(body, ids)).status_code == 401, (method, url)


def test_cross_branch_rules_ba_never_reach_another_branchs_users_or_scope(
    users: dict[str, Any], locations: Any, make_user: Any
) -> None:
    other_ba = make_user("branch_admin", "b")
    ba = client_as(users[BA])
    assert call(ba, "GET", f"/api/v1/users/{other_ba.pk}/").status_code == 404
    assert other_ba.login_id not in call(ba, "GET", "/api/v1/users/").content.decode()
    # a BA cannot name another branch as its scope, and the dashboard is always the own branch
    assert call(ba, "PUT", "/api/v1/working-branch/", {"branch_id": locations["b"].pk}).status_code == 403
    assert call(ba, "GET", "/api/v1/dashboard/").json()["location"]["id"] == locations["a"].pk
    # nor write to another branch through the management endpoints
    assert call(ba, "PATCH", f"/api/v1/branches/{locations['b'].pk}/", {"name": "Hijack"}).status_code == 403
    assert Location.objects.get(pk=locations["b"].pk).name == "Branch B"
    # the other BA is the same in reverse
    assert call(client_as(other_ba), "GET", f"/api/v1/users/{users[BA].pk}/").status_code == 404


# ---- the generated schema against the published contract (implemented paths) --------------------

B3_PREFIXES = ("/api/v1/working-branch/", "/api/v1/branches/", "/api/v1/users/", "/api/v1/dashboard/")
METHODS = {"get", "post", "put", "patch", "delete"}


def props(spec: dict[str, Any], schema: dict[str, Any]) -> set[str]:
    """Property names of an object schema, following $ref and allOf."""
    if "$ref" in schema:
        node: Any = spec
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        return props(spec, node)
    found = set(schema.get("properties", {}))
    for sub in schema.get("allOf", []):
        found |= props(spec, sub)
    return found


def operations(spec: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (p, m): op
        for p, item in spec["paths"].items()
        if p.startswith(B3_PREFIXES)
        for m, op in item.items()
        if m in METHODS
    }


def query_names(spec: dict[str, Any], op: dict[str, Any], path_item: dict[str, Any]) -> set[str]:
    names = set()
    for param in op.get("parameters", []):
        if "$ref" in param:
            param = spec["components"]["parameters"][param["$ref"].rsplit("/", 1)[1]]
        if param["in"] == "query":
            names.add(param["name"])
    return names


def test_generated_schema_matches_the_contract_for_every_b3_operation(tmp_path: Path) -> None:
    out = tmp_path / "schema.yaml"
    call_command("spectacular", file=str(out))
    generated = yaml.safe_load(out.read_text(encoding="utf-8"))
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    gen_ops, ref_ops = operations(generated), operations(contract)
    assert set(gen_ops) == set(ref_ops) and len(ref_ops) == 17  # nothing missing, nothing extra
    for key, ref in ref_ops.items():
        gen = gen_ops[key]
        assert gen["operationId"] == ref["operationId"], key
        assert set(gen["responses"]) <= set(ref["responses"]), key
        gen_header = {p["name"] for p in gen.get("parameters", []) if p["in"] == "header"}
        ref_header = {
            "Idempotency-Key"
            for p in ref.get("parameters", [])
            if p.get("$ref", "").endswith("/IdempotencyKey")
        }
        assert gen_header == ref_header, key
        assert query_names(generated, gen, {}) == query_names(contract, ref, {}), key
        for code in ("200", "201"):
            if code in ref["responses"] and "content" in ref["responses"][code]:
                ref_schema = ref["responses"][code]["content"]["application/json"]["schema"]
                gen_schema = gen["responses"][code]["content"]["application/json"]["schema"]
                assert props(generated, gen_schema) == props(contract, ref_schema), (key, code)
        if "requestBody" in ref:
            ref_body = ref["requestBody"]["content"]["application/json"]["schema"]
            gen_body = gen["requestBody"]["content"]["application/json"]["schema"]
            assert props(generated, gen_body) == props(contract, ref_body), key
