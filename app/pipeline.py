"""The pipeline: arrive -> read (Claude) -> checks -> human review -> ERP | CRM | folder -> email.

Only the read step uses AI. Nothing is written to the ERP or the CRM until accept().
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime

from . import checks, extract, sender
from .erp_client import ERPRefused, ERPUnavailable
from .validate import validate_po

NODES = ("arrive", "read", "review", "erp", "crm", "folder", "email")
BRANCHES = ("erp", "crm", "folder")


class PipelineError(Exception):
    def __init__(self, message, code=400, details=None):
        super().__init__(message)
        self.code, self.details = code, details or []


def _now():
    return datetime.now().isoformat(timespec="seconds")


def fmt_money(x):
    return f"${float(x or 0):,.2f}"


def fmt_date(s, year=False):
    try:
        d = date.fromisoformat(s)
    except (TypeError, ValueError):
        return s or ""
    return d.strftime("%b %d, %Y" if year else "%b %d").replace(" 0", " ")


def safe_name(s, fallback="unknown"):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(s or "")).strip().rstrip(". ")
    return s[:80] or fallback


DERIVED = {"extended", "subtotal", "total"}  # recomputed from other fields, so not counted as edits


def count_changes(a, b):
    """Number of leaf values a person changed between two PO dicts (lines compared by position)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return sum(count_changes(a.get(k), b.get(k)) for k in set(a) | set(b) if k not in DERIVED)
    if isinstance(a, list) and isinstance(b, list):
        n = sum(count_changes(x, y) for x, y in zip(a, b))
        longer = a[len(b):] if len(a) > len(b) else b[len(a):]
        return n + len(longer)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return int(abs(float(a) - float(b)) > 0.0001)
    return int((a if a is not None else "") != (b if b is not None else ""))


def summary_line(po):
    n = len(po["lines"])
    s = f"{n} line{'s' if n != 1 else ''} · {fmt_money(po['total'])}"
    if po.get("requested_ship_date"):
        s += f" · ship {fmt_date(po['requested_ship_date'])}"
    return s


class Pipeline:
    def __init__(self, cfg, erp, crm, extractor=None, backend=None):
        self.cfg, self.erp, self.crm = cfg, erp, crm
        self.extractor = extractor or extract.extract
        self.backend = backend            # tests inject a stub backend here
        self.state_dir = cfg["STATE_DIR"]
        self.customers_dir = cfg["CUSTOMERS_DIR"]
        self.lock = threading.RLock()
        self.listeners = []
        self.run, self.log = None, []
        self.mailbox = {"state": "off"}
        self._load()

    # ------------------------------------------------------------ state
    @property
    def state_file(self):
        return os.path.join(self.state_dir, "run.json")

    def _load(self):
        try:
            with open(self.state_file, encoding="utf-8") as f:
                data = json.load(f)
            self.run, self.log = data.get("run"), data.get("log") or []
        except (OSError, ValueError):
            return
        if self.run:
            for n in self.run["nodes"].values():
                if n["status"] == "running":
                    n.update(status="error", error="Interrupted: the app restarted while this step was running")

    def _save(self):
        os.makedirs(self.state_dir, exist_ok=True)
        tmp = self.state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"run": self.run, "log": self.log}, f, indent=1)
        os.replace(tmp, self.state_file)

    def subscribe(self, fn):
        with self.lock:
            self.listeners.append(fn)

    def unsubscribe(self, fn):
        with self.lock:
            if fn in self.listeners:
                self.listeners.remove(fn)

    def snapshot(self):
        with self.lock:
            return {"run": copy.deepcopy(self.run), "log": list(self.log[-200:]), "mailbox": dict(self.mailbox)}

    def _changed(self):
        self._save()
        snap = self.snapshot()
        for fn in list(self.listeners):
            try:
                fn(snap)
            except Exception:
                pass

    def _log(self, msg, level="info"):
        self.log.append({"t": _now(), "msg": msg, "level": level})

    def _node(self, name, **kw):
        self.run["nodes"][name].update(kw)

    def _current(self, run_id):
        return self.run is not None and self.run["id"] == run_id

    def set_mailbox(self, status):
        with self.lock:
            self.mailbox = dict(status)
            self._changed()

    # ------------------------------------------------------------ 1. arrive
    def busy(self):
        return bool(self.run) and any(self.run["nodes"][n]["status"] == "running" for n in NODES)

    def start(self, pdf_bytes, filename, source="upload", email_info=None):
        if not pdf_bytes or pdf_bytes[:5] != b"%PDF-":
            raise PipelineError("That file is not a PDF")
        with self.lock:
            if self.busy():
                raise PipelineError("A step is still running. Wait for it, or press Reset.", 409)
            run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
            rdir = os.path.join(self.state_dir, "runs", run_id)
            os.makedirs(rdir, exist_ok=True)
            fname = safe_name(os.path.basename(filename or "po.pdf"), "po.pdf")
            if not fname.lower().endswith(".pdf"):
                fname += ".pdf"
            with open(os.path.join(rdir, fname), "wb") as f:
                f.write(pdf_bytes)
            with open(os.path.join(rdir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump({"filename": fname, "source": source}, f)
            if email_info:
                with open(os.path.join(rdir, "original_email.eml"), "wb") as f:
                    f.write(email_info["raw"])
            label = {"upload": "Upload", "sample": "Sample", "email": "Email"}.get(source, source.title())
            detail = f"{label} · {email_info['subject'] or fname}" if email_info else f"{label} · {fname}"
            self.run = {
                "id": run_id, "created": _now(), "dir": rdir, "pdf": fname, "source": source,
                "email": {k: email_info[k] for k in ("subject", "from", "message_id")} if email_info else None,
                "extracted": None, "checks": None, "approved": None, "folder": None, "match": None,
                "nodes": {n: {"status": "idle"} for n in NODES},
            }
            self._node("arrive", status="done", detail=detail, at=_now())
            self._node("read", status="running", lines=[], detail="Starting")
            self._log(f"PO arrived: {detail}")
            self._changed()
        threading.Thread(target=self._extract, args=(run_id,), daemon=True).start()
        return run_id

    # ------------------------------------------------------------ 2. read + checks
    def rerun_read(self):
        """Try the extraction again on the same PDF after a failure."""
        with self.lock:
            if not self.run or self.run["nodes"]["read"]["status"] != "error":
                raise PipelineError("Nothing to retry", 409)
            self._node("read", status="running", lines=[], detail="Starting", error=None)
            self._log("Retrying extraction")
            self._changed()
            run_id = self.run["id"]
        threading.Thread(target=self._extract, args=(run_id,), daemon=True).start()

    def _extract(self, run_id):
        pdf = os.path.join(self.run["dir"], self.run["pdf"])
        info = extract.describe_backend(self.cfg)
        reading = ("Replaying the truth file (test mode, no AI)" if info["kind"] == "replay"
                   else f"Claude reading the PO ({info['label']}, {self.cfg.get('PO_MODEL')})")

        def status(text):
            with self.lock:
                if self._current(run_id):
                    node = self.run["nodes"]["read"]
                    node["lines"] = (node.get("lines") or []) + [{"t": _now(), "text": text}]
                    node["detail"] = text
                    self._changed()

        with self.lock:
            if self._current(run_id):
                self._log(reading)
        try:
            kwargs = {"backend": self.backend} if self.backend else {}
            po = self.extractor(pdf, self.cfg, status, **kwargs)
        except Exception as e:
            with self.lock:
                if self._current(run_id):
                    self._node("read", status="error", error=str(e), detail="Extraction failed")
                    self._log(f"Extraction failed: {e}", "error")
                    self._changed()
            return
        result = self.check(po)
        with self.lock:
            if not self._current(run_id):
                return
            self.run["extracted"] = po
            self.run["checks"] = result
            self._node("read", status="done", detail=summary_line(po), chips=result["chips"], at=_now())
            r = result["route"]
            self._node("review", status="waiting", level=r["level"], reasons=r["reasons"],
                       detail="Needs your review")
            flagged = [c["label"] for c in result["chips"] if c["status"] in ("warn", "bad")]
            self._log(f"Extracted PO {po['po_number'] or '(no number)'}: {summary_line(po)}")
            self._log("Checks: " + ("all passed" if not flagged else "; ".join(flagged)),
                      "info" if not flagged else "warn")
            self._log("Waiting for review")
            self._changed()

    def check(self, po):
        """Run the deterministic checks against live ERP and CRM data."""
        try:
            items = self.erp.items()
            company = (po.get("buyer") or {}).get("company") or ""
            dup = self.erp.find_po(company, po.get("po_number")) if company and po.get("po_number") else None

            def suggest(q):
                try:
                    return [{"sku": s["sku"], "description": s["description"], "list_price": s["list_price"]}
                            for s in self.erp.search(q, 3)]
                except Exception:
                    return []
            result = checks.run_checks(po, items, self.crm.companies(), dup, suggest)
        except ERPUnavailable as e:
            result = checks.run_checks(po, {}, self.crm.companies(), None, None)
            result["chips"].insert(0, {"id": "erp", "status": "bad", "label": "ERP offline", "detail": str(e)})
            result["blocking"].insert(0, "ERP offline")
            result["route"] = checks.route(result)
        result["plan"] = self.folder_plan(po, result["customer"])
        return result

    def recheck(self, po):
        clean, errors = validate_po(po)
        result = self.check(clean)
        result["errors"] = errors
        return result

    def folder_plan(self, po, match):
        company = match.get("company") if match and match.get("status") == "known" else (po.get("buyer") or {}).get("company")
        parts = [safe_name(company), safe_name(po.get("po_number"), "no-po-number")]
        files = [self.run["pdf"] if self.run else "po.pdf"]
        if self.run and self.run.get("email"):
            files.append("original_email.eml")
        files += ["extracted.json", "confirmation_email.eml"]
        return {"path": "customers/" + "/".join(parts), "parts": parts, "files": files}

    # ------------------------------------------------------------ 3. review -> 4. fan-out
    def accept(self, po):
        with self.lock:
            if not self.run or self.run["nodes"]["review"]["status"] != "waiting":
                raise PipelineError("There is no order waiting for review", 409)
            run_id = self.run["id"]
        clean, errors = validate_po(po)
        if errors:
            raise PipelineError("Some fields are not valid", 422, errors)
        result = self.check(clean)
        if result["blocking"]:
            raise PipelineError("Fix these before accepting", 422, result["blocking"])
        with self.lock:
            if not self._current(run_id) or self.run["nodes"]["review"]["status"] != "waiting":
                raise PipelineError("The order is no longer waiting for review", 409)
            edits = count_changes(self.run["extracted"], clean)
            self.run["approved"] = clean
            self.run["checks"] = result
            self.run["match"] = result["customer"]
            self.run["folder"] = result["plan"]
            self._node("review", status="done", at=_now(), edits=edits,
                       detail=f"Accepted · {edits} field{'s' if edits != 1 else ''} edited" if edits else "Accepted as read")
            self._log(f"Accepted by reviewer ({edits} field{'s' if edits != 1 else ''} edited)")
            for b in BRANCHES:
                self._node(b, status="running", detail="", error=None)
            self._changed()
        for b in BRANCHES:
            threading.Thread(target=self._branch, args=(run_id, b), daemon=True).start()
        return True

    def _branch(self, run_id, name):
        po, match = self.run["approved"], self.run["match"]
        try:
            if name == "erp":
                order = self.erp.post_order(po)
                so, n = order["so_number"], len(order["lines"])
                out = {"detail": f"{so} posted · {n} line{'s' if n != 1 else ''} · {fmt_money(order['total'])}",
                       "so_number": so, "link": self.erp.order_url(so)}
            elif name == "crm":
                n = len(po["lines"])
                res = self.crm.upsert_from_po(po, match, activity=f"PO {po['po_number']} accepted · {n} lines · {fmt_money(po['total'])}")
                out = {"detail": res["summary"], "company_id": res["company_id"], "link": f"#/crm/{res['company_id']}"}
            else:
                folder = self._write_folder(po)
                out = {"detail": self._files_label(folder), "path": folder}
        except (ERPRefused, ERPUnavailable) as e:
            return self._branch_failed(run_id, name, str(e))
        except Exception as e:
            return self._branch_failed(run_id, name, f"{type(e).__name__}: {e}")
        with self.lock:
            if not self._current(run_id):
                return
            self._node(name, status="done", at=_now(), **out)
            self._log({"erp": "ERP: ", "crm": "CRM: ", "folder": "Folder: "}[name] + out["detail"])
            self._maybe_draft()
            self._changed()

    def _branch_failed(self, run_id, name, msg):
        with self.lock:
            if self._current(run_id):
                self._node(name, status="error", error=msg, detail="Failed")
                self._log(f"{name.upper()} failed: {msg}", "error")
                self._changed()

    def retry(self, name):
        with self.lock:
            if name not in BRANCHES or not self.run or self.run["nodes"][name]["status"] != "error":
                raise PipelineError("Nothing to retry there", 409)
            self._node(name, status="running", error=None, detail="")
            self._log(f"Retrying {name.upper()}")
            self._changed()
            run_id = self.run["id"]
        threading.Thread(target=self._branch, args=(run_id, name), daemon=True).start()

    def _folder_abs(self):
        return os.path.join(self.customers_dir, *self.run["folder"]["parts"])

    def _write_folder(self, po):
        folder = self._folder_abs()
        os.makedirs(folder, exist_ok=True)
        shutil.copyfile(os.path.join(self.run["dir"], self.run["pdf"]), os.path.join(folder, self.run["pdf"]))
        eml = os.path.join(self.run["dir"], "original_email.eml")
        if os.path.exists(eml):
            shutil.copyfile(eml, os.path.join(folder, "original_email.eml"))
        with open(os.path.join(folder, "extracted.json"), "w", encoding="utf-8") as f:
            json.dump(po, f, indent=2)
        return folder

    def _files_label(self, folder):
        n = len([f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))])
        return f"{n} file{'s' if n != 1 else ''} saved · {self.run['folder']['path']}/"

    # ------------------------------------------------------------ 5. email
    def _maybe_draft(self):
        nodes = self.run["nodes"]
        if any(nodes[b]["status"] != "done" for b in BRANCHES) or nodes["email"]["status"] != "idle":
            return
        po = self.run["approved"]
        draft = self.draft_email(po, nodes["erp"].get("so_number"))
        sender.save_draft(self.cfg, draft, nodes["folder"]["path"])
        nodes["folder"]["detail"] = self._files_label(nodes["folder"]["path"])
        self._node("email", status="waiting", draft=draft, gate=sender.gate(self.cfg, draft["to"]),
                   detail="Draft ready")
        self._log("Confirmation email drafted")

    def draft_email(self, po, so_number):
        b = po.get("buyer") or {}
        first = (b.get("contact_name") or "").split(" ")[0] or "there"
        n = len(po["lines"])
        ship = f"shipping {fmt_date(po['requested_ship_date'], True)}" if po.get("requested_ship_date") else \
            "with the ship date to be confirmed"
        lines = "\n".join(f"  {l['line']}. {l['sku']}  {l['description']}  x{l['qty']:g} {l['uom']}  {fmt_money(l['extended'])}"
                          for l in po["lines"])
        body = (f"Hello {first},\n\n"
                f"We received PO {po['po_number']} for {n} line{'s' if n != 1 else ''}, {fmt_money(po['total'])}, {ship}.\n"
                + (f"Our sales order number is {so_number}.\n" if so_number else "")
                + f"\n{lines}\n\n"
                f"Subtotal {fmt_money(po['subtotal'])} · Freight {fmt_money(po['freight'])} · Tax {fmt_money(po['tax'])}"
                f" · Total {fmt_money(po['total'])}\n\n"
                "Reply to this email if anything above is not right.\n\nThank you,\nOrder Desk\nCorvane Steel Works\n")
        return {"to": b.get("email") or "", "subject": f"Order confirmation: your PO {po['po_number']}"
                + (f" / {so_number}" if so_number else ""), "body": body}

    def email_gate(self, to):
        return sender.gate(self.cfg, to)

    def send_email(self, draft):
        with self.lock:
            if not self.run or self.run["nodes"]["email"]["status"] != "waiting":
                raise PipelineError("There is no draft waiting to be sent", 409)
            draft = {k: str(draft.get(k) or "") for k in ("to", "subject", "body")}
            folder = self.run["nodes"]["folder"]["path"]
        res = sender.deliver(self.cfg, draft, folder)
        with self.lock:
            if res["sent"]:
                detail, level = f"Sent to {draft['to']}", "info"
            elif res["action"] == "save":
                detail, level = "Saved, not sent (dry run) · confirmation_email.eml", "info"
            else:
                detail, level = f"Kept as draft · {res['reason']}", "warn"
            self._node("email", status="done", draft=draft, detail=detail, result=res, at=_now(),
                       warn=level == "warn")
            self.run["nodes"]["folder"]["detail"] = self._files_label(folder)
            self._log(f"Email: {detail}", level)
            self._log("Run complete")
            self._changed()
        return res

    # ------------------------------------------------------------ misc
    def reset(self):
        with self.lock:
            self.run, self.log = None, []
            self._log("Reset")
            self._changed()

    def pdf_path(self):
        if not self.run:
            return None
        return os.path.join(self.run["dir"], self.run["pdf"])

    def open_folder(self):
        if not self.run or self.run["nodes"]["folder"]["status"] != "done":
            raise PipelineError("The folder has not been written yet", 409)
        path = os.path.realpath(self.run["nodes"]["folder"]["path"])
        if not path.startswith(os.path.realpath(self.customers_dir)):
            raise PipelineError("Folder is outside the customers directory", 400)
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606 - local folder we created
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return path
