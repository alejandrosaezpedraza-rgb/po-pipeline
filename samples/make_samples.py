"""Generate the 5 sample POs, their truth files and customers.json.

    python samples/make_samples.py        (needs: pip install reportlab)

All companies, people and addresses are fictional. SKUs, descriptions and prices
come from the demo ERP's item master (erp/seed_data.py), so the checks pass.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from erp.seed_data import COMPANY, PRICES, UOMS  # noqa: E402

try:
    from reportlab.lib.colors import HexColor, black, white
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen.canvas import Canvas
except ImportError:
    sys.exit("make_samples.py needs reportlab:  pip install reportlab")

W, H = letter

# ---------------------------------------------------------------- data

CUSTOMERS = [
    {"slug": "edi-printout", "company": "BRISTOW WHOLESALE FOODS INC", "contact_name": "MARCUS TEALE",
     "email": "mteale@bristowfoods.example", "phone": "(555) 013-7741",
     "bill_to": {"name": "BRISTOW WHOLESALE FOODS INC", "street": "2200 MILL RACE RD", "city": "COLUMBUS", "state": "OH", "zip": "43215"},
     "ship_to": {"name": "BRISTOW DISTRIBUTION CENTER 07", "street": "9100 RICKENBACKER PKWY", "city": "COLUMBUS", "state": "OH", "zip": "43217", "store_number": "DC07"},
     "payment_terms": "Net 45",
     "crm": {"name": "Bristow Wholesale Foods, Inc.", "payment_terms": "Net 45",
             "bill_to": {"name": "Bristow Wholesale Foods, Inc.", "street": "2200 Mill Race Road", "city": "Columbus", "state": "OH", "zip": "43215"},
             "addresses": [{"name": "Bristow Wholesale Foods, Inc.", "street": "2200 Mill Race Road", "city": "Columbus", "state": "OH", "zip": "43215"}],
             "contacts": [{"name": "Marcus Teale", "email": "mteale@bristowfoods.example", "phone": "(555) 013-7741"}]}},
    {"slug": "corporate-form", "company": "Northfield Market Co.", "contact_name": "Dana Reyes",
     "email": "dreyes@northfieldmarket.example", "phone": "(555) 014-2290",
     "bill_to": {"name": "Northfield Market Co.", "street": "1500 Harbor Street", "city": "Duluth", "state": "MN", "zip": "55802"},
     "ship_to": {"name": "Northfield Market Co. Distribution", "street": "77 Lakeshore Drive", "city": "Superior", "state": "WI", "zip": "54880", "store_number": ""},
     "payment_terms": "Net 30", "crm": None},
    {"slug": "store-order", "company": "Pinecrest Hardware & Home", "contact_name": "Priya Natarajan",
     "email": "store0417@pinecresthome.example", "phone": "(555) 018-0417",
     "bill_to": {"name": "Pinecrest Home Centers LLC", "street": "1 Pinecrest Plaza", "city": "Albany", "state": "NY", "zip": "12207"},
     "ship_to": {"name": "Pinecrest Hardware & Home", "street": "880 Route 9", "city": "Fishkill", "state": "NY", "zip": "12524", "store_number": "0417"},
     "payment_terms": "2% 10 Net 30",
     "crm": {"name": "Pinecrest Home Centers LLC", "payment_terms": "2% 10 Net 30",
             "bill_to": {"name": "Pinecrest Home Centers LLC", "street": "1 Pinecrest Plaza", "city": "Albany", "state": "NY", "zip": "12207"},
             "addresses": [{"name": "Pinecrest Home Centers LLC", "street": "1 Pinecrest Plaza", "city": "Albany", "state": "NY", "zip": "12207"}],
             "contacts": [{"name": "Owen Halloway", "email": "ap@pinecresthome.example", "phone": "(555) 018-1000"}]}},
    {"slug": "change-form", "company": "Calloway Logistics Group", "contact_name": "Imani Brooks",
     "email": "ibrooks@calloway-logistics.example", "phone": "(555) 016-8830",
     "bill_to": {"name": "Calloway Logistics Group", "street": "3100 Commerce Blvd", "city": "Memphis", "state": "TN", "zip": "38118"},
     "ship_to": {"name": "Calloway Memphis Cross-Dock", "street": "4400 Airways Blvd", "city": "Memphis", "state": "TN", "zip": "38116", "store_number": ""},
     "payment_terms": "Net 30",
     "crm": {"name": "Calloway Logistics Group", "payment_terms": "Net 30",
             "bill_to": {"name": "Calloway Logistics Group", "street": "3100 Commerce Blvd", "city": "Memphis", "state": "TN", "zip": "38118"},
             "addresses": [{"name": "Calloway Logistics Group", "street": "3100 Commerce Blvd", "city": "Memphis", "state": "TN", "zip": "38118"}],
             "contacts": [{"name": "Imani Brooks", "email": "ibrooks@calloway-logistics.example", "phone": "(555) 016-8830"}]}},
    {"slug": "distributor-po", "company": "Meridian Industrial Distributors", "contact_name": "Tomas Lindqvist",
     "email": "tlindqvist@meridianind.example", "phone": "(555) 019-4482",
     "bill_to": {"name": "Meridian Industrial Distributors", "street": "P.O. Box 4410", "city": "Tulsa", "state": "OK", "zip": "74101"},
     "ship_to": {"name": "Meridian Branch 22 - Oklahoma City", "street": "1850 Industrial Blvd", "city": "Oklahoma City", "state": "OK", "zip": "73108", "store_number": "22"},
     "payment_terms": "Net 30", "crm": None},
]

# lines: (sku, qty, customer_item, description as printed)
ORDERS = {
    "edi-printout": {
        "po_number": "BWF-4500172", "po_date": "2026-10-26", "requested_ship_date": "2026-11-09",
        "freight": 285.00, "tax": 0.0, "notes": "",
        "lines": [("SH-7248", 12, "100-4417", "BOLTLESS SHELVING 72X48X24 5-SHELF"),
                  ("SH-WIRE", 20, "100-4420", "CHROME WIRE SHELVING 72X36X18"),
                  ("CT-0500", 5, "220-0915", "STEEL MESH UTILITY CART 500 LB"),
                  ("AC-CAST4", 10, "220-0990", "REPLACEMENT CASTER SET 4PK")]},
    "corporate-form": {
        "po_number": "88213", "po_date": "2026-10-29", "requested_ship_date": "2026-11-12",
        "freight": 0.0, "tax": 0.0, "notes": "Deliver to Receiving Dock B, 7am-3pm weekdays.",
        "lines": [("CT-1200", 6, "NM-40121", "Heavy-Duty Platform Truck Cart, 1200 lb"),
                  ("CT-0800", 6, "NM-40118", "Utility Platform Cart, 800 lb"),
                  ("CT-0500", 2, "NM-40110", "Steel Mesh Utility Cart, 500 lb"),
                  ("CT-0350", 2, "NM-40102", "Folding Hand Cart, 350 lb")]},
    "store-order": {
        "po_number": "PHH-0417-1103", "po_date": "2026-10-30", "requested_ship_date": "2026-11-16",
        "freight": 125.00, "tax": 349.28, "notes": "Call the store before delivery, rear dock.",
        "lines": [("WB-6030", 3, "", "Steel workbench 60x30 hardwood top"),
                  ("WB-PEG", 6, "", "Pegboard back panel 60\""),
                  ("WB-LGT", 6, "", "LED work light kit"),
                  ("SH-6036", 4, "", "Boltless shelving 60x36x18, 4 shelf"),
                  ("CT-SRV", 2, "", "Two-shelf service cart")]},
    "change-form": {
        "po_number": "CL-30417", "po_date": "2026-10-19", "requested_ship_date": "2026-11-20",
        "freight": 450.00, "tax": 0.0, "notes": "Change notice 2 (2026-10-28): line 1 qty 3 to 4, line 3 qty 5 to 3, ship date moved from 2026-11-13 to 2026-11-20.",
        "lines": [("CT-2000", 4, "", "Industrial Flatbed Cart, 2000 lb"),
                  ("CT-1200", 2, "", "Heavy-Duty Platform Truck Cart, 1200 lb"),
                  ("WB-ADJ", 3, "", "Height-Adjustable Workbench 72x30"),
                  ("SH-RACK", 6, "", "Pallet Rack Starter Bay, 96 in")],
        "original_qty": [3, 2, 5, 6], "original_ship": "2026-11-13", "change_date": "2026-10-28"},
    "distributor-po": {
        "po_number": "MID-2026-009482", "po_date": "2026-10-27", "requested_ship_date": "2026-11-18",
        "freight": 785.00, "tax": 0.0, "notes": "Resale, tax exempt certificate on file. Show PO number on all packing lists.",
        "lines": [("WB-7236H", 4, "MID-55120", "HD WORKBENCH 72X36 W/DRAWERS"),
                  ("WB-7236", 6, "MID-55118", "STEEL WORKBENCH 72X36 HARDWOOD TOP"),
                  ("WB-4824", 4, "MID-55102", "COMPACT WORKBENCH 48X24"),
                  ("WB-ESD", 2, "MID-55140", "ESD SAFE WORKBENCH 60X30"),
                  ("SH-8448", 10, "MID-31207", "WIDE-SPAN SHELVING 84X48X24 5 SHELF"),
                  ("SH-ADD", 10, "MID-31208", "ADD-ON SHELVING UNIT 72X48X24"),
                  ("SH-CAB", 3, "MID-31260", "STEEL STORAGE CABINET 78X36X24"),
                  ("CT-TUB", 2, "MID-12044", "TILT BIN CART 12 CU FT")]},
}


def build_truth(c, o):
    lines = []
    for i, (sku, qty, citem, desc) in enumerate(o["lines"], 1):
        price = PRICES[sku]
        lines.append({"line": i, "sku": sku, "customer_item": citem, "description": desc, "qty": qty,
                      "uom": UOMS[sku], "unit_price": price, "extended": round(qty * price, 2)})
    subtotal = round(sum(l["extended"] for l in lines), 2)
    return {
        "po_number": o["po_number"], "po_date": o["po_date"], "requested_ship_date": o["requested_ship_date"],
        "buyer": {"company": c["company"], "contact_name": c["contact_name"], "email": c["email"], "phone": c["phone"]},
        "bill_to": c["bill_to"], "ship_to": c["ship_to"], "payment_terms": c["payment_terms"], "currency": "USD",
        "lines": lines, "subtotal": subtotal, "freight": o["freight"], "tax": o["tax"],
        "total": round(subtotal + o["freight"] + o["tax"], 2), "notes": o["notes"],
    }


# ---------------------------------------------------------------- drawing helpers

def m(x):
    return f"{x:,.2f}"


def us_date(iso, two_digit=False):
    y, mo, d = iso.split("-")
    return f"{mo}/{d}/{y[2:] if two_digit else y}"


def txt(c, x, y, s, font="Helvetica", size=9, color=black, align="left"):
    c.setFont(font, size)
    c.setFillColor(color)
    if align == "right":
        c.drawRightString(x, y, s)
    elif align == "center":
        c.drawCentredString(x, y, s)
    else:
        c.drawString(x, y, s)


def rect(c, x, y, w, h, stroke=black, fill=None, lw=0.6):
    c.setLineWidth(lw)
    if stroke is not None:
        c.setStrokeColor(stroke)
    if fill is not None:
        c.setFillColor(fill)
    c.rect(x, y, w, h, stroke=1 if stroke is not None else 0, fill=1 if fill is not None else 0)


def addr_lines(a):
    out = [a["name"], a["street"], f"{a['city']}, {a['state']} {a['zip']}"]
    return out


# ---------------------------------------------------------------- 1. EDI printout

def render_edi(path, c_, t):
    c = Canvas(path, pagesize=letter)
    c.setTitle(f"EDI 850 {t['po_number']}")
    green = HexColor("#e6f2e6")
    for i in range(0, 60):  # green-bar paper
        if i % 2 == 0:
            rect(c, 30, H - 60 - (i + 1) * 12, W - 60, 12, stroke=None, fill=green)
    font, sz = "Courier", 8.2
    rows = [
        ("*** EDI TRANSLATOR PRINTOUT ***   TRANSACTION SET 850 (PURCHASE ORDER)", ""),
        (f"RECEIVED 2026-10-26 06:14:09   SENDER ID: BRISTOWWF   RECEIVER ID: CORVANESW", ""),
        ("-" * 64, "-" * 34),
        ("SEGMENT", "INTERPRETATION"),
        ("-" * 64, "-" * 34),
        ("ST*850*0412", "Transaction set header"),
        (f"BEG*00*SA*{t['po_number']}**{t['po_date'].replace('-', '')}", f"Original PO {t['po_number']}"),
        ("CUR*BY*USD", "Currency USD"),
        ("ITD*01*3*****45*****NET 45", "Terms: NET 45"),
        (f"DTM*010*{t['requested_ship_date'].replace('-', '')}", "Requested ship date"),
        (f"N1*BY*{c_['company']}*92*BWF01", "Buying party"),
        (f"PER*BD*{c_['contact_name']}*TE*5550137741*EM*{c_['email'].upper()}", "Buyer contact"),
        (f"N1*BT*{t['bill_to']['name']}", "Bill-to party"),
        (f"N3*{t['bill_to']['street']}", ""),
        (f"N4*{t['bill_to']['city']}*{t['bill_to']['state']}*{t['bill_to']['zip']}", ""),
        (f"N1*ST*{t['ship_to']['name']}*92*{t['ship_to']['store_number']}", "Ship-to party, location DC07"),
        (f"N3*{t['ship_to']['street']}", ""),
        (f"N4*{t['ship_to']['city']}*{t['ship_to']['state']}*{t['ship_to']['zip']}", ""),
    ]
    for l in t["lines"]:
        rows.append((f"PO1*{l['line']}*{l['qty']}*{l['uom']}*{l['unit_price']:.2f}**VP*{l['sku']}*BP*{l['customer_item']}",
                     f"Line {l['line']}: {l['qty']} {l['uom']} @ {l['unit_price']:.2f}"))
        rows.append((f"PID*F****{l['description']}", f"  ext {m(l['extended'])}"))
    rows += [
        (f"SAC*C*D240***{int(round(t['freight'] * 100))}", f"Freight charge {m(t['freight'])}"),
        (f"AMT*TT*{t['total']:.2f}", f"Total amount {m(t['total'])}"),
        (f"CTT*{len(t['lines'])}", f"{len(t['lines'])} line items"),
        ("SE*27*0412", "Transaction set trailer"),
        ("", ""),
        ("MERCHANDISE TOTAL ............ " + m(t["subtotal"]), ""),
        ("*** END OF TRANSACTION ***", ""),
    ]
    y = H - 70
    for left, right in rows:
        txt(c, 38, y, left, font, sz)
        txt(c, 390, y, right, font, sz, HexColor("#333333"))
        y -= 12
    txt(c, 38, 40, "PRINTED BY EDIVIEW 4.2   PAGE 1 OF 1", font, 7)
    c.save()


# ---------------------------------------------------------------- 2. designed corporate form

def render_corporate(path, c_, t):
    c = Canvas(path, pagesize=letter)
    c.setTitle(f"Purchase Order {t['po_number']}")
    navy, teal, pale = HexColor("#16324f"), HexColor("#2a9d8f"), HexColor("#eef3f7")
    rect(c, 0, H - 96, W, 96, stroke=None, fill=navy)
    c.setFillColor(teal)
    c.circle(58, H - 48, 20, stroke=0, fill=1)
    c.setFillColor(white)
    p = c.beginPath()
    p.moveTo(46, H - 58); p.lineTo(58, H - 34); p.lineTo(70, H - 58); p.close()
    c.drawPath(p, stroke=0, fill=1)
    txt(c, 88, H - 44, "Northfield Market Co.", "Helvetica-Bold", 17, white)
    txt(c, 88, H - 60, "Fresh foods · Since 1987 · 1500 Harbor Street, Duluth, MN 55802", "Helvetica", 8.5, HexColor("#c7d6e5"))
    txt(c, W - 40, H - 42, "PURCHASE ORDER", "Helvetica-Bold", 20, white, "right")
    txt(c, W - 40, H - 62, f"No. {t['po_number']}", "Helvetica", 11, HexColor("#c7d6e5"), "right")

    y0 = H - 130
    boxes = [("VENDOR", [COMPANY["name"], COMPANY["street"], f"{COMPANY['city']}, {COMPANY['state']} {COMPANY['zip']}"]),
             ("BILL TO", addr_lines(t["bill_to"])), ("SHIP TO", addr_lines(t["ship_to"]))]
    bw = (W - 80 - 20) / 3
    for i, (label, lines) in enumerate(boxes):
        x = 40 + i * (bw + 10)
        rect(c, x, y0 - 62, bw, 70, stroke=HexColor("#c9d3dd"), fill=pale)
        txt(c, x + 10, y0 - 6, label, "Helvetica-Bold", 7.5, teal)
        for j, s in enumerate(lines):
            txt(c, x + 10, y0 - 20 - j * 12, s, "Helvetica", 8.8)

    fields = [("PO Date", "October 29, 2026"), ("Requested Ship Date", "November 12, 2026"),
              ("Payment Terms", t["payment_terms"]), ("Ship Via", "Best way, freight prepaid"),
              ("Buyer", c_["contact_name"]), ("Phone", c_["phone"]), ("Email", c_["email"])]
    fy = y0 - 90
    fw = (W - 80) / 4
    for i, (k, v) in enumerate(fields):
        x, yy = 40 + (i % 4) * fw, fy - (i // 4) * 30
        txt(c, x, yy, k.upper(), "Helvetica", 6.8, HexColor("#6b7c8f"))
        txt(c, x, yy - 12, v, "Helvetica-Bold" if i < 2 else "Helvetica", 9)

    ty = fy - 80
    cols = [("#", 40, "left"), ("Our Item", 62, "left"), ("Vendor SKU", 120, "left"), ("Description", 182, "left"),
            ("Qty", 400, "right"), ("UOM", 412, "left"), ("Unit Price", 494, "right"), ("Amount", W - 40, "right")]
    rect(c, 36, ty - 5, W - 72, 18, stroke=None, fill=navy)
    for name, x, al in cols:
        txt(c, x, ty, name, "Helvetica-Bold", 8, white, al)
    y = ty - 22
    for i, l in enumerate(t["lines"]):
        if i % 2:
            rect(c, 36, y - 6, W - 72, 20, stroke=None, fill=pale)
        vals = [str(l["line"]), l["customer_item"], l["sku"], l["description"], str(l["qty"]), l["uom"],
                m(l["unit_price"]), m(l["extended"])]
        for (name, x, al), v in zip(cols, vals):
            txt(c, x, y, v, "Helvetica", 8.8, black, al)
        y -= 20
    c.setStrokeColor(HexColor("#c9d3dd"))
    c.line(36, y + 8, W - 36, y + 8)
    for k, v, bold in (("Subtotal", t["subtotal"], False), ("Freight", t["freight"], False),
                       ("Sales Tax", t["tax"], False), ("Order Total", t["total"], True)):
        y -= 16
        txt(c, 494, y, k, "Helvetica-Bold" if bold else "Helvetica", 9.5 if bold else 9, black, "right")
        txt(c, W - 40, y, "$" + m(v), "Helvetica-Bold" if bold else "Helvetica", 9.5 if bold else 9, black, "right")
    y -= 14
    txt(c, W - 40, y, "All amounts in USD", "Helvetica", 7.5, HexColor("#6b7c8f"), "right")

    y -= 30
    txt(c, 40, y, "SPECIAL INSTRUCTIONS", "Helvetica-Bold", 7.5, teal)
    txt(c, 40, y - 13, t["notes"], "Helvetica", 9)
    txt(c, 40, y - 26, "Reference our PO number on all invoices and packing slips.", "Helvetica", 9)
    c.setStrokeColor(black)
    c.line(W - 240, 110, W - 40, 110)
    txt(c, W - 240, 98, f"Authorized: {c_['contact_name']}, Purchasing Manager", "Helvetica", 8)
    rect(c, 0, 0, W, 30, stroke=None, fill=navy)
    txt(c, W / 2, 12, "Northfield Market Co. · Purchasing Department · page 1 of 1", "Helvetica", 7.5, HexColor("#c7d6e5"), "center")
    c.save()


# ---------------------------------------------------------------- 3. store-level order

def render_store(path, c_, t):
    c = Canvas(path, pagesize=letter)
    c.setTitle(f"Store order {t['po_number']}")
    red = HexColor("#9b2d20")
    txt(c, 40, H - 50, "PINECREST", "Times-Bold", 26, red)
    txt(c, 40, H - 66, "HARDWARE & HOME", "Helvetica-Bold", 10, HexColor("#555555"))
    rect(c, W - 170, H - 78, 130, 50, stroke=red, lw=1.5)
    txt(c, W - 105, H - 45, "STORE #", "Helvetica-Bold", 8, red, "center")
    txt(c, W - 105, H - 70, t["ship_to"]["store_number"], "Helvetica-Bold", 22, black, "center")
    txt(c, 40, H - 100, "STORE ORDER FORM  ·  vendor direct ship", "Helvetica-Bold", 12)
    c.setLineWidth(1.2)
    c.line(40, H - 106, W - 40, H - 106)

    y = H - 128
    txt(c, 40, y, "Order type:", "Helvetica", 9)
    for i, (lab, on) in enumerate((("Stock replenishment", False), ("Special order", True), ("Seasonal", False))):
        x = 100 + i * 130
        rect(c, x, y - 2, 9, 9)
        if on:
            txt(c, x + 1, y - 1, "X", "Helvetica-Bold", 9)
        txt(c, x + 14, y, lab, "Helvetica", 9)
    y -= 26
    pairs = [("Order no.", t["po_number"]), ("Order date", us_date(t["po_date"], True)),
             ("NEED BY", us_date(t["requested_ship_date"], True)), ("Vendor", COMPANY["name"])]
    for i, (k, v) in enumerate(pairs):
        x = 40 + i * 135
        txt(c, x, y, k, "Helvetica", 7.5, HexColor("#777777"))
        txt(c, x, y - 14, v, "Courier-Bold", 10.5)
        c.setLineWidth(0.5)
        c.line(x, y - 18, x + 120, y - 18)

    y -= 50
    txt(c, 40, y, "DELIVER TO STORE", "Helvetica-Bold", 8, red)
    txt(c, 310, y, "INVOICE TO (CORPORATE A/P)", "Helvetica-Bold", 8, red)
    st, bt = t["ship_to"], t["bill_to"]
    for j, s in enumerate([f"{st['name']} #{st['store_number']}", st["street"], f"{st['city']}, {st['state']} {st['zip']}"]):
        txt(c, 40, y - 14 - j * 12, s, "Helvetica", 9.5)
    for j, s in enumerate([bt["name"], "Attn: Accounts Payable", bt["street"], f"{bt['city']}, {bt['state']} {bt['zip']}"]):
        txt(c, 310, y - 14 - j * 12, s, "Helvetica", 9.5)
    y -= 70
    txt(c, 40, y, f"Store manager: {c_['contact_name']}    Tel {c_['phone']}    {c_['email']}", "Helvetica", 9)
    txt(c, 40, y - 13, f"Terms: {t['payment_terms']} (per vendor agreement)", "Helvetica", 9)

    y -= 40
    cols = [("QTY", 40, 50), ("VENDOR #", 90, 80), ("DESCRIPTION", 170, 230), ("EACH", 400, 70), ("TOTAL", 470, 102)]
    for name, x, w in cols:
        rect(c, x, y - 4, w, 16, fill=HexColor("#f1e3df"))
        txt(c, x + 4, y + 1, name, "Helvetica-Bold", 8)
    for l in t["lines"]:
        y -= 20
        vals = [str(l["qty"]), l["sku"], l["description"], m(l["unit_price"]), m(l["extended"])]
        for (name, x, w), v in zip(cols, vals):
            rect(c, x, y - 6, w, 20)
            if name in ("EACH", "TOTAL"):
                txt(c, x + w - 4, y, v, "Courier", 10, black, "right")
            else:
                txt(c, x + 4, y, v, "Courier", 10)
    for k, v in (("Merch. subtotal", t["subtotal"]), ("Delivery charge", t["freight"]),
                 ("Sales tax 8%", t["tax"]), ("ORDER TOTAL", t["total"])):
        y -= 18
        txt(c, 466, y, k, "Helvetica-Bold" if k == "ORDER TOTAL" else "Helvetica", 9, black, "right")
        txt(c, 568, y, m(v), "Courier-Bold" if k == "ORDER TOTAL" else "Courier", 10, black, "right")

    c.saveState()
    c.translate(60, 120)
    c.rotate(4)
    txt(c, 0, 0, "Pls call the store before delivery - use REAR dock!", "Courier-Oblique", 12, HexColor("#1f3c88"))
    txt(c, 0, -15, "      thx - P.N.", "Courier-Oblique", 12, HexColor("#1f3c88"))
    c.restoreState()
    txt(c, 40, 50, "Store copy (white) · Corporate (yellow) · Vendor (pink)      Form PH-114 rev 3", "Helvetica", 7, HexColor("#888888"))
    c.save()


# ---------------------------------------------------------------- 4. change form

def render_change(path, c_, t, o):
    c = Canvas(path, pagesize=letter)
    c.setTitle(f"PO change {t['po_number']}")
    red, grey = HexColor("#c0392b"), HexColor("#666666")
    txt(c, 40, H - 48, "CALLOWAY LOGISTICS GROUP", "Helvetica-Bold", 14)
    txt(c, 40, H - 62, f"{t['bill_to']['street']} · {t['bill_to']['city']}, {t['bill_to']['state']} {t['bill_to']['zip']}", "Helvetica", 8.5, grey)
    rect(c, 40, H - 102, W - 80, 28, stroke=None, fill=red)
    txt(c, W / 2, H - 93, "PURCHASE ORDER CHANGE NOTICE  ·  CHANGE NO. 2", "Helvetica-Bold", 13, white, "center")
    txt(c, 40, H - 120, "This notice amends the purchase order below. Values in the REVISED columns replace the original values.",
        "Helvetica-Oblique", 8.5)

    grid = [("PO NUMBER", t["po_number"]), ("PO DATE", us_date(t["po_date"])), ("CHANGE DATE", us_date(o["change_date"])),
            ("BUYER", c_["contact_name"]), ("PHONE", c_["phone"]), ("EMAIL", c_["email"]),
            ("VENDOR", COMPANY["name"]), ("TERMS", t["payment_terms"]), ("CURRENCY", "USD")]
    gy, gw = H - 140, (W - 80) / 3
    for i, (k, v) in enumerate(grid):
        x, y = 40 + (i % 3) * gw, gy - (i // 3) * 30
        rect(c, x, y - 22, gw, 30)
        txt(c, x + 5, y, k, "Helvetica", 6.5, grey)
        txt(c, x + 5, y - 15, v, "Helvetica-Bold", 9)

    y = gy - 110
    txt(c, 40, y, "SHIP TO", "Helvetica-Bold", 8)
    for j, s in enumerate(addr_lines(t["ship_to"])):
        txt(c, 40, y - 13 - j * 11, s, "Helvetica", 9)
    txt(c, 310, y, "HEADER CHANGES", "Helvetica-Bold", 8)
    txt(c, 310, y - 14, "Requested ship date", "Helvetica", 9)
    txt(c, 410, y - 14, us_date(o["original_ship"]), "Helvetica", 9, grey)
    c.setStrokeColor(grey)
    c.line(408, y - 11, 462, y - 11)
    txt(c, 470, y - 14, "->  " + us_date(t["requested_ship_date"]), "Helvetica-Bold", 9, red)

    y -= 70
    cols = [("LN", 44, "left"), ("ITEM", 66, "left"), ("DESCRIPTION", 124, "left"), ("UOM", 300, "left"),
            ("UNIT PRICE", 380, "right"), ("ORIG QTY", 432, "right"), ("REVISED QTY", 492, "right"), ("REVISED EXT", W - 44, "right")]
    rect(c, 40, y - 5, W - 80, 17, fill=HexColor("#eeeeee"))
    for name, x, al in cols:
        txt(c, x, y, name, "Helvetica-Bold", 7, black, al)
    orig_sub = 0
    for l, oq in zip(t["lines"], o["original_qty"]):
        y -= 19
        orig_sub += oq * l["unit_price"]
        changed = oq != l["qty"]
        vals = [str(l["line"]), l["sku"], l["description"], l["uom"], m(l["unit_price"]), str(oq), str(l["qty"]), m(l["extended"])]
        for (name, x, al), v in zip(cols, vals):
            f = "Helvetica-Bold" if (changed and name == "REVISED QTY") else "Helvetica"
            col = red if (changed and name == "REVISED QTY") else (grey if name == "ORIG QTY" else black)
            txt(c, x, y, v, f, 8.5, col, al)
        if changed:
            c.setStrokeColor(grey)
            c.line(410, y + 3, 434, y + 3)
            txt(c, W - 44, y - 9, "CHANGED", "Helvetica-Bold", 6, red, "right")
        c.setStrokeColor(HexColor("#dddddd"))
        c.line(40, y - 12, W - 40, y - 12)

    y -= 40
    txt(c, 330, y, "ORIGINAL", "Helvetica-Bold", 7.5, grey, "right")
    txt(c, W - 44, y, "REVISED", "Helvetica-Bold", 7.5, red, "right")
    rows = (("Merchandise", orig_sub, t["subtotal"]), ("Freight", t["freight"], t["freight"]),
            ("Tax", t["tax"], t["tax"]), ("PO TOTAL", orig_sub + t["freight"] + t["tax"], t["total"]))
    for k, a, b in rows:
        y -= 15
        bold = k == "PO TOTAL"
        txt(c, 200, y, k, "Helvetica-Bold" if bold else "Helvetica", 9)
        txt(c, 330, y, m(a), "Helvetica", 9, grey, "right")
        txt(c, W - 44, y, m(b), "Helvetica-Bold" if bold else "Helvetica", 9, black, "right")

    y -= 40
    txt(c, 40, y, "REASON FOR CHANGE: demand update from Memphis cross-dock; line 3 reduced, line 1 increased.", "Helvetica", 8.5)
    txt(c, 40, y - 12, "All other terms and conditions of the original purchase order remain unchanged.", "Helvetica", 8.5)
    c.setStrokeColor(black)
    c.line(40, 90, 240, 90)
    txt(c, 40, 78, f"{c_['contact_name']}, Procurement", "Helvetica", 8)
    txt(c, W - 40, 40, "Form CL-PO-CHG · page 1/1", "Helvetica", 7, grey, "right")
    c.save()


# ---------------------------------------------------------------- 5. distributor PO (2 pages)

def render_distributor(path, c_, t):
    c = Canvas(path, pagesize=letter)
    c.setTitle(f"PO {t['po_number']}")
    pages = 2

    def header(page):
        txt(c, 40, H - 50, "MERIDIAN", "Times-Bold", 22)
        txt(c, 40, H - 64, "INDUSTRIAL DISTRIBUTORS", "Times-Roman", 10)
        txt(c, 40, H - 78, f"{t['bill_to']['street']} · {t['bill_to']['city']}, {t['bill_to']['state']} {t['bill_to']['zip']}", "Times-Roman", 8.5)
        txt(c, W - 40, H - 46, "PURCHASE ORDER", "Times-Bold", 16, black, "right")
        cells = [("P.O. No.", t["po_number"]), ("Date", "27-Oct-2026"), ("Page", f"{page} of {pages}")]
        for i, (k, v) in enumerate(cells):
            x = W - 280 + i * 80 + (0 if i == 0 else 40)
            w = 120 if i == 0 else 80
            rect(c, x, H - 90, w, 32)
            txt(c, x + 4, H - 68, k, "Times-Roman", 7)
            txt(c, x + 4, H - 84, v, "Times-Bold", 9.5)
        c.setLineWidth(1.5)
        c.line(40, H - 98, W - 40, H - 98)
        c.setLineWidth(0.5)
        c.line(40, H - 101, W - 40, H - 101)

    cols = [("Ln", 44, "left"), ("Qty", 80, "right"), ("U/M", 88, "left"), ("Our Part #", 116, "left"),
            ("Mfr Part #", 180, "left"), ("Description", 240, "left"), ("Unit Cost", 500, "right"), ("Ext. Cost", W - 44, "right")]

    def table_head(y):
        rect(c, 40, y - 5, W - 80, 16)
        for name, x, al in cols:
            txt(c, x, y, name, "Times-Bold", 8.5, black, al)

    def line_row(y, l):
        vals = [str(l["line"]), str(l["qty"]), l["uom"], l["customer_item"], l["sku"], l["description"],
                m(l["unit_price"]), m(l["extended"])]
        for (name, x, al), v in zip(cols, vals):
            txt(c, x, y, v, "Times-Roman", 9, black, al)

    header(1)
    y = H - 122
    txt(c, 40, y, "VENDOR", "Times-Bold", 8)
    txt(c, 220, y, "SHIP TO", "Times-Bold", 8)
    txt(c, 410, y, "INVOICE TO", "Times-Bold", 8)
    ven = [f"{COMPANY['name']}  (Vendor # V-20117)", COMPANY["street"], f"{COMPANY['city']}, {COMPANY['state']} {COMPANY['zip']}"]
    st = t["ship_to"]
    shp = [st["name"], st["street"], f"{st['city']}, {st['state']} {st['zip']}", f"Branch No.: {st['store_number']}"]
    bil = [t["bill_to"]["name"], "Accounts Payable", t["bill_to"]["street"], f"{t['bill_to']['city']}, {t['bill_to']['state']} {t['bill_to']['zip']}"]
    for col_x, lines in ((40, ven), (220, shp), (410, bil)):
        for j, s in enumerate(lines):
            txt(c, col_x, y - 13 - j * 11, s, "Times-Roman", 9)
    y -= 72
    strip = [("Buyer", c_["contact_name"]), ("Phone", c_["phone"]), ("E-mail", c_["email"]), ("Ship Via", "LTL - Best Way"),
             ("F.O.B.", "Origin"), ("Terms", t["payment_terms"]), ("Req. Ship", us_date(t["requested_ship_date"])), ("Confirm To", "Buyer")]
    sw = (W - 80) / 4
    for i, (k, v) in enumerate(strip):
        x, yy = 40 + (i % 4) * sw, y - (i // 4) * 26
        rect(c, x, yy - 18, sw, 26)
        txt(c, x + 4, yy, k, "Times-Roman", 7)
        txt(c, x + 4, yy - 12, v, "Times-Bold", 8.5)
    y -= 70
    table_head(y)
    for l in t["lines"][:6]:
        y -= 18
        line_row(y, l)
    txt(c, W - 44, 60, "Continued on page 2", "Times-Italic", 9, black, "right")
    c.showPage()

    header(2)
    y = H - 130
    table_head(y)
    for l in t["lines"][6:]:
        y -= 18
        line_row(y, l)
    y -= 12
    c.line(380, y, W - 40, y)
    for k, v in (("Merchandise Total", t["subtotal"]), ("Freight", t["freight"]),
                 ("Sales Tax (resale - exempt)", t["tax"]), ("P.O. TOTAL  USD", t["total"])):
        y -= 15
        txt(c, 500, y, k, "Times-Bold" if "TOTAL  USD" in k else "Times-Roman", 9, black, "right")
        txt(c, W - 44, y, m(v), "Times-Bold" if "TOTAL  USD" in k else "Times-Roman", 9, black, "right")
    y -= 40
    txt(c, 40, y, "NOTES", "Times-Bold", 9)
    txt(c, 40, y - 13, "Tax exempt: resale certificate on file. Show our P.O. number on all packing lists and the bill of lading.", "Times-Roman", 9)
    y -= 45
    txt(c, 40, y, "TERMS AND CONDITIONS", "Times-Bold", 9)
    terms = [
        "1. Acceptance. Shipment of any goods against this order constitutes acceptance of these terms.",
        "2. Pricing. Prices are firm for the life of this order unless changed by a written change notice from the Buyer.",
        "3. Shipping. Partial shipments require prior approval. Each carton must show the P.O. number and Our Part #.",
        "4. Invoicing. Invoice each shipment separately to the Invoice To address. Do not include freight not shown above.",
        "5. Inspection. Goods are subject to inspection on receipt; nonconforming goods may be returned at Vendor's cost.",
        "6. Warranty. Vendor warrants goods free from defects in material and workmanship for one year from delivery.",
    ]
    for j, s in enumerate(terms):
        txt(c, 40, y - 13 - j * 12, s, "Times-Roman", 8.2)
    c.line(W - 240, 100, W - 40, 100)
    txt(c, W - 240, 88, "Authorized signature, Meridian Purchasing", "Times-Italic", 8)
    c.save()


# ---------------------------------------------------------------- main

def main():
    os.makedirs(os.path.join(HERE, "truth"), exist_ok=True)
    renderers = {"edi-printout": render_edi, "corporate-form": render_corporate, "store-order": render_store,
                 "change-form": lambda p, c_, t: render_change(p, c_, t, ORDERS["change-form"]),
                 "distributor-po": render_distributor}
    for c_ in CUSTOMERS:
        slug = c_["slug"]
        t = build_truth(c_, ORDERS[slug])
        renderers[slug](os.path.join(HERE, f"{slug}.pdf"), c_, t)
        with open(os.path.join(HERE, "truth", f"{slug}.json"), "w", encoding="utf-8") as f:
            json.dump(t, f, indent=2)
        print(f"{slug}: PO {t['po_number']} · {len(t['lines'])} lines · ${t['total']:,.2f}")
    with open(os.path.join(HERE, "customers.json"), "w", encoding="utf-8") as f:
        json.dump(CUSTOMERS, f, indent=2)


if __name__ == "__main__":
    main()
