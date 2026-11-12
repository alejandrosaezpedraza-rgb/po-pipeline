import unittest
import urllib.request

from helpers import TempERP, truth

from app.erp_client import ERPClient, ERPRefused


class ERPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.erp = TempERP()
        cls.client = ERPClient(cls.erp.url)

    @classmethod
    def tearDownClass(cls):
        cls.erp.close()

    def test_item_master(self):
        items = self.client.items()
        self.assertEqual(items["CT-1200"]["list_price"], 1240.0)
        self.assertGreaterEqual(len(items), 20)

    def test_typo_tolerant_search(self):
        cases = {"ct-12oo": "CT-1200", "workbnch 72x36 drawers": "WB-7236H", "boltles shelving 72x48": "SH-7248",
                 "tilt bin": "CT-TUB", "castor set": "AC-CAST4", "wb7236h": "WB-7236H"}
        for q, sku in cases.items():
            hits = self.client.search(q, 3)
            self.assertTrue(hits, q)
            self.assertEqual(hits[0]["sku"], sku, q)

    def test_stage_then_approve(self):
        po = truth("store-order")
        po["po_number"] = "T-STAGE-1"
        order = self.client.post_order(po, source="test")
        self.assertEqual(order["status"], "POSTED")
        self.assertRegex(order["so_number"], r"^SO-\d+$")
        self.assertEqual(order["total"], po["total"])
        self.assertEqual(len(order["lines"]), 5)
        html = urllib.request.urlopen(f"{self.erp.url}/orders/{order['so_number']}").read().decode()
        self.assertIn("T-STAGE-1", html)
        self.assertIn("$4,840.28", html)

    def test_so_numbers_increase(self):
        a = self.client.post_order(dict(truth("corporate-form"), po_number="T-SEQ-1"))
        b = self.client.post_order(dict(truth("corporate-form"), po_number="T-SEQ-2"))
        self.assertEqual(int(b["so_number"][3:]), int(a["so_number"][3:]) + 1)

    def test_refuses_unknown_sku(self):
        po = truth("corporate-form")
        po["po_number"] = "T-BAD-SKU"
        po["lines"][0]["sku"] = "XX-0000"
        with self.assertRaises(ERPRefused) as cm:
            self.client.post_order(po)
        self.assertIn("XX-0000", str(cm.exception))

    def test_refuses_bad_totals(self):
        po = truth("corporate-form")
        po["po_number"] = "T-BAD-TOTAL"
        po["total"] += 100
        with self.assertRaises(ERPRefused):
            self.client.post_order(po)

    def test_refuses_duplicate_po(self):
        po = dict(truth("change-form"), po_number="T-DUP")
        first = self.client.post_order(po)
        with self.assertRaises(ERPRefused) as cm:
            self.client.post_order(po)
        self.assertIn(first["so_number"], str(cm.exception))
        self.assertEqual(self.client.find_po(po["buyer"]["company"], "T-DUP")["so_number"], first["so_number"])

    def test_approve_only_staged(self):
        from erp import core
        o = core.stage_order(dict(truth("edi-printout"), po_number="T-APPROVE"))
        self.assertEqual(o["status"], "STAGED")
        self.assertIsNone(o["so_number"])
        core.approve_order(o["id"])
        with self.assertRaises(core.ERPError):
            core.approve_order(o["id"])


if __name__ == "__main__":
    unittest.main()
