"""The IMAP watcher must be read-only. A fake server records every command."""
import os
import shutil
import tempfile
import unittest
from email.message import EmailMessage

from helpers import SAMPLES

from app import mailbox


def make_email(mid, with_pdf=True):
    m = EmailMessage()
    m["From"] = "Dana Reyes <dreyes@northfieldmarket.example>"
    m["To"] = "orders@corvane.example"
    m["Subject"] = "PO 88213"
    m["Message-ID"] = mid
    m.set_content("Please see attached PO.")
    if with_pdf:
        with open(os.path.join(SAMPLES, "corporate-form.pdf"), "rb") as f:
            m.add_attachment(f.read(), maintype="application", subtype="pdf", filename="88213.pdf")
    return bytes(m)


class FakeIMAP:
    FORBIDDEN = ("store", "copy", "move", "expunge", "delete", "uid", "append")

    def __init__(self, host, port):
        self.calls = []
        self.messages = {b"1": make_email("<a@x>"), b"2": make_email("<b@x>", with_pdf=False), b"3": make_email("<c@x>")}
        FakeIMAP.last = self

    def __getattr__(self, name):
        if name in FakeIMAP.FORBIDDEN:
            raise AssertionError(f"mailbox watcher called {name.upper()}")
        raise AttributeError(name)

    def login(self, u, p):
        self.calls.append(("login",))

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder, readonly))
        return "OK", [b"3"]

    def search(self, charset, *criteria):
        self.calls.append(("search",) + criteria)
        return "OK", [b" ".join(self.messages)]

    def fetch(self, num, what):
        self.calls.append(("fetch", num, what))
        return "OK", [(b"1 (BODY[] {n}", self.messages[num]), b")"]

    def logout(self):
        self.calls.append(("logout",))


CFG = {"IMAP_HOST": "imap.test.invalid", "IMAP_PORT": "993", "IMAP_USER": "u", "IMAP_PASSWORD": "p",
       "IMAP_FOLDER": "INBOX", "IMAP_LOOKBACK_DAYS": "3"}


class MailboxTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.handled = mailbox.HandledList(os.path.join(self.dir, "handled.json"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_read_only(self):
        mailbox.poll_once(CFG, self.handled, imap_factory=FakeIMAP)
        calls = FakeIMAP.last.calls
        self.assertIn(("select", "INBOX", True), calls)
        fetches = [c for c in calls if c[0] == "fetch"]
        self.assertTrue(fetches)
        for c in fetches:
            self.assertIn("BODY.PEEK[]", c[2])
        names = {c[0] for c in calls}
        self.assertTrue(names <= {"login", "select", "search", "fetch", "logout"}, names)

    def test_only_messages_with_pdf(self):
        found = mailbox.poll_once(CFG, self.handled, imap_factory=FakeIMAP)
        self.assertEqual([m["message_id"] for m in found], ["<a@x>", "<c@x>"])
        self.assertEqual(found[0]["pdfs"][0][0], "88213.pdf")
        self.assertTrue(found[0]["pdfs"][0][1].startswith(b"%PDF-"))

    def test_handled_ids_are_skipped_and_persisted(self):
        self.handled.add("<a@x>")
        found = mailbox.poll_once(CFG, self.handled, imap_factory=FakeIMAP)
        self.assertEqual([m["message_id"] for m in found], ["<c@x>"])
        again = mailbox.HandledList(self.handled.path)
        self.assertEqual(again.load(), {"<a@x>"})

    def test_off_by_default(self):
        enabled, missing = mailbox.settings_ok({"MAILBOX_WATCH": "off"})
        self.assertFalse(enabled)
        self.assertEqual(missing, ["IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"])


if __name__ == "__main__":
    unittest.main()
