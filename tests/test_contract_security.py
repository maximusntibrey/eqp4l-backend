"""FIX-10: cost never reaches BA/FS schemas; generated schema paths stay inside the contract."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from django.core.management import call_command

CONTRACT = Path(__file__).resolve().parent.parent / "docs" / "api" / "openapi.yaml"
METHODS = {"get", "post", "put", "patch", "delete"}
COST_KEYS = {"cost", "unit_cost", "average_cost", "unit_cost_snapshot"}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return loaded


def refs(node: Any) -> list[str]:
    if isinstance(node, dict):
        found = [node["$ref"]] if isinstance(node.get("$ref"), str) else []
        return found + [r for v in node.values() for r in refs(v)]
    if isinstance(node, list):
        return [r for v in node for r in refs(v)]
    return []


def reachable_schemas(spec: dict[str, Any], roots: list[str]) -> set[str]:
    schemas = spec["components"]["schemas"]
    seen: set[str] = set()
    todo = [r for r in roots if r.startswith("#/components/schemas/")]
    while todo:
        name = todo.pop().rsplit("/", 1)[1]
        if name in seen:
            continue
        seen.add(name)
        todo += refs(schemas[name])
    return seen


def test_no_cost_property_reachable_by_branch_roles(spec: dict[str, Any]) -> None:
    roots: list[str] = []
    for item in spec["paths"].values():
        for method, op in item.items():
            if method not in METHODS:
                continue
            perm = re.split(r"\(", op["x-permission"], maxsplit=1)[0]
            if re.search(r"\b(BA|FS)\b|any logged-in|public", perm):
                roots += refs(
                    {k: v for k, v in op.items() if k in ("requestBody", "responses", "parameters")}
                )
    found = {
        (name, prop)
        for name in reachable_schemas(spec, roots)
        for prop in spec["components"]["schemas"][name].get("properties", {})
        if prop in COST_KEYS
    }
    found |= {
        (name, prop)
        for name in reachable_schemas(spec, roots)
        for sub in spec["components"]["schemas"][name].get("allOf", [])
        for prop in sub.get("properties", {})
        if prop in COST_KEYS
    }
    assert found == set()


def test_cost_variants_only_on_sa_wa_operations(spec: dict[str, Any]) -> None:
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method in METHODS and any("WithCost" in r for r in refs(op)):
                assert (
                    re.split(r"\(", op["x-permission"], maxsplit=1)[0]
                    .replace(" ", "")
                    .startswith(("SA,WA", "SAall,WA"))
                ), (path, method)


def test_generated_paths_are_subset_of_contract(spec: dict[str, Any], tmp_path: Path) -> None:
    out = tmp_path / "schema.yaml"
    call_command("spectacular", file=str(out))
    generated = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert set(generated["paths"]) <= set(spec["paths"])
