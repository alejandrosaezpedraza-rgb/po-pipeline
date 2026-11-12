"""The send allowlist. No test here opens a network connection: SMTP is always a fake."""
import os
import shutil
import tempfile
import unittest

import helpers  # noqa: F401  (sets sys.path)

from app import sender

DRAFT = {"to": "buyer@customer.example", "subject": "Order confirmation", "body": "Hello"}


class NoSMTP:
    def __init__(self, *a, **k):
        raise AssertionError("SMTP must not be contacted")


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, u, p):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def live(allowed, **kw):
    return dict({"SEND_MODE": "live", "SEND_ALLOWED": allowed, "SMTP_HOST": "smtp.test.invalid",
                 "SMTP_PORT": "587", "SMTP_FROM": "orders@corvane.example", "SMTP_STARTTLS": "true"}, **kw)


class GateTest(unittest.TestCase):
    def test_dry_is_default_and_never_sends(self):
        g = sender.gate({}, DRAFT["to"])
        self.assertEqual((g["action"], g["mode"]), ("save", "dry"))

    def test_live_exact_and_domain(self):
        self.assertEqual(sender.gate(live("buyer@customer.example"), DRAFT["to"])["action"], "send")
        self.assertEqual(sender.gate(live("@customer.example"), DRAFT["to"])["action"], "send")
        self.assertEqual(sender.gate(live("BUYER@Customer.Example"), DRAFT["to"])["action"], "send")

    def test_live_not_allowed(self):
        g = sender.gate(live("me@mine.example"), DRAFT["to"])
        self.assertEqual(g["action"], "draft")
        self.assertIn("not in SEND_ALLOWED", g["label"])

    def test_empty_allowlist_blocks_everything(self):
        self.assertEqual(sender.gate(live(""), DRAFT["to"])["action"], "draft")

    def test_lookalike_domains_blocked(self):
        allowed = live("@customer.example")
        for to in ("x@evilcustomer.example", "x@sub.customer.example", "x@customer.example.evil",
                   "x@customer-example"):
            self.assertEqual(sender.gate(allowed, to)["action"], "draft", to)

    def test_every_recipient_must_be_allowed(self):
        g = sender.gate(live("a@ok.example"), "a@ok.example, b@other.example")
        self.assertEqual(g["action"], "draft")
        self.assertIn("b@other.example", g["reason"])

    def test_display_name_tricks(self):
        g = sender.gate(live("a@ok.example"), '"a@ok.example" <evil@bad.example>')
        self.assertEqual(g["action"], "draft")

    def test_header_injection_rejected(self):
        g = sender.gate(live("a@ok.example"), "a@ok.example\nBcc: evil@bad.example")
        self.assertEqual(g["action"], "draft")

    def test_invalid_address(self):
        self.assertEqual(sender.gate(live("a@ok.example"), "not an address")["action"], "draft")

    def test_live_without_smtp_host_stays_draft(self):
        self.assertEqual(sender.gate(live("buyer@customer.example", SMTP_HOST=""), DRAFT["to"])["action"], "draft")


class DeliverTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        FakeSMTP.sent = []

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_dry_saves_file_without_smtp(self):
        r = sender.deliver({"SEND_MODE": "dry"}, DRAFT, self.dir, smtp_factory=NoSMTP)
        self.assertFalse(r["sent"])
        with open(r["saved"], encoding="utf-8") as f:
            text = f.read()
        self.assertIn("dry-run, not sent", text)
        self.assertIn("To: buyer@customer.example", text)

    def test_live_blocked_never_touches_smtp(self):
        r = sender.deliver(live("me@mine.example"), DRAFT, self.dir, smtp_factory=NoSMTP)
        self.assertFalse(r["sent"])
        self.assertEqual(r["action"], "draft")
        self.assertTrue(os.path.exists(r["saved"]))

    def test_live_allowed_sends_through_smtp(self):
        r = sender.deliver(live("buyer@customer.example"), DRAFT, self.dir, smtp_factory=FakeSMTP)
        self.assertTrue(r["sent"])
        self.assertEqual(len(FakeSMTP.sent), 1)
        self.assertEqual(FakeSMTP.sent[0]["To"], "buyer@customer.example")

    def test_injection_in_to_is_saved_not_sent(self):
        d = dict(DRAFT, to="buyer@customer.example\r\nBcc: x@evil.example")
        r = sender.deliver(live("buyer@customer.example"), d, self.dir, smtp_factory=NoSMTP)
        self.assertFalse(r["sent"])

    def test_save_draft_sends_nothing(self):
        p = sender.save_draft({}, DRAFT, self.dir)
        with open(p, encoding="utf-8") as f:
            self.assertIn("draft, not sent yet", f.read())


if __name__ == "__main__":
    unittest.main()
