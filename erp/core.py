"""Demo ERP core: item master, typo-tolerant search, staged-then-approved sales orders.

Every order, however it got here, goes through stage_order() then approve_order().
The HTTP API and the web UI call these same two functions.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import sqlite3
import threading
from datetime import datetime

from . import seed_data

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "data", "erp.db")
FIRST_SO = 11901

_lock = threading.RLock()


class ERPError(Exception):
    """A request the ERP refuses. Message is safe to show to a person."""


class DuplicateError(ERPError):
    def __init__(self, message, existing):
        super().__init__(message)
        self.existing = existing


SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  sku TEXT PRIMARY KEY, description TEXT NOT NULL, category TEXT NOT NULL,
  uom TEXT NOT NULL, list_price REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  so_number TEXT UNIQUE,
  status TEXT NOT NULL,
  customer_name TEXT NOT NULL, customer_key TEXT NOT NULL,
  po_number TEXT NOT NULL, po_date TEXT, requested_ship_date TEXT,
  payment_terms TEXT, currency TEXT,
  buyer TEXT, bill_to TEXT, ship_to TEXT,
  subtotal REAL, freight REAL, tax REAL, total REAL,
  notes TEXT, source TEXT,
  created_at TEXT, posted_at TEXT
);
CREATE TABLE IF NOT EXISTS order_lines (
  order_id INTEGER NOT NULL REFERENCES orders(id),
  line INTEGER NOT NULL, sku TEXT NOT NULL, customer_item TEXT, description TEXT,
  qty REAL NOT NULL, uom TEXT, unit_price REAL NOT NULL, extended REAL NOT NULL,
  list_price REAL NOT NULL,
  PRIMARY KEY (order_id, line)
);
CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
"""


def db_path():
    return os.environ.get("ERP_DB") or DEFAULT_DB


def connect(path=None):
    path = path or db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db(path=None):
    """Create tables and seed the item master on first run."""
    with _lock:
        con = connect(path)
        con.executescript(SCHEMA)
        if con.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
            con.executemany("INSERT INTO items VALUES (?,?,?,?,?)", seed_data.ITEMS)
            con.execute("INSERT OR IGNORE INTO counters VALUES ('so', ?)", (FIRST_SO - 1,))
            con.commit()
        con.close()


# ---------------------------------------------------------------- items

def norm_sku(sku):
    return re.sub(r"\s+", "", str(sku or "")).upper()


def _alnum(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def all_items(con=None):
    own = con is None
    con = con or connect()
    try:
        return [dict(r) for r in con.execute("SELECT * FROM items ORDER BY category, sku")]
    finally:
        if own:
            con.close()


def get_item(sku, con=None):
    own = con is None
    con = con or connect()
    try:
        row = con.execute("SELECT * FROM items WHERE sku = ?", (norm_sku(sku),)).fetchone()
        return dict(row) if row else None
    finally:
        if own:
            con.close()


def _token_score(qt, words):
    best = 0.0
    for w in words:
        if qt == w:
            return 1.0
        if len(qt) >= 2 and w.startswith(qt):
            best = max(best, 0.9)
        elif qt in w and len(qt) >= 3:
            best = max(best, 0.8)
        else:
            r = difflib.SequenceMatcher(None, qt, w).ratio()
            if r >= 0.72:
                best = max(best, r * 0.85)
    return best


def search_items(query, limit=10, con=None):
    """Typo-tolerant search over SKU and description. Returns items with a 'score'."""
    q = str(query or "").strip().lower()
    if not q:
        return []
    qtokens = re.findall(r"[a-z0-9]+", q)
    qa = _alnum(q)
    out = []
    for it in all_items(con):
        sku_a = _alnum(it["sku"])
        words = re.findall(r"[a-z0-9]+", (it["sku"] + " " + it["description"]).lower())
        if qa == sku_a:
            score = 1.0
        else:
            tok = sum(_token_score(t, words) for t in qtokens) / max(len(qtokens), 1)
            sku_fuzz = difflib.SequenceMatcher(None, qa, sku_a).ratio() * 0.9 if len(qa) >= 3 else 0
            score = max(tok, sku_fuzz)
        if score >= 0.6:
            out.append(dict(it, score=round(score, 3)))
    out.sort(key=lambda r: (-r["score"], r["sku"]))
    return out[:limit]


# ---------------------------------------------------------------- orders

def customer_key(name):
    return _alnum(name)


def _money(x):
    return round(float(x) + 0.0, 2)


def _json(v):
    return json.dumps(v or {}, sort_keys=True)


def _order_row_to_dict(con, row):
    o = dict(row)
    for k in ("buyer", "bill_to", "ship_to"):
        o[k] = json.loads(o[k] or "{}")
    o["lines"] = [dict(r) for r in con.execute(
        "SELECT * FROM order_lines WHERE order_id=? ORDER BY line", (o["id"],))]
    return o


def get_order(ref, con=None):
    """ref is a numeric id or an SO number such as SO-11905."""
    own = con is None
    con = con or connect()
    try:
        ref = str(ref)
        if ref.upper().startswith("SO-"):
            row = con.execute("SELECT * FROM orders WHERE so_number=?", (ref.upper(),)).fetchone()
        elif ref.isdigit():
            row = con.execute("SELECT * FROM orders WHERE id=?", (int(ref),)).fetchone()
        else:
            row = None
        return _order_row_to_dict(con, row) if row else None
    finally:
        if own:
            con.close()


def list_orders(con=None):
    own = con is None
    con = con or connect()
    try:
        rows = con.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
        out = []
        for r in rows:
            o = dict(r)
            o["line_count"] = con.execute(
                "SELECT COUNT(*) FROM order_lines WHERE order_id=?", (o["id"],)).fetchone()[0]
            out.append(o)
        return out
    finally:
        if own:
            con.close()


def find_po(customer_name, po_number, con=None):
    own = con is None
    con = con or connect()
    try:
        row = con.execute(
            "SELECT id, so_number, status FROM orders WHERE customer_key=? AND po_number=? "
            "AND status != 'REJECTED'", (customer_key(customer_name), str(po_number).strip())).fetchone()
        return dict(row) if row else None
    finally:
        if own:
            con.close()


def stage_order(payload):
    """Validate and stage an order. Nothing is posted until approve_order()."""
    with _lock:
        con = connect()
        try:
            return _stage(con, payload)
        finally:
            con.close()


def _stage(con, p):
    customer = str((p.get("buyer") or {}).get("company") or p.get("customer_name") or "").strip()
    po_number = str(p.get("po_number") or "").strip()
    errors = []
    if not customer:
        errors.append("customer name is missing")
    if not po_number:
        errors.append("PO number is missing")
    lines = p.get("lines") or []
    if not lines:
        errors.append("order has no lines")

    clean_lines = []
    for i, ln in enumerate(lines, 1):
        item = get_item(ln.get("sku"), con)
        if not item:
            errors.append(f"line {i}: SKU '{ln.get('sku')}' is not in the item master")
            continue
        try:
            qty = float(ln.get("qty"))
            price = float(ln.get("unit_price"))
        except (TypeError, ValueError):
            errors.append(f"line {i}: qty and unit price must be numbers")
            continue
        if qty <= 0:
            errors.append(f"line {i}: qty must be above zero")
            continue
        ext = _money(qty * price)
        if ln.get("extended") is not None and abs(float(ln["extended"]) - ext) > 0.005:
            errors.append(f"line {i}: extended {ln['extended']} does not equal qty x price ({ext})")
        clean_lines.append({
            "line": i, "sku": item["sku"], "customer_item": str(ln.get("customer_item") or ""),
            "description": str(ln.get("description") or item["description"]),
            "qty": qty, "uom": str(ln.get("uom") or item["uom"]),
            "unit_price": _money(price), "extended": ext, "list_price": item["list_price"],
        })
    subtotal = _money(sum(l["extended"] for l in clean_lines))
    freight = _money(p.get("freight") or 0)
    tax = _money(p.get("tax") or 0)
    total = _money(subtotal + freight + tax)
    if p.get("total") is not None and not errors and abs(float(p["total"]) - total) > 0.005:
        errors.append(f"total {p['total']} does not equal subtotal + freight + tax ({total})")
    if p.get("subtotal") is not None and not errors and abs(float(p["subtotal"]) - subtotal) > 0.005:
        errors.append(f"subtotal {p['subtotal']} does not equal the sum of the lines ({subtotal})")
    if errors:
        raise ERPError("; ".join(errors))

    dup = find_po(customer, po_number, con)
    if dup:
        ref = dup["so_number"] or f"staged order #{dup['id']}"
        raise DuplicateError(f"PO {po_number} from {customer} already exists in the ERP ({ref})", dup)

    now = datetime.now().isoformat(timespec="seconds")
    cur = con.execute(
        "INSERT INTO orders (status, customer_name, customer_key, po_number, po_date, requested_ship_date,"
        " payment_terms, currency, buyer, bill_to, ship_to, subtotal, freight, tax, total, notes, source,"
        " created_at) VALUES ('STAGED',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (customer, customer_key(customer), po_number, p.get("po_date") or "", p.get("requested_ship_date") or "",
         p.get("payment_terms") or "", p.get("currency") or "USD", _json(p.get("buyer")),
         _json(p.get("bill_to")), _json(p.get("ship_to")), subtotal, freight, tax, total,
         p.get("notes") or "", p.get("source") or "api", now))
    oid = cur.lastrowid
    con.executemany(
        "INSERT INTO order_lines VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(oid, l["line"], l["sku"], l["customer_item"], l["description"], l["qty"], l["uom"],
          l["unit_price"], l["extended"], l["list_price"]) for l in clean_lines])
    con.commit()
    return get_order(oid, con)


def approve_order(order_id):
    """Post a staged order and assign its sales order number."""
    with _lock:
        con = connect()
        try:
            row = con.execute("SELECT status FROM orders WHERE id=?", (int(order_id),)).fetchone()
            if not row:
                raise ERPError(f"order #{order_id} not found")
            if row["status"] != "STAGED":
                raise ERPError(f"order #{order_id} is {row['status']}, only STAGED orders can be approved")
            n = con.execute("SELECT value FROM counters WHERE name='so'").fetchone()[0] + 1
            con.execute("UPDATE counters SET value=? WHERE name='so'", (n,))
            con.execute("UPDATE orders SET status='POSTED', so_number=?, posted_at=? WHERE id=?",
                        (f"SO-{n}", datetime.now().isoformat(timespec="seconds"), int(order_id)))
            con.commit()
            return get_order(order_id, con)
        finally:
            con.close()


def reject_order(order_id):
    with _lock:
        con = connect()
        try:
            row = con.execute("SELECT status FROM orders WHERE id=?", (int(order_id),)).fetchone()
            if not row or row["status"] != "STAGED":
                raise ERPError("only STAGED orders can be rejected")
            con.execute("UPDATE orders SET status='REJECTED' WHERE id=?", (int(order_id),))
            con.commit()
            return get_order(order_id, con)
        finally:
            con.close()
