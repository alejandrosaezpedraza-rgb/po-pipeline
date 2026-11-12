"""Demo ERP server: JSON API plus a small web UI. http://127.0.0.1:7811

Run:  python -m erp.server
"""
from __future__ import annotations

import html
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import core, seed_data

HOST = "127.0.0.1"
PORT = int(os.environ.get("ERP_PORT", "7811"))
# Path prefix when served behind the app (hosted: "/erp"); links in the pages include it.
BASE = os.environ.get("ERP_BASE_PATH", "").rstrip("/")

CSS = """
:root{--bg:#0f1115;--panel:#171a21;--line:#272c36;--text:#e7eaf0;--dim:#8b93a3;--accent:#6ea8fe;--ok:#4cc38a;--warn:#f0b64a;--bad:#ef6a6a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,Segoe UI,sans-serif}
header{display:flex;align-items:center;gap:24px;padding:14px 28px;border-bottom:1px solid var(--line);background:var(--panel)}
header b{font-size:15px;letter-spacing:.2px}header .tag{color:var(--dim);font-size:12px}
nav a{color:var(--dim);text-decoration:none;margin-right:16px}nav a:hover,nav a.on{color:var(--text)}
main{padding:24px 28px;max-width:1100px}h1{font-size:20px;margin:0 0 16px}h2{font-size:14px;color:var(--dim);margin:24px 0 8px;text-transform:uppercase;letter-spacing:.6px}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow:hidden}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line)}th{color:var(--dim);font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:.5px}
tr:last-child td{border-bottom:0}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
a{color:var(--accent)}.pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:12px;border:1px solid var(--line)}
.POSTED{color:var(--ok);border-color:#2c5f49}.STAGED{color:var(--warn);border-color:#6b5426}.REJECTED{color:var(--bad)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 16px}.card div{color:var(--dim)}.card p{margin:2px 0 0;color:var(--text)}
input[type=text]{background:var(--panel);border:1px solid var(--line);color:var(--text);padding:8px 12px;border-radius:6px;width:320px}
button{background:var(--accent);color:#0b0d12;border:0;border-radius:6px;padding:8px 14px;font-weight:600;cursor:pointer}
.flag{color:var(--warn);font-size:12px}.dim{color:var(--dim)}
"""


def esc(x):
    return html.escape("" if x is None else str(x))


def money(x):
    return f"${float(x or 0):,.2f}"


def page(title, body, active="orders"):
    nav = "".join(
        f'<a href="{href}" class="{"on" if key == active else ""}">{label}</a>'
        for key, href, label in (("orders", BASE + "/", "Sales orders"), ("items", BASE + "/items", "Item master")))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{esc(title)} · Demo ERP</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style></head><body>
<header><b>{esc(seed_data.COMPANY['name'])} · ERP</b><span class="tag">demo system, fictional data</span><nav>{nav}</nav></header>
<main>{body}</main></body></html>""".encode()


def view_orders():
    rows = core.list_orders()
    trs = "".join(
        f'<tr><td><a href="{BASE}/orders/{esc(r["so_number"] or r["id"])}">{esc(r["so_number"] or "staged #%d" % r["id"])}</a></td>'
        f'<td><span class="pill {esc(r["status"])}">{esc(r["status"])}</span></td><td>{esc(r["customer_name"])}</td>'
        f'<td>{esc(r["po_number"])}</td><td>{esc(r["requested_ship_date"])}</td><td class="n">{r["line_count"]}</td>'
        f'<td class="n">{money(r["total"])}</td><td class="dim">{esc(r["source"])}</td></tr>' for r in rows)
    if not trs:
        trs = '<tr><td colspan="8" class="dim">No orders yet.</td></tr>'
    return page("Sales orders", f"""<h1>Sales orders</h1><table><tr><th>Order</th><th>Status</th><th>Customer</th><th>PO</th>
<th>Ship date</th><th class="n">Lines</th><th class="n">Total</th><th>Source</th></tr>{trs}</table>""")


def addr(a):
    a = a or {}
    parts = [a.get("name"), a.get("street"), " ".join(x for x in (a.get("city"), a.get("state"), a.get("zip")) if x)]
    if a.get("store_number"):
        parts.append("Store " + a["store_number"])
    return "<br>".join(esc(p) for p in parts if p) or '<span class="dim">none</span>'


def view_order(ref):
    o = core.get_order(ref)
    if not o:
        return None
    trs = "".join(
        f'<tr><td>{l["line"]}</td><td>{esc(l["sku"])}</td><td>{esc(l["customer_item"])}</td><td>{esc(l["description"])}</td>'
        f'<td class="n">{l["qty"]:g}</td><td>{esc(l["uom"])}</td><td class="n">{money(l["unit_price"])}'
        + (f'<div class="flag">list {money(l["list_price"])}</div>' if abs(l["unit_price"] - l["list_price"]) > 0.005 else "")
        + f'</td><td class="n">{money(l["extended"])}</td></tr>' for l in o["lines"])
    buyer = o["buyer"]
    approve = ""
    if o["status"] == "STAGED":
        approve = f'<form method="post" action="{BASE}/orders/{o["id"]}/approve" style="margin:16px 0"><button>Approve and post</button></form>'
    title = o["so_number"] or f"Staged order #{o['id']}"
    return page(title, f"""<h1>{esc(title)} <span class="pill {esc(o['status'])}">{esc(o['status'])}</span></h1>{approve}
<div class="grid">
<div class="card"><div>Customer</div><p>{esc(o['customer_name'])}</p></div>
<div class="card"><div>Customer PO</div><p>{esc(o['po_number'])} · {esc(o['po_date'])}</p></div>
<div class="card"><div>Requested ship date</div><p>{esc(o['requested_ship_date'])}</p></div>
<div class="card"><div>Payment terms</div><p>{esc(o['payment_terms'])} · {esc(o['currency'])}</p></div>
<div class="card"><div>Buyer</div><p>{esc(buyer.get('contact_name'))}<br>{esc(buyer.get('email'))}<br>{esc(buyer.get('phone'))}</p></div>
<div class="card"><div>Bill to</div><p>{addr(o['bill_to'])}</p></div>
<div class="card"><div>Ship to</div><p>{addr(o['ship_to'])}</p></div>
<div class="card"><div>Entered</div><p>{esc(o['created_at'])} via {esc(o['source'])}<br>{('Posted ' + esc(o['posted_at'])) if o['posted_at'] else 'Not posted'}</p></div>
</div>
<h2>Lines</h2><table><tr><th>#</th><th>SKU</th><th>Customer item</th><th>Description</th><th class="n">Qty</th><th>UOM</th>
<th class="n">Unit price</th><th class="n">Extended</th></tr>{trs}
<tr><td colspan="7" class="n dim">Subtotal</td><td class="n">{money(o['subtotal'])}</td></tr>
<tr><td colspan="7" class="n dim">Freight</td><td class="n">{money(o['freight'])}</td></tr>
<tr><td colspan="7" class="n dim">Tax</td><td class="n">{money(o['tax'])}</td></tr>
<tr><td colspan="7" class="n"><b>Total</b></td><td class="n"><b>{money(o['total'])}</b></td></tr></table>
{('<h2>Notes</h2><p>' + esc(o['notes']) + '</p>') if o['notes'] else ''}""")


def view_items(q):
    items = core.search_items(q, limit=30) if q else core.all_items()
    trs = "".join(
        f'<tr><td>{esc(i["sku"])}</td><td>{esc(i["description"])}</td><td>{esc(i["category"])}</td><td>{esc(i["uom"])}</td>'
        f'<td class="n">{money(i["list_price"])}</td></tr>' for i in items) or '<tr><td colspan="5" class="dim">No matches.</td></tr>'
    return page("Item master", f"""<h1>Item master</h1><form method="get" style="margin-bottom:16px">
<input type="text" name="q" value="{esc(q)}" placeholder="Search SKU or description (typos are fine)" autofocus> <button>Search</button></form>
<table><tr><th>SKU</th><th>Description</th><th>Category</th><th>UOM</th><th class="n">List price</th></tr>{trs}</table>""", "items")


class Handler(BaseHTTPRequestHandler):
    server_version = "DemoERP/1.0"

    def log_message(self, fmt, *args):
        if not os.environ.get("ERP_QUIET"):
            sys.stderr.write("[erp] " + fmt % args + "\n")

    def _send(self, code, body, ctype="text/html; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj), "application/json")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        u = urlparse(self.path)
        path, qs = u.path.rstrip("/") or "/", parse_qs(u.query)
        try:
            if path == "/":
                return self._send(200, view_orders())
            if path.startswith("/orders/"):
                v = view_order(path.split("/", 2)[2])
                return self._send(200, v) if v else self._send(404, page("Not found", "<h1>Order not found</h1>"))
            if path == "/items":
                return self._send(200, view_items(qs.get("q", [""])[0]))
            if path == "/api/health":
                return self._json(200, {"ok": True, "service": "demo-erp"})
            if path == "/api/items":
                return self._json(200, core.all_items())
            if path == "/api/items/search":
                return self._json(200, core.search_items(qs.get("q", [""])[0], int(qs.get("limit", ["10"])[0])))
            if path.startswith("/api/items/"):
                it = core.get_item(path.rsplit("/", 1)[1])
                return self._json(200, it) if it else self._json(404, {"error": "no such SKU"})
            if path == "/api/orders":
                return self._json(200, core.list_orders())
            if path == "/api/orders/find":
                hit = core.find_po(qs.get("customer", [""])[0], qs.get("po", [""])[0])
                return self._json(200, hit or {})
            if path.startswith("/api/orders/"):
                o = core.get_order(path.rsplit("/", 1)[1])
                return self._json(200, o) if o else self._json(404, {"error": "no such order"})
            self._send(404, page("Not found", "<h1>Not found</h1>"))
        except core.ERPError as e:
            self._json(400, {"error": str(e)})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        parts = path.strip("/").split("/")
        try:
            if path == "/api/orders":
                order = core.stage_order(json.loads(self._body() or b"{}"))
                return self._json(201, order)
            if len(parts) == 4 and parts[:2] == ["api", "orders"] and parts[3] in ("approve", "reject"):
                fn = core.approve_order if parts[3] == "approve" else core.reject_order
                return self._json(200, fn(parts[2]))
            if len(parts) == 3 and parts[0] == "orders" and parts[2] == "approve":  # UI form
                order = core.approve_order(parts[1])
                return self._send(303, b"", headers={"Location": f"{BASE}/orders/{order['so_number']}"})
            self._json(404, {"error": "not found"})
        except core.DuplicateError as e:
            self._json(409, {"error": str(e), "existing": e.existing})
        except core.ERPError as e:
            self._json(400, {"error": str(e)})
        except json.JSONDecodeError:
            self._json(400, {"error": "body is not valid JSON"})


def main():
    core.init_db()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    srv.daemon_threads = True
    print(f"Demo ERP on http://{HOST}:{PORT}  (db: {core.db_path()})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
