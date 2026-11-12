"""Full pipeline with a stubbed extractor, the real demo ERP (temp DB) and a temp CRM.

Proves: nothing reaches the ERP or CRM before accept(); edits reach the ERP; every
branch runs; the email is saved in dry mode and nothing is sent.
"""
import json
import os
import shutil
import tempfile
import unittest

from helpers import ROOT, SAMPLES, SLUGS, TempERP, truth, wait_for

from app import sender
from app.crm import CRM
from app.erp_client import ERPClient
from app.pipeline import Pipeline, PipelineError


def stub_backend(pdf_path, feedback, cfg, on_text, on_status):
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    text = json.dumps(truth(stem))
    on_status("Reading page 1")
    on_text(text)
    return text


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.erp = TempERP()

    @classmethod
    def tearDownClass(cls):
        cls.erp.close()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pipe-test-")
        self.cfg = {"STATE_DIR": os.path.join(self.tmp, "state"), "CUSTOMERS_DIR": os.path.join(self.tmp, "customers"),
                    "SEND_MODE": "dry", "PO_MODEL": "stub", "PO_EXTRACTOR": "auto"}
        self.client = ERPClient(self.erp.url)
        self.crm = CRM(os.path.join(self.tmp, "state", "crm.db"), os.path.join(SAMPLES, "customers.json"))
        self.p = Pipeline(self.cfg, self.client, self.crm, backend=stub_backend)
        self._no_smtp = sender.smtplib.SMTP
        sender.smtplib.SMTP = _forbidden_smtp

    def tearDown(self):
        sender.smtplib.SMTP = self._no_smtp
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, slug):
        with open(os.path.join(SAMPLES, slug + ".pdf"), "rb") as f:
            self.p.start(f.read(), slug + ".pdf", "upload")
        wait_for(lambda: self.p.run["nodes"]["review"]["status"] == "waiting" or self.p.run["nodes"]["read"]["status"] == "error",
                 msg="review")
        self.assertEqual(self.p.run["nodes"]["read"]["status"], "done", self.p.run["nodes"]["read"].get("error"))

    def orders_for(self, po_number):
        return [o for o in self.client._req("GET", "/api/orders") if o["po_number"] == po_number]

    def test_each_sample_end_to_end(self):
        for slug in SLUGS:
            with self.subTest(slug=slug):
                self.p.reset()
                t = truth(slug)
                po_no = f"{t['po_number']}-{slug[:3]}"
                companies_before = len(self.crm.companies())
                self.start(slug)
                chips = {c["id"]: c["status"] for c in self.p.run["checks"]["chips"]}
                for cid in ("totals", "skus", "prices", "ship_date"):
                    self.assertEqual(chips[cid], "ok", (slug, cid))

                # nothing reached the ERP or CRM yet
                self.assertEqual(self.orders_for(po_no), [])
                self.assertEqual(len(self.crm.companies()), companies_before)
                self.assertEqual(self.p.run["nodes"]["erp"]["status"], "idle")

                # reviewer edits: new PO number (so samples don't collide) and line 1 qty + 2
                po = json.loads(json.dumps(self.p.run["extracted"]))
                po["po_number"] = po_no
                ln = po["lines"][0]
                ln["qty"] += 2
                ln["extended"] = round(ln["qty"] * ln["unit_price"], 2)
                po["subtotal"] = round(sum(l["extended"] for l in po["lines"]), 2)
                po["total"] = round(po["subtotal"] + po["freight"] + po["tax"], 2)
                self.p.accept(po)

                wait_for(lambda: self.p.run["nodes"]["email"]["status"] == "waiting" or
                         any(self.p.run["nodes"][b]["status"] == "error" for b in ("erp", "crm", "folder")), msg="branches")
                for b in ("erp", "crm", "folder"):
                    self.assertEqual(self.p.run["nodes"][b]["status"], "done", (slug, b, self.p.run["nodes"][b].get("error")))
                self.assertEqual(self.p.run["nodes"]["review"]["edits"], 2)

                # ERP has the edited values
                (summary,) = self.orders_for(po_no)
                order = self.client._req("GET", f"/api/orders/{summary['so_number']}")
                self.assertEqual(order["status"], "POSTED")
                self.assertEqual(order["lines"][0]["qty"], t["lines"][0]["qty"] + 2)
                self.assertAlmostEqual(order["total"], po["total"], places=2)
                self.assertIn(order["so_number"], self.p.run["nodes"]["erp"]["detail"])
                self.assertTrue(self.p.run["nodes"]["erp"]["link"].endswith(order["so_number"]))

                # CRM: known customers updated, new ones created
                crm_detail = self.p.run["nodes"]["crm"]["detail"]
                expected = "Updated" if slug in ("edi-printout", "store-order", "change-form") else "Created"
                self.assertTrue(crm_detail.startswith(expected), (slug, crm_detail))
                self.assertTrue(self.p.run["nodes"]["crm"]["link"].startswith("#/crm/"))

                # Folder
                folder = self.p.run["nodes"]["folder"]["path"]
                self.assertTrue(folder.startswith(self.cfg["CUSTOMERS_DIR"]))
                files = sorted(os.listdir(folder))
                self.assertEqual(files, sorted([slug + ".pdf", "extracted.json", "confirmation_email.eml"]))
                with open(os.path.join(folder, "extracted.json"), encoding="utf-8") as f:
                    self.assertEqual(json.load(f)["po_number"], po_no)

                # Email draft built from the data, then saved (dry), never sent
                draft = self.p.run["nodes"]["email"]["draft"]
                self.assertEqual(draft["to"], t["buyer"]["email"])
                n = len(po["lines"])
                self.assertIn(f"We received PO {po_no} for {n} lines, ${po['total']:,.2f}", draft["body"])
                self.assertIn(order["so_number"], draft["body"])
                r = self.p.send_email(draft)
                self.assertFalse(r["sent"])
                self.assertEqual(self.p.run["nodes"]["email"]["status"], "done")
                with open(os.path.join(folder, "confirmation_email.eml"), encoding="utf-8") as f:
                    self.assertIn("dry-run, not sent", f.read())

    def test_accept_blocked_on_unknown_sku_and_nothing_written(self):
        self.start("corporate-form")
        po = json.loads(json.dumps(self.p.run["extracted"]))
        po["po_number"] = "T-BLOCK"
        po["lines"][0]["sku"] = "NOT-A-SKU"
        with self.assertRaises(PipelineError) as cm:
            self.p.accept(po)
        self.assertEqual(cm.exception.code, 422)
        self.assertEqual(self.p.run["nodes"]["review"]["status"], "waiting")
        self.assertEqual(self.orders_for("T-BLOCK"), [])

    def test_accept_requires_waiting_review(self):
        with self.assertRaises(PipelineError):
            self.p.accept(truth("corporate-form"))

    def test_duplicate_po_is_blocked(self):
        self.start("change-form")
        po = dict(self.p.run["extracted"], po_number="T-TWICE")
        self.p.accept(po)
        wait_for(lambda: self.p.run["nodes"]["email"]["status"] == "waiting", msg="first run")
        self.p.reset()
        self.start("change-form")
        with self.assertRaises(PipelineError) as cm:
            self.p.accept(dict(self.p.run["extracted"], po_number="T-TWICE"))
        self.assertTrue(any("already in ERP" in d for d in cm.exception.details))

    def test_extraction_error_shown_on_node(self):
        def broken(pdf_path, feedback, cfg, on_text, on_status):
            return "not json"
        self.p.backend = broken
        with open(os.path.join(SAMPLES, "store-order.pdf"), "rb") as f:
            self.p.start(f.read(), "store-order.pdf")
        wait_for(lambda: self.p.run["nodes"]["read"]["status"] == "error", msg="error")
        self.assertIn("data contract", self.p.run["nodes"]["read"]["error"])
        self.assertEqual(self.p.run["nodes"]["review"]["status"], "idle")

    def test_rejects_non_pdf(self):
        with self.assertRaises(PipelineError):
            self.p.start(b"hello", "x.pdf")

    def test_state_survives_restart(self):
        self.start("store-order")
        with self.p.lock:  # state changes and their save to disk happen under this lock
            p2 = Pipeline(self.cfg, self.client, self.crm, backend=stub_backend)
        self.assertEqual(p2.run["nodes"]["review"]["status"], "waiting")
        self.assertEqual(p2.run["extracted"]["po_number"], "PHH-0417-1103")


def _forbidden_smtp(*a, **k):
    raise AssertionError("tests must never open an SMTP connection")


if __name__ == "__main__":
    unittest.main()
