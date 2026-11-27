#!/usr/bin/env python3
"""API smoke test: log in, call every GET endpoint, run safe write cycles, report per endpoint.

Standard library only. Exit code 1 on any 5xx, any missing CORS header, any CSRF refusal or a failed
write cycle step the role should be able to do. A 403 on an endpoint the role may not use is reported
as "403 (role)" and is fine.

    python scripts/api-smoke.py --login SA-0001 --password '<DEV_SA_0001_PASSWORD>'
    python scripts/api-smoke.py --base http://localhost:8000 --origin http://localhost:5173 \
        --login USR-0001 --password '...'     # password may also come from API_SMOKE_PASSWORD

Writes (SA/WA/BA/FS as allowed): a draft item, a user, a branch, a goods receipt, a dispatch received at a
branch, a sale cancelled again, a CSV import dry run. They are real rows in the target database, so use a
local or staging stack, never production.
"""

import argparse
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any

PREFLIGHT_HEADERS = "content-type,x-csrftoken,idempotency-key"
GETS = [
    "/health/",
    "/api/v1/auth/csrf/",
    "/api/v1/auth/me/",
    "/api/v1/working-branch/",
    "/api/v1/branches/",
    "/api/v1/users/",
    "/api/v1/dashboard/",
    "/api/v1/item-categories/",
    "/api/v1/brands/",
    "/api/v1/items/",
    "/api/v1/costed-items/",
    "/api/v1/stock/",
    "/api/v1/stock/movements/",
    "/api/v1/costed-stock/",
    "/api/v1/goods-receipts/",
    "/api/v1/dispatches/",
    "/api/v1/shortfalls/",
    "/api/v1/activity-log/",
    "/api/v1/activity-log/export/",
    "/api/v1/sales/",
    "/api/v1/costed-sales/",
]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class Smoke:
    def __init__(self, base: str, origin: str) -> None:
        self.base, self.origin = base.rstrip("/"), origin
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)
        self.rows: list[tuple[str, str, str, str]] = []  # method, path, status, verdict
        self.failed = False

    def cookie(self, name: str) -> str:
        return next((c.value or "" for c in self.jar if c.name == name), "")

    def raw(
        self, method: str, path: str, data: bytes | None = None, headers: dict[str, str] | None = None
    ) -> Any:
        head = {"Origin": self.origin, **(headers or {})}
        if method not in ("GET", "HEAD", "OPTIONS") and self.cookie("csrftoken"):
            head["X-CSRFToken"] = self.cookie("csrftoken")
        request = urllib.request.Request(self.base + path, data=data, headers=head, method=method)  # noqa: S310
        try:
            response = self.opener.open(request, timeout=30)  # base is checked to be http(s)
        except urllib.error.HTTPError as err:
            response = err
        except urllib.error.URLError as err:
            raise SystemExit(f"cannot reach {self.base}: {err.reason}") from err
        return response.status, response.headers, response.read()

    def call(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        key: bool = True,
        multipart: dict[str, tuple[str, bytes] | str] | None = None,
        expect_refusal_ok: bool = True,
    ) -> tuple[int, Any]:
        headers: dict[str, str] = {}
        data = None
        if multipart is not None:
            boundary = uuid.uuid4().hex
            parts = []
            for name, value in multipart.items():
                if isinstance(value, tuple):
                    filename, content = value
                    parts.append(
                        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                        f'filename="{filename}"\r\n'
                        f"Content-Type: text/csv\r\n\r\n".encode()
                        + content
                        + b"\r\n"
                    )
                else:
                    field = f'Content-Disposition: form-data; name="{name}"'
                    parts.append(f"--{boundary}\r\n{field}\r\n\r\n{value}\r\n".encode())
            data = b"".join(parts) + f"--{boundary}--\r\n".encode()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if method not in ("GET", "HEAD") and key:
            headers["Idempotency-Key"] = str(uuid.uuid4())
        status, response_headers, raw = self.raw(method, path, data, headers)
        text = raw.decode("utf-8", "replace")
        try:
            parsed: Any = json.loads(text) if text else None
        except ValueError:
            parsed = text
        problems = []
        if status >= 500:
            problems.append("5xx")
        if response_headers.get("Access-Control-Allow-Origin") != self.origin:
            problems.append("CORS: no Allow-Origin for the origin")
        if response_headers.get("Access-Control-Allow-Credentials") != "true":
            problems.append("CORS: no Allow-Credentials")
        if status == 403 and "csrf" in text.lower():
            problems.append("CSRF refused")
        verdict = "; ".join(problems) or (
            "ok" if status < 400 else "403 (role)" if status == 403 else f"{status}"
        )
        if status == 403 and not problems and not expect_refusal_ok:
            problems.append("unexpected 403")
            verdict = "unexpected 403"
        if status >= 400 and status != 403 and not problems and expect_refusal_ok is False:
            problems.append(f"unexpected {status}")
            verdict = f"unexpected {status}: {text[:160]}"
        self.rows.append((method, path.split("?")[0], str(status), verdict))
        if problems:
            self.failed = True
        return status, parsed

    def preflight(self, method: str, path: str) -> None:
        status, headers, _ = self.raw(
            "OPTIONS",
            path,
            headers={
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": PREFLIGHT_HEADERS,
            },
        )
        allowed = {h.strip() for h in headers.get("Access-Control-Allow-Headers", "").lower().split(",")}
        ok = status == 200 and set(PREFLIGHT_HEADERS.split(",")) <= allowed
        self.rows.append(("OPTIONS", path, str(status), "ok" if ok else "CORS preflight refused the headers"))
        self.failed |= not ok


def first(parsed: Any, **match: Any) -> dict[str, Any] | None:
    rows = parsed.get("results", parsed) if isinstance(parsed, dict) else parsed
    for row in rows or []:
        if all(row.get(k) == v for k, v in match.items()):
            return dict(row)
    return None


def cycles(s: Smoke) -> None:
    tag = uuid.uuid4().hex[:6]
    _, me = s.call("GET", "/api/v1/auth/me/")
    permissions = set((me or {}).get("permissions", []))
    _, branches = s.call("GET", "/api/v1/branches/?page_size=100")
    warehouse = first(branches, branch_type="warehouse", is_active=True)
    shop = first(branches, branch_type="branch", is_active=True)
    if ((me or {}).get("must_pick_branch") or "working_branch.select" in permissions) and shop:
        s.call("PUT", "/api/v1/working-branch/", {"branch_id": shop["id"]})
    _, categories = s.call("GET", "/api/v1/item-categories/")
    _, brands = s.call("GET", "/api/v1/brands/")
    category = categories[0] if isinstance(categories, list) and categories else None
    brand = first(brands)
    if category:
        s.call("GET", f"/api/v1/item-field-definitions/?category_id={category['id']}")
    if "items.manage" in permissions and category and brand and category.get("subtypes"):
        specs = {"processor": "Core i5", "ram_gb": 16, "storage_gb": 512, "storage_type": "NVMe SSD"}
        status, item = s.call(
            "POST",
            "/api/v1/items/",
            {
                "name": f"Smoke {tag}",
                "category_id": category["id"],
                "subtype_id": category["subtypes"][0]["id"],
                "brand_id": brand["id"],
                "model_name": f"SMK-{tag}",
                "mpn": f"SMK{tag}",
                "condition": "new",
                "key_specs": specs,
            },
            expect_refusal_ok=False,
        )
        if status == 201:
            s.call(
                "PATCH",
                f"/api/v1/items/{item['id']}/",
                {"model_name": f"SMK-{tag}-b"},
                expect_refusal_ok=False,
            )
    if "users.manage" in permissions:
        status, user = s.call(
            "POST",
            "/api/v1/users/",
            {"full_name": f"Smoke User {tag}", "roles": ["front_staff"]},
            expect_refusal_ok=False,
        )
        if status == 201:
            s.call(
                "PATCH",
                f"/api/v1/users/{user['id']}/",
                {"full_name": f"Smoke User {tag} b"},
                expect_refusal_ok=False,
            )
            s.call(
                "POST",
                f"/api/v1/users/{user['id']}/status/",
                {"status": "deactivated"},
                expect_refusal_ok=False,
            )
    if "branches.manage" in permissions:
        status, made = s.call(
            "POST",
            "/api/v1/branches/",
            {"code": f"S{tag}".upper(), "name": f"Smoke Branch {tag}", "branch_type": "branch"},
            expect_refusal_ok=False,
        )
        if status == 201:
            s.call(
                "PATCH",
                f"/api/v1/branches/{made['id']}/",
                {"name": f"Smoke Branch {tag} b"},
                expect_refusal_ok=False,
            )
            s.call("POST", f"/api/v1/branches/{made['id']}/deactivate/", {}, expect_refusal_ok=False)
    _, items = s.call("GET", "/api/v1/items/?status=active&page_size=100")
    active = first(items, status="active")
    if "goods_receipts.manage" in permissions and active and warehouse:
        s.call(
            "POST",
            "/api/v1/goods-receipts/",
            {
                "warehouse_id": warehouse["id"],
                "supplier_name": f"Smoke supplier {tag}",
                "lines": [{"item_id": active["id"], "quantity": 2, "unit_cost": "1.00"}],
            },
            expect_refusal_ok=False,
        )
    if "dispatches.create" in permissions and active and warehouse and shop:
        status, dispatch = s.call(
            "POST",
            "/api/v1/dispatches/",
            {
                "warehouse_id": warehouse["id"],
                "destination_id": shop["id"],
                "lines": [{"item_id": active["id"], "quantity": 1}],
            },
            expect_refusal_ok=False,
        )
        if status == 201:
            s.call("GET", f"/api/v1/dispatches/{dispatch['id']}/")
    if "dispatches.receive" in permissions and shop:
        _, waiting = s.call("GET", f"/api/v1/dispatches/waiting/?branch_id={shop['id']}")
        pending = (waiting or {}).get("results", []) if isinstance(waiting, dict) else []
        if pending:
            lines = [
                {"line_id": ln["id"], "qty_received": ln["qty_sent"], "qty_accepted": ln["qty_sent"]}
                for ln in pending[0]["lines"]
            ]
            s.call(
                "POST",
                f"/api/v1/dispatches/{pending[0]['id']}/receive/",
                {"decision": "approve_all", "lines": lines},
                expect_refusal_ok=False,
            )
    if "sales.record" in permissions and active:
        status, sale = s.call(
            "POST",
            "/api/v1/sales/",
            {"payment_method": "cash", "lines": [{"item_id": active["id"], "quantity": 1}]},
        )
        if status == 201 and "sales.cancel" in permissions:
            s.call(
                "POST",
                f"/api/v1/sales/{sale['id']}/cancel/",
                {"reason": "api-smoke"},
                expect_refusal_ok=False,
            )
    if "items.import" in permissions and warehouse:
        header = "sku,name,category,subtype,brand,model_name,mpn,condition,opening_quantity,unit_cost"
        csv = f"{header}\n,Smoke import {tag},Laptop,Business,HP,SMK{tag},SMKI{tag},new,1,1.00\n".encode()
        s.call(
            "POST",
            "/api/v1/item-imports/",
            multipart={"file": ("smoke.csv", csv), "dry_run": "true", "location_id": str(warehouse["id"])},
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base", default=os.environ.get("API_SMOKE_BASE", "http://localhost:8000"))
    parser.add_argument("--origin", default=os.environ.get("API_SMOKE_ORIGIN", "http://localhost:5173"))
    parser.add_argument("--login", required=True, help="login id, for example SA-0001")
    parser.add_argument("--password", default=os.environ.get("API_SMOKE_PASSWORD", ""))
    args = parser.parse_args()
    if not args.password:
        parser.error("give --password or set API_SMOKE_PASSWORD")
    if not args.base.startswith(("http://", "https://")):
        parser.error("--base must start with http:// or https://")
    smoke = Smoke(args.base, args.origin)
    for method, path in (
        ("POST", "/api/v1/auth/login/"),
        ("POST", "/api/v1/items/"),
        ("PATCH", "/api/v1/items/1/"),
    ):
        smoke.preflight(method, path)
    smoke.call("GET", "/api/v1/auth/csrf/")
    status, body = smoke.call(
        "POST",
        "/api/v1/auth/login/",
        {"login_id": args.login, "password": args.password},
        key=False,
        expect_refusal_ok=False,
    )
    if status != 200:
        print(f"login failed: {status} {body}")
        return 1
    if body.get("must_change_password") or body.get("user", {}).get("must_change_password"):
        print("this account must change its password first; the smoke test cannot continue")
        return 1
    for path in GETS:
        smoke.call("GET", path)
    cycles(smoke)
    smoke.call("POST", "/api/v1/auth/logout/", {}, key=False)
    width = max(len(p) for _, p, _, _ in smoke.rows)
    for method, path, code, verdict in smoke.rows:
        print(f"{method:<8}{path:<{width + 2}}{code:<5}{verdict}")
    bad = [r for r in smoke.rows if r[3] not in ("ok", "403 (role)") and not r[3].isdigit()]
    print(f"\n{len(smoke.rows)} calls, {len(bad)} problem(s): {'FAIL' if smoke.failed else 'OK'}")
    return 1 if smoke.failed else 0


if __name__ == "__main__":
    sys.exit(main())
