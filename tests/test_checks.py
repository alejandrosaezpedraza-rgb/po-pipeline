import copy
import unittest

from helpers import SLUGS, erp_items, truth

from app import checks

ITEMS = erp_items()
COMPANIES = [
    {"id": 1, "name": "Bristow Wholesale Foods, Inc.", "addresses": [{"street": "2200 Mill Race Road", "zip": "43215"}]},
    {"id": 2, "name": "Pinecrest Home Centers LLC", "addresses": [{"street": "1 Pinecrest Plaza", "zip": "12207"}]},
    {"id": 3, "name": "Calloway Logistics Group", "addresses": []},
]


class TotalsTest(unittest.TestCase):
    def test_every_sample_adds_up(self):
        for slug in SLUGS:
            self.assertEqual(checks.check_totals(truth(slug))["status"], "ok", slug)

    def test_bad_extended(self):
        po = truth("corporate-form")
        po["lines"][1]["extended"] = 5000
        r = checks.check_totals(po)
        self.assertEqual(r["status"], "bad")
        self.assertIn(1, r["line_issues"])

    def test_bad_subtotal_and_total(self):
        po = truth("corporate-form")
        po["subtotal"] += 10
        self.assertIn("subtotal", checks.check_totals(po)["detail"])
        po = truth("store-order")
        po["total"] = 4000
        self.assertIn("total", checks.check_totals(po)["detail"])

    def test_freight_and_tax_count(self):
        po = truth("store-order")  # has freight and tax
        self.assertEqual(checks.check_totals(po)["status"], "ok")
        po["tax"] = 0
        self.assertEqual(checks.check_totals(po)["status"], "bad")

    def test_cent_tolerance(self):
        po = truth("corporate-form")
        po["total"] += 0.004
        self.assertEqual(checks.check_totals(po)["status"], "ok")


class SkuPriceTest(unittest.TestCase):
    def test_all_sample_skus_and_prices_match(self):
        for slug in SLUGS:
            po = truth(slug)
            self.assertEqual(checks.check_skus(po, ITEMS)["status"], "ok", slug)
            self.assertEqual(checks.check_prices(po, ITEMS)["status"], "ok", slug)

    def test_unknown_sku_with_suggestion(self):
        po = truth("corporate-form")
        po["lines"][0]["sku"] = "CT-12OO"
        r = checks.check_skus(po, ITEMS, suggest=lambda q: [{"sku": "CT-1200", "description": "x"}])
        self.assertEqual(r["status"], "bad")
        self.assertIn("CT-1200", r["line_issues"][0])

    def test_sku_case_and_space_insensitive(self):
        po = truth("corporate-form")
        po["lines"][0]["sku"] = " ct-1200 "
        self.assertEqual(checks.check_skus(po, ITEMS)["status"], "ok")

    def test_price_off_list_is_a_warning(self):
        po = truth("corporate-form")
        po["lines"][2]["unit_price"] = 399.0
        r = checks.check_prices(po, ITEMS)
        self.assertEqual(r["status"], "warn")
        self.assertIn("$410.00", r["line_issues"][2])

    def test_unknown_sku_not_double_counted_as_price(self):
        po = truth("corporate-form")
        po["lines"][0]["sku"] = "NOPE"
        self.assertEqual(checks.check_prices(po, ITEMS)["status"], "ok")


class ShipDateTest(unittest.TestCase):
    def test_present(self):
        self.assertEqual(checks.check_ship_date(truth("edi-printout"))["status"], "ok")

    def test_missing(self):
        po = truth("edi-printout")
        po["requested_ship_date"] = ""
        self.assertEqual(checks.check_ship_date(po)["status"], "bad")

    def test_before_po_date(self):
        po = truth("edi-printout")
        po["requested_ship_date"] = "2026-10-01"
        self.assertEqual(checks.check_ship_date(po)["status"], "warn")


class CustomerMatchTest(unittest.TestCase):
    def test_exact(self):
        m = checks.match_customer(truth("change-form"), COMPANIES)
        self.assertEqual((m["status"], m["method"], m["company_id"]), ("known", "exact name", 3))

    def test_normalized_name(self):
        m = checks.match_customer(truth("edi-printout"), COMPANIES)  # "BRISTOW WHOLESALE FOODS INC"
        self.assertEqual((m["status"], m["method"], m["company_id"]), ("known", "normalized name", 1))

    def test_address(self):
        m = checks.match_customer(truth("store-order"), COMPANIES)  # different name, same bill-to
        self.assertEqual((m["status"], m["method"], m["company_id"]), ("known", "address", 2))

    def test_new(self):
        for slug in ("corporate-form", "distributor-po"):
            self.assertEqual(checks.match_customer(truth(slug), COMPANIES)["status"], "new", slug)

    def test_normalizers(self):
        self.assertEqual(checks.norm_name("The Acme Co., Inc."), checks.norm_name("ACME COMPANY"))
        self.assertEqual(checks.norm_name("A & B Supply"), checks.norm_name("A and B Supply LLC"))
        self.assertEqual(checks.norm_street("2200 Mill Race Road"), checks.norm_street("2200 MILL RACE RD."))
        self.assertEqual(checks.norm_zip("43215-1234"), "43215")

    def test_same_street_other_zip_is_not_a_match(self):
        po = truth("store-order")
        po["bill_to"]["zip"] = "99999"
        po["buyer"]["company"] = "Someone Else"
        self.assertEqual(checks.match_customer(po, COMPANIES)["status"], "new")


class RoutingTest(unittest.TestCase):
    def test_clean_order_still_goes_to_a_person(self):
        r = checks.run_checks(truth("corporate-form"), ITEMS, COMPANIES)
        self.assertEqual(r["route"]["level"], "clean")
        self.assertTrue(r["route"]["requires_human"])
        self.assertEqual(r["route"]["queue"], "human_review")
        self.assertEqual(r["blocking"], [])

    def test_price_warning_routes_attention(self):
        po = truth("corporate-form")
        po["lines"][0]["unit_price"] = 1200
        po["lines"][0]["extended"] = 7200
        po["subtotal"] = po["total"] = 14080
        r = checks.run_checks(po, ITEMS, COMPANIES)
        self.assertEqual(r["route"]["level"], "attention")
        self.assertEqual(r["blocking"], [])

    def test_blockers(self):
        po = truth("corporate-form")
        po["lines"][0]["sku"] = "XX-1"
        r = checks.run_checks(po, ITEMS, COMPANIES)
        self.assertEqual(r["route"]["level"], "blocked")
        r = checks.run_checks(truth("corporate-form"), ITEMS, COMPANIES, duplicate={"id": 4, "so_number": "SO-11902"})
        self.assertTrue(any("SO-11902" in b for b in r["blocking"]))
        po = truth("corporate-form")
        po["po_number"] = ""
        self.assertIn("missing PO number", checks.run_checks(po, ITEMS, COMPANIES)["blocking"])

    def test_no_auto_approve_for_any_sample(self):
        for slug in SLUGS:
            r = checks.run_checks(truth(slug), ITEMS, COMPANIES)
            self.assertTrue(r["route"]["requires_human"], slug)

    def test_input_not_mutated(self):
        po = truth("distributor-po")
        before = copy.deepcopy(po)
        checks.run_checks(po, ITEMS, COMPANIES)
        self.assertEqual(po, before)


if __name__ == "__main__":
    unittest.main()
