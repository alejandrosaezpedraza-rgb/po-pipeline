import json
import unittest

from helpers import SLUGS, truth

from app.validate import parse_json_reply, validate_po


class ValidateTest(unittest.TestCase):
    def test_truth_files_are_valid(self):
        for slug in SLUGS:
            clean, errors = validate_po(truth(slug))
            self.assertEqual(errors, [], slug)
            self.assertEqual(clean["total"], truth(slug)["total"])

    def test_missing_keys(self):
        po = truth("corporate-form")
        del po["po_number"]
        del po["lines"][0]["qty"]
        _, errors = validate_po(po)
        self.assertIn("po_number: missing", errors)
        self.assertIn("lines[1].qty: missing", errors)

    def test_bad_date(self):
        po = truth("corporate-form")
        po["po_date"] = "10/29/2026"
        _, errors = validate_po(po)
        self.assertTrue(any(e.startswith("po_date") for e in errors))

    def test_empty_date_allowed(self):
        po = truth("corporate-form")
        po["requested_ship_date"] = ""
        self.assertEqual(validate_po(po)[1], [])

    def test_numeric_strings_coerced_text_rejected(self):
        po = truth("corporate-form")
        po["lines"][0]["unit_price"] = "$1,240.00"
        clean, errors = validate_po(po)
        self.assertEqual(errors, [])
        self.assertEqual(clean["lines"][0]["unit_price"], 1240.0)
        po["lines"][0]["qty"] = "six"
        self.assertTrue(validate_po(po)[1])

    def test_no_lines(self):
        po = truth("corporate-form")
        po["lines"] = []
        self.assertIn("lines: no line items found", validate_po(po)[1])

    def test_nulls(self):
        po = truth("corporate-form")
        po["notes"] = None
        po["freight"] = None
        clean, errors = validate_po(po)
        self.assertEqual(errors, [])
        self.assertEqual((clean["notes"], clean["freight"]), ("", 0))
        po["total"] = None
        self.assertTrue(validate_po(po)[1])

    def test_wrong_types(self):
        self.assertTrue(validate_po([])[1])
        po = truth("corporate-form")
        po["buyer"] = "Dana"
        self.assertIn("buyer: expected an object", validate_po(po)[1])
        po = truth("corporate-form")
        po["lines"][0]["qty"] = True
        self.assertTrue(validate_po(po)[1])

    def test_currency(self):
        po = truth("corporate-form")
        po["currency"] = "dollars"
        self.assertTrue(validate_po(po)[1])

    def test_unknown_keys_dropped(self):
        po = truth("corporate-form")
        po["confidence"] = 0.9
        clean, errors = validate_po(po)
        self.assertEqual(errors, [])
        self.assertNotIn("confidence", clean)

    def test_parse_reply_variants(self):
        body = json.dumps(truth("store-order"))
        for reply in (body, f"```json\n{body}\n```", f"Here it is:\n{body}\nDone."):
            self.assertEqual(parse_json_reply(reply)["po_number"], "PHH-0417-1103")
        for bad in ("", "no json here", "{\"a\": }"):
            with self.assertRaises(ValueError):
                parse_json_reply(bad)


if __name__ == "__main__":
    unittest.main()
