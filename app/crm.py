"""Demo CRM: companies, contacts and an activity log in SQLite."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

from . import checks

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, payment_terms TEXT,
  bill_to TEXT, ship_to TEXT, addresses TEXT, source TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER NOT NULL REFERENCES companies(id),
  name TEXT, email TEXT, phone TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS activities (
  id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER NOT NULL, at TEXT, text TEXT);
"""


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _addr(a, keys=("name", "street", "city", "state", "zip", "store_number")):
    return {k: str((a or {}).get(k) or "") for k in keys if (a or {}).get(k) or k != "store_number"}


class CRM:
    def __init__(self, path, seed_path=None):
        self.path = path
        self.lock = threading.RLock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with self._con() as con:
            con.executescript(SCHEMA)
            empty = con.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0
        if empty and seed_path and os.path.exists(seed_path):
            self.seed(seed_path)

    @contextmanager
    def _con(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def seed(self, seed_path):
        with open(seed_path, encoding="utf-8") as f:
            customers = json.load(f)
        with self.lock, self._con() as con:
            for c in customers:
                known = c.get("crm")
                if not known:
                    continue
                now = _now()
                cur = con.execute(
                    "INSERT INTO companies (name, payment_terms, bill_to, ship_to, addresses, source, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (known["name"], known.get("payment_terms", ""), json.dumps(known.get("bill_to") or {}),
                     json.dumps(known.get("ship_to") or {}), json.dumps(known.get("addresses") or []),
                     "seed", now, now))
                for ct in known.get("contacts") or []:
                    con.execute("INSERT INTO contacts (company_id, name, email, phone, created_at, updated_at)"
                                " VALUES (?,?,?,?,?,?)", (cur.lastrowid, ct["name"], ct["email"], ct["phone"], now, now))

    # ---------------------------------------------------------- reads
    def _company(self, con, row):
        c = dict(row)
        for k in ("bill_to", "ship_to", "addresses"):
            c[k] = json.loads(c[k] or ("[]" if k == "addresses" else "{}"))
        c["contacts"] = [dict(r) for r in con.execute(
            "SELECT * FROM contacts WHERE company_id=? ORDER BY id", (c["id"],))]
        c["activities"] = [dict(r) for r in con.execute(
            "SELECT at, text FROM activities WHERE company_id=? ORDER BY id DESC", (c["id"],))]
        return c

    def companies(self):
        with self._con() as con:
            return [self._company(con, r) for r in con.execute("SELECT * FROM companies ORDER BY name")]

    def company(self, cid):
        with self._con() as con:
            row = con.execute("SELECT * FROM companies WHERE id=?", (int(cid),)).fetchone()
            return self._company(con, row) if row else None

    # ---------------------------------------------------------- writes
    def upsert_from_po(self, po, match, activity=""):
        """Create or update the company and buyer contact from an approved PO."""
        buyer = po.get("buyer") or {}
        bill, ship = _addr(po.get("bill_to")), _addr(po.get("ship_to"))
        now = _now()
        with self.lock, self._con() as con:
            if match.get("status") == "known" and match.get("company_id"):
                cid = int(match["company_id"])
                row = con.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
                addresses = json.loads(row["addresses"] or "[]")
                have = {checks.addr_key(a) for a in addresses}
                for a in (bill, ship):
                    k = checks.addr_key(a)
                    if k and k not in have:
                        addresses.append(a)
                        have.add(k)
                con.execute("UPDATE companies SET payment_terms=?, bill_to=?, ship_to=?, addresses=?, updated_at=? WHERE id=?",
                            (po.get("payment_terms") or row["payment_terms"], json.dumps(bill), json.dumps(ship),
                             json.dumps(addresses), now, cid))
                company_action, name = "Updated", row["name"]
            else:
                name = str(buyer.get("company") or "").strip()
                addresses = [a for a in (bill, ship) if checks.addr_key(a)]
                if len(addresses) == 2 and checks.addr_key(bill) == checks.addr_key(ship):
                    addresses = addresses[:1]
                cur = con.execute(
                    "INSERT INTO companies (name, payment_terms, bill_to, ship_to, addresses, source, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (name, po.get("payment_terms") or "", json.dumps(bill), json.dumps(ship), json.dumps(addresses),
                     "po-pipeline", now, now))
                cid, company_action = cur.lastrowid, "Created"

            contact_action, contact_name = None, str(buyer.get("contact_name") or "").strip()
            email = str(buyer.get("email") or "").strip()
            if contact_name or email:
                existing = None
                if email:
                    existing = con.execute("SELECT * FROM contacts WHERE company_id=? AND lower(email)=lower(?)",
                                           (cid, email)).fetchone()
                if not existing and contact_name:
                    existing = con.execute("SELECT * FROM contacts WHERE company_id=? AND lower(name)=lower(?)",
                                           (cid, contact_name)).fetchone()
                if existing:
                    con.execute("UPDATE contacts SET name=?, email=?, phone=?, updated_at=? WHERE id=?",
                                (contact_name or existing["name"], email or existing["email"],
                                 buyer.get("phone") or existing["phone"], now, existing["id"]))
                    contact_action = "updated"
                else:
                    con.execute("INSERT INTO contacts (company_id, name, email, phone, created_at, updated_at)"
                                " VALUES (?,?,?,?,?,?)", (cid, contact_name, email, buyer.get("phone") or "", now, now))
                    contact_action = "added"
            if activity:
                con.execute("INSERT INTO activities (company_id, at, text) VALUES (?,?,?)", (cid, now, activity))

        who = contact_name or email
        if company_action == "Created":
            summary = f"Created {name}" + (f" + {who}" if who else "")
        else:
            summary = f"Updated {name}" + (f" · contact {who} {contact_action}" if who else "")
        return {"company_action": company_action.lower(), "contact_action": contact_action,
                "company_id": cid, "company": name, "summary": summary}
