"""Deterministic checks and routing for an extracted PO. No AI here.

Every function is pure: data in, result out. The pipeline feeds in the ERP item
master, the CRM companies and the ERP's duplicate-PO lookup.
"""
from __future__ import annotations

import re
from datetime import date

CENT = 0.005

NAME_STOPWORDS = {"inc", "incorporated", "llc", "ltd", "limited", "co", "company", "corp",
                  "corporation", "the", "lp", "llp", "plc", "group"}
STREET_ABBR = {"street": "st", "avenue": "ave", "av": "ave", "road": "rd", "boulevard": "blvd",
               "drive": "dr", "lane": "ln", "parkway": "pkwy", "highway": "hwy", "suite": "ste",
               "north": "n", "south": "s", "east": "e", "west": "w", "place": "pl", "court": "ct",
               "route": "rte", "plaza": "plz", "box": "box", "post": "po", "office": ""}


# ------------------------------------------------------------ normalizers

def norm_name(name):
    s = str(name or "").lower().replace("&", " and ")
    words = re.findall(r"[a-z0-9]+", s)
    words = [w for w in words if w not in NAME_STOPWORDS]
    return " ".join(words)


def norm_street(street):
    s = str(street or "").lower().replace("p.o.", "po")
    words = [STREET_ABBR.get(w, w) for w in re.findall(r"[a-z0-9]+", s)]
    return " ".join(w for w in words if w)


def norm_zip(z):
    return re.sub(r"\D", "", str(z or ""))[:5]


def addr_key(a):
    a = a or {}
    street, z = norm_street(a.get("street")), norm_zip(a.get("zip"))
    return f"{street}|{z}" if street and z else ""


def money(x):
    return round(float(x or 0) + 0.0, 2)


def fmt_money(x):
    return f"${float(x or 0):,.2f}"


# ------------------------------------------------------------ individual checks

def check_totals(po):
    problems, line_issues = [], {}
    total_lines = 0.0
    for i, ln in enumerate(po.get("lines") or []):
        exp = money(float(ln.get("qty") or 0) * float(ln.get("unit_price") or 0))
        if abs(float(ln.get("extended") or 0) - exp) > CENT:
            line_issues[i] = f"qty x price = {fmt_money(exp)}"
            problems.append(f"line {i + 1}: extended {fmt_money(ln.get('extended'))} should be {fmt_money(exp)}")
        total_lines += float(ln.get("extended") or 0)
    subtotal = money(total_lines)
    if abs(float(po.get("subtotal") or 0) - subtotal) > CENT:
        problems.append(f"subtotal {fmt_money(po.get('subtotal'))} but lines add to {fmt_money(subtotal)}")
    exp_total = money(float(po.get("subtotal") or 0) + float(po.get("freight") or 0) + float(po.get("tax") or 0))
    if abs(float(po.get("total") or 0) - exp_total) > CENT:
        problems.append(f"total {fmt_money(po.get('total'))} but subtotal + freight + tax = {fmt_money(exp_total)}")
    ok = not problems
    return {"id": "totals", "status": "ok" if ok else "bad",
            "label": "Totals add up" if ok else "Totals don't add up",
            "detail": "; ".join(problems), "line_issues": line_issues}


def check_skus(po, items, suggest=None):
    missing, line_issues, suggestions = [], {}, {}
    for i, ln in enumerate(po.get("lines") or []):
        sku = re.sub(r"\s+", "", str(ln.get("sku") or "")).upper()
        if sku not in items:
            missing.append(ln.get("sku") or "(blank)")
            sugg = list(suggest(ln.get("sku") or ln.get("description") or "")) if suggest else []
            suggestions[i] = sugg
            hint = f" · did you mean {sugg[0]['sku']}?" if sugg else ""
            line_issues[i] = f"not in item master{hint}"
    ok = not missing
    n = len(po.get("lines") or [])
    return {"id": "skus", "status": "ok" if ok else "bad",
            "label": "All SKUs exist" if ok else f"{len(missing)} of {n} SKUs unknown",
            "detail": "" if ok else "Unknown: " + ", ".join(missing),
            "line_issues": line_issues, "suggestions": suggestions}


def check_prices(po, items):
    diffs, line_issues = [], {}
    for i, ln in enumerate(po.get("lines") or []):
        it = items.get(re.sub(r"\s+", "", str(ln.get("sku") or "")).upper())
        if not it:
            continue
        if abs(float(ln.get("unit_price") or 0) - float(it["list_price"])) > CENT:
            line_issues[i] = f"price list {fmt_money(it['list_price'])}"
            diffs.append(f"{it['sku']} at {fmt_money(ln.get('unit_price'))}, list {fmt_money(it['list_price'])}")
    ok = not diffs
    return {"id": "prices", "status": "ok" if ok else "warn",
            "label": "Prices match price list" if ok else f"{len(diffs)} price{'s' if len(diffs) > 1 else ''} off list",
            "detail": "; ".join(diffs), "line_issues": line_issues}


def check_ship_date(po):
    s = str(po.get("requested_ship_date") or "").strip()
    if not s:
        return {"id": "ship_date", "status": "bad", "label": "No ship date", "detail": "requested ship date is empty"}
    try:
        d = date.fromisoformat(s)
    except ValueError:
        return {"id": "ship_date", "status": "bad", "label": "Ship date unreadable", "detail": s}
    try:
        pod = date.fromisoformat(str(po.get("po_date") or ""))
        if d < pod:
            return {"id": "ship_date", "status": "warn", "label": "Ship date before PO date",
                    "detail": f"ship {s}, PO dated {pod.isoformat()}"}
    except ValueError:
        pass
    return {"id": "ship_date", "status": "ok", "label": "Ship date present", "detail": s}


def match_customer(po, companies):
    """Exact name, then normalized name, then normalized address (street + ZIP)."""
    name = str((po.get("buyer") or {}).get("company") or "").strip()
    for c in companies:
        if name and c["name"].strip() == name:
            return {"status": "known", "method": "exact name", "company_id": c["id"], "company": c["name"]}
    n = norm_name(name)
    for c in companies:
        if n and norm_name(c["name"]) == n:
            return {"status": "known", "method": "normalized name", "company_id": c["id"], "company": c["name"]}
    po_keys = {k for k in (addr_key(po.get("bill_to")), addr_key(po.get("ship_to"))) if k}
    for c in companies:
        c_keys = {addr_key(a) for a in c.get("addresses") or []} - {""}
        if po_keys & c_keys:
            return {"status": "known", "method": "address", "company_id": c["id"], "company": c["name"]}
    return {"status": "new", "method": None, "company_id": None, "company": name}


def customer_chip(match):
    if match["status"] == "known":
        return {"id": "customer", "status": "ok", "label": "Known customer",
                "detail": f"{match['company']} (matched by {match['method']})"}
    return {"id": "customer", "status": "info", "label": "New customer",
            "detail": f"{match['company'] or 'no company name'} is not in the CRM yet"}


def check_duplicate(dup):
    if dup:
        ref = dup.get("so_number") or f"staged order #{dup.get('id')}"
        return {"id": "duplicate", "status": "bad", "label": "PO already in ERP", "detail": ref}
    return {"id": "duplicate", "status": "ok", "label": "New PO number", "detail": ""}


def check_required(po):
    missing = []
    if not str(po.get("po_number") or "").strip():
        missing.append("PO number")
    if not str((po.get("buyer") or {}).get("company") or "").strip():
        missing.append("company")
    if not po.get("lines"):
        missing.append("line items")
    return missing


# ------------------------------------------------------------ all together

def run_checks(po, items, companies, duplicate=None, suggest=None):
    """items: {SKU: item}; companies: CRM companies; duplicate: ERP lookup result or None."""
    totals = check_totals(po)
    skus = check_skus(po, items, suggest)
    prices = check_prices(po, items)
    ship = check_ship_date(po)
    match = match_customer(po, companies)
    dup = check_duplicate(duplicate)
    chips = [totals, skus, prices, customer_chip(match), ship, dup]

    lines = []
    for i, ln in enumerate(po.get("lines") or []):
        it = items.get(re.sub(r"\s+", "", str(ln.get("sku") or "")).upper())
        issues = [d[i] for d in (skus["line_issues"], prices["line_issues"], totals["line_issues"]) if i in d]
        lines.append({"sku_known": bool(it), "list_price": it["list_price"] if it else None,
                      "master_description": it["description"] if it else None,
                      "suggestions": skus["suggestions"].get(i, []), "issues": issues})

    missing = check_required(po)
    blocking = [f"missing {m}" for m in missing]
    if skus["status"] != "ok":
        blocking.append(skus["label"])
    if totals["status"] != "ok":
        blocking.append(totals["label"])
    if dup["status"] != "ok":
        blocking.append(f"PO already in ERP ({dup['detail']})")
    result = {"chips": [{k: v for k, v in c.items() if k not in ("line_issues", "suggestions")} for c in chips],
              "lines": lines, "customer": match, "blocking": blocking}
    result["route"] = route(result)
    return result


def route(result):
    """Where the order goes next. Always to a person: there is no auto-approve path."""
    flags = [c["label"] for c in result["chips"] if c["status"] in ("warn", "bad")]
    if result["blocking"]:
        level = "blocked"
    elif flags:
        level = "attention"
    else:
        level = "clean"
    return {"queue": "human_review", "requires_human": True, "level": level,
            "reasons": result["blocking"] or flags}
