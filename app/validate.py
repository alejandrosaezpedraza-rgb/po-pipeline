"""Strict validator for the PO data contract.

validate_po(obj) -> (clean, errors). `clean` is only meaningful when errors is empty.
Allowed leniency, all documented here: null in a string field becomes "", null freight
or tax becomes 0, a numeric string such as "1,240.00" becomes a number, unknown keys
are dropped. Everything else is an error.
"""
from __future__ import annotations

import json
import re
from datetime import date

PARTY = ("name", "street", "city", "state", "zip")
BUYER = ("company", "contact_name", "email", "phone")
LINE_STR = ("sku", "customer_item", "description", "uom")
LINE_NUM = ("qty", "unit_price", "extended")
TOP_STR = ("po_number", "po_date", "requested_ship_date", "payment_terms", "currency", "notes")
TOP_NUM = ("subtotal", "freight", "tax", "total")


def empty_po():
    return {
        "po_number": "", "po_date": "", "requested_ship_date": "",
        "buyer": {k: "" for k in BUYER},
        "bill_to": {k: "" for k in PARTY},
        "ship_to": dict({k: "" for k in PARTY}, store_number=""),
        "payment_terms": "", "currency": "USD", "lines": [],
        "subtotal": 0, "freight": 0, "tax": 0, "total": 0, "notes": "",
    }


def parse_json_reply(text):
    """Pull one JSON object out of a model reply (tolerates ```json fences and chatter)."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty reply")
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("reply contains no JSON object")
    try:
        return json.loads(t[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"reply is not valid JSON: {e.msg} at char {e.pos}") from None


def _num(v, path, errors, null_default=None):
    if v is None and null_default is not None:
        return null_default
    if isinstance(v, bool):
        errors.append(f"{path}: expected a number, got a boolean")
        return 0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "").replace("$", "")
        try:
            return float(s)
        except ValueError:
            pass
    errors.append(f"{path}: expected a number, got {json.dumps(v)}")
    return 0


def _str(v, path, errors):
    if v is None:
        return ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, str):
        return v.strip()
    errors.append(f"{path}: expected a string, got {type(v).__name__}")
    return ""


def _date(v, path, errors):
    s = _str(v, path, errors)
    if s == "":
        return ""
    try:
        date.fromisoformat(s)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            raise ValueError
    except ValueError:
        errors.append(f"{path}: expected YYYY-MM-DD or empty, got {json.dumps(s)}")
    return s


def _obj(v, keys, path, errors):
    out = {}
    if not isinstance(v, dict):
        errors.append(f"{path}: expected an object")
        return {k: "" for k in keys}
    for k in keys:
        if k not in v:
            errors.append(f"{path}.{k}: missing")
        out[k] = _str(v.get(k), f"{path}.{k}", errors)
    return out


def validate_po(obj):
    errors = []
    if not isinstance(obj, dict):
        return empty_po(), ["top level: expected a JSON object"]
    clean = {}
    for k in TOP_STR:
        if k not in obj:
            errors.append(f"{k}: missing")
    clean["po_number"] = _str(obj.get("po_number"), "po_number", errors)
    clean["po_date"] = _date(obj.get("po_date"), "po_date", errors)
    clean["requested_ship_date"] = _date(obj.get("requested_ship_date"), "requested_ship_date", errors)
    clean["buyer"] = _obj(obj.get("buyer"), BUYER, "buyer", errors)
    clean["bill_to"] = _obj(obj.get("bill_to"), PARTY, "bill_to", errors)
    st = obj.get("ship_to")
    clean["ship_to"] = _obj(st, PARTY, "ship_to", errors)
    clean["ship_to"]["store_number"] = _str((st or {}).get("store_number") if isinstance(st, dict) else "",
                                            "ship_to.store_number", errors)
    clean["payment_terms"] = _str(obj.get("payment_terms"), "payment_terms", errors)
    clean["currency"] = _str(obj.get("currency"), "currency", errors).upper() or "USD"
    if not re.fullmatch(r"[A-Z]{3}", clean["currency"]):
        errors.append(f"currency: expected a 3-letter code, got {json.dumps(clean['currency'])}")
    clean["notes"] = _str(obj.get("notes"), "notes", errors)

    lines = obj.get("lines")
    clean["lines"] = []
    if not isinstance(lines, list):
        errors.append("lines: expected an array")
    elif not lines:
        errors.append("lines: no line items found")
    else:
        for i, ln in enumerate(lines, 1):
            p = f"lines[{i}]"
            if not isinstance(ln, dict):
                errors.append(f"{p}: expected an object")
                continue
            c = {"line": _num(ln.get("line", i), f"{p}.line", errors)}
            for k in LINE_STR:
                if k not in ln:
                    errors.append(f"{p}.{k}: missing")
                c[k] = _str(ln.get(k), f"{p}.{k}", errors)
            for k in LINE_NUM:
                if k not in ln:
                    errors.append(f"{p}.{k}: missing")
                c[k] = _num(ln.get(k), f"{p}.{k}", errors)
            if isinstance(c["line"], float) and c["line"].is_integer():
                c["line"] = int(c["line"])
            if isinstance(c["qty"], float) and c["qty"].is_integer():
                c["qty"] = int(c["qty"])
            if not c["sku"] and not c["description"]:
                errors.append(f"{p}: has neither a SKU nor a description")
            clean["lines"].append(c)

    for k in TOP_NUM:
        if k not in obj:
            errors.append(f"{k}: missing")
        clean[k] = _num(obj.get(k), k, errors, null_default=0 if k in ("freight", "tax") else None)
    return clean, errors
