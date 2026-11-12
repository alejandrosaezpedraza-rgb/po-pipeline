"""HTTP client for the demo ERP. Swap this file to talk to a real ERP (see README)."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class ERPUnavailable(Exception):
    pass


class ERPRefused(Exception):
    pass


class ERPClient:
    name = "Demo ERP"

    def __init__(self, base_url, timeout=10, public_url=""):
        self.base = base_url.rstrip("/")
        self.public = (public_url or base_url).rstrip("/")  # what people's browsers use for links
        self.timeout = timeout

    def _req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("error")
            except Exception:
                msg = f"HTTP {e.code}"
            finally:
                e.close()
            if e.code == 404:
                return None
            raise ERPRefused(msg) from None
        except (urllib.error.URLError, OSError) as e:
            raise ERPUnavailable(f"ERP not reachable at {self.base} ({getattr(e, 'reason', e)})") from None

    def health(self):
        try:
            return bool((self._req("GET", "/api/health") or {}).get("ok"))
        except ERPUnavailable:
            return False

    def items(self):
        return {it["sku"]: it for it in self._req("GET", "/api/items") or []}

    def search(self, q, limit=3):
        return self._req("GET", "/api/items/search?" + urllib.parse.urlencode({"q": q, "limit": limit})) or []

    def find_po(self, customer, po_number):
        hit = self._req("GET", "/api/orders/find?" + urllib.parse.urlencode({"customer": customer, "po": po_number}))
        return hit or None

    def post_order(self, po, source="po-pipeline"):
        """Stage then approve: the same two calls the ERP's own UI uses."""
        staged = self._req("POST", "/api/orders", dict(po, source=source))
        return self._req("POST", f"/api/orders/{staged['id']}/approve")

    def order_url(self, so_number):
        return f"{self.public}/orders/{so_number}"
