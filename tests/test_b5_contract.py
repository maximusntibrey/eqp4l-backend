"""The generated schema against the published contract for the Day 5 operations (receipts, dispatches)."""

from pathlib import Path
from typing import Any

import yaml
from django.core.management import call_command

from tests.test_b3_matrix import CONTRACT, METHODS, props, query_names
from tests.test_b4_contract import first_schema

B5_PREFIXES = ("/api/v1/goods-receipts/", "/api/v1/dispatches/")


def b5_operations(spec: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (p, m): op
        for p, item in spec["paths"].items()
        if p.startswith(B5_PREFIXES)
        for m, op in item.items()
        if m in METHODS
    }


def test_generated_schema_matches_the_contract_for_every_b5_operation(tmp_path: Path) -> None:
    out = tmp_path / "schema.yaml"
    call_command("spectacular", file=str(out))
    generated = yaml.safe_load(out.read_text(encoding="utf-8"))
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    gen_ops, ref_ops = b5_operations(generated), b5_operations(contract)
    assert set(gen_ops) == set(ref_ops) and len(ref_ops) == 8  # nothing missing, nothing extra
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
                ref_schema = first_schema(ref["responses"][code]["content"])
                gen_schema = first_schema(gen["responses"][code]["content"])
                assert props(generated, gen_schema) == props(contract, ref_schema), (key, code)
        if "requestBody" in ref:
            ref_body = first_schema(ref["requestBody"]["content"])
            gen_body = first_schema(gen["requestBody"]["content"])
            assert props(generated, gen_body) == props(contract, ref_body), key
