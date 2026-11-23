"""FIX-3: contract x-permission rows exist in PERMISSION_TABLE.md and the role sets agree."""

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "docs" / "design" / "PERMISSION_TABLE.md"
CONTRACT = ROOT / "docs" / "api" / "openapi.yaml"
METHODS = {"get", "post", "put", "patch", "delete"}
ROLES = ["SA", "WA", "BA", "FS"]


def table_rows() -> dict[int, set[str]]:
    rows: dict[int, set[str]] = {}
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 6 and cells[0].isdigit():
            rows[int(cells[0])] = {
                r for r, c in zip(ROLES, cells[2:6], strict=True) if not c.lower().startswith("n")
            }
    return rows


def contract_ops() -> list[tuple[str, str, str]]:
    spec: dict[str, Any] = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return [
        (p, m, op["x-permission"]) for p, i in spec["paths"].items() for m, op in i.items() if m in METHODS
    ]


def test_table_parses() -> None:
    assert len(table_rows()) >= 42


def test_every_referenced_row_exists_and_roles_agree() -> None:
    rows = table_rows()
    problems: list[str] = []
    for path, method, perm in contract_ops():
        refs = [
            n
            for g in re.findall(r"\((?:table )?rows? ([^)]*)\)", perm)
            for n in re.findall(r"(?<!OQ-)\b\d+\b", g)
        ]
        missing = [int(n) for n in refs if int(n) not in rows]
        if missing:
            problems.append(f"{method} {path}: rows {missing} not in table")
        if not refs or perm.startswith("public"):
            continue
        head = perm.split("(", 1)[0]
        stated = set(ROLES) if "any logged-in" in head else set(re.findall(r"\b(SA|WA|BA|FS)\b", head))
        if int(refs[0]) in rows and stated != rows[int(refs[0])]:
            problems.append(
                f"{method} {path}: contract {sorted(stated)} vs row {refs[0]} {sorted(rows[int(refs[0])])}"
            )
    assert problems == []
