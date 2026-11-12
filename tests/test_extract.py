"""Extraction plumbing with stub backends: retry once, then a clear error. No AI is called."""
import json
import os
import unittest
from unittest import mock

from helpers import SAMPLES, truth

from app import extract

PDF = os.path.join(SAMPLES, "corporate-form.pdf")
CFG = {"PO_MODEL": "test-model", "PO_EXTRACTOR": "auto"}


def stub(replies):
    calls = []

    def run(pdf_path, feedback, cfg, on_text, on_status):
        calls.append(feedback)
        text = replies[len(calls) - 1]
        for i in range(0, len(text), 40):
            on_text(text[i:i + 40])
        return text
    run.calls = calls
    return run


class ExtractTest(unittest.TestCase):
    def test_good_reply_first_time(self):
        good = json.dumps(truth("corporate-form"))
        lines = []
        run = stub([good])
        po = extract.extract(PDF, CFG, lines.append, backend=run)
        self.assertEqual(po["po_number"], "88213")
        self.assertEqual(len(run.calls), 1)
        self.assertIn("Found the customer: Northfield Market Co.", lines)
        self.assertIn("Line 4: CT-0350", lines)
        self.assertEqual(lines[-1], "4 line items")

    def test_retry_once_with_feedback(self):
        bad = json.dumps(dict(truth("corporate-form"), po_date="Oct 29"))
        good = json.dumps(truth("corporate-form"))
        run = stub([bad, good])
        po = extract.extract(PDF, CFG, lambda s: None, backend=run)
        self.assertEqual(po["po_date"], "2026-10-29")
        self.assertEqual(len(run.calls), 2)
        self.assertIsNone(run.calls[0])
        self.assertTrue(any("po_date" in e for e in run.calls[1]))

    def test_two_bad_replies_raise(self):
        run = stub(["sorry, I can't read that", "still not json"])
        with self.assertRaises(extract.ExtractionError) as cm:
            extract.extract(PDF, CFG, lambda s: None, backend=run)
        self.assertIn("twice", str(cm.exception))
        self.assertEqual(len(run.calls), 2)

    def test_prompt_contains_contract_and_feedback(self):
        p = extract.build_prompt("PDF attached.", ["lines: no line items found"])
        self.assertIn('"requested_ship_date"', p)
        self.assertIn("lines: no line items found", p)

    def test_page_count(self):
        self.assertEqual(extract.pdf_page_count(PDF), 1)
        self.assertEqual(extract.pdf_page_count(os.path.join(SAMPLES, "distributor-po.pdf")), 2)

    def test_backend_selection(self):
        self.assertEqual(extract.describe_backend({"PO_EXTRACTOR": "auto", "ANTHROPIC_API_KEY": "k"})["kind"], "api")
        self.assertEqual(extract.describe_backend({"PO_EXTRACTOR": "replay"})["kind"], "replay")
        b = extract.describe_backend({"PO_EXTRACTOR": "api", "ANTHROPIC_API_KEY": ""})
        self.assertFalse(b["ready"])

    def test_not_ready_gives_clear_error(self):
        cfg = {"PO_EXTRACTOR": "cli", "CLAUDE_BIN": "", "PO_MODEL": "m"}
        with mock.patch.object(extract, "find_cli", return_value=""):  # as if no CLI is installed
            with self.assertRaises(extract.ExtractionError) as cm:
                extract.extract(PDF, cfg, lambda s: None)
        self.assertIn("ANTHROPIC_API_KEY", str(cm.exception))
        with mock.patch.object(extract, "find_cli", return_value="claude"), \
                mock.patch.object(extract, "cli_signed_in", return_value=False):  # installed, not signed in
            with self.assertRaises(extract.ExtractionError) as cm:
                extract.extract(PDF, cfg, lambda s: None)
        self.assertIn("sign in", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
