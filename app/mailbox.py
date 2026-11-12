"""Optional IMAP watcher. Strictly read-only.

- The folder is opened with SELECT ... readonly (EXAMINE), so the server can't change flags.
- Messages are fetched with BODY.PEEK[], which never sets \\Seen.
- No STORE, COPY, MOVE, EXPUNGE or DELETE command is ever issued.
- Handled Message-IDs are kept locally in state/handled_messages.json.
"""
from __future__ import annotations

import email
import imaplib
import json
import os
import threading
import time
from datetime import datetime, timedelta
from email import policy

from . import config


class HandledList:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                return set(json.load(f))
        except (OSError, ValueError):
            return set()

    def add(self, mid):
        with self.lock:
            ids = self.load()
            ids.add(mid)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(sorted(ids), f, indent=1)


def pdf_attachments(msg):
    out = []
    for part in msg.walk():
        fn = part.get_filename() or ""
        ctype = part.get_content_type()
        if ctype == "application/pdf" or fn.lower().endswith(".pdf"):
            data = part.get_payload(decode=True)
            if data and data[:5] == b"%PDF-":
                out.append((fn or "attachment.pdf", data))
    return out


def poll_once(cfg, handled, imap_factory=None):
    """Return a list of new messages that carry a PDF: dicts with message_id, subject, from, raw, pdfs."""
    factory = imap_factory or imaplib.IMAP4_SSL
    conn = factory(cfg["IMAP_HOST"], int(cfg.get("IMAP_PORT") or 993))
    found = []
    try:
        conn.login(cfg["IMAP_USER"], cfg["IMAP_PASSWORD"])
        typ, _ = conn.select(cfg.get("IMAP_FOLDER") or "INBOX", readonly=True)
        if typ != "OK":
            raise RuntimeError(f"cannot open folder {cfg.get('IMAP_FOLDER')}")
        since = (datetime.now() - timedelta(days=int(cfg.get("IMAP_LOOKBACK_DAYS") or 3))).strftime("%d-%b-%Y")
        typ, data = conn.search(None, "SINCE", since)
        seen = handled.load()
        for num in (data[0].split() if data and data[0] else []):
            typ, parts = conn.fetch(num, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if not raw:
                continue
            msg = email.message_from_bytes(raw, policy=policy.default)
            mid = str(msg.get("Message-ID") or f"no-id-{num.decode()}").strip()
            if mid in seen:
                continue
            pdfs = pdf_attachments(msg)
            if not pdfs:
                continue
            found.append({"message_id": mid, "subject": str(msg.get("Subject") or ""),
                          "from": str(msg.get("From") or ""), "raw": raw, "pdfs": pdfs})
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return found


class Watcher(threading.Thread):
    """Polls the mailbox and hands new PDFs to on_message(msg) -> bool (True when accepted)."""

    def __init__(self, cfg, handled, on_message, on_status):
        super().__init__(daemon=True)
        self.cfg, self.handled, self.on_message, self.on_status = cfg, handled, on_message, on_status
        self.stop = threading.Event()

    def run(self):
        interval = max(15, int(self.cfg.get("IMAP_POLL_SECONDS") or 60))
        while not self.stop.is_set():
            try:
                for m in poll_once(self.cfg, self.handled):
                    if self.on_message(m):
                        self.handled.add(m["message_id"])
                    else:
                        break  # a run is busy; try again next poll
                self.on_status({"state": "watching", "last_poll": datetime.now().isoformat(timespec="seconds")})
            except Exception as e:  # keep watching; show the error
                self.on_status({"state": "error", "error": str(e)[:200]})
            self.stop.wait(interval)


def settings_ok(cfg):
    missing = [k for k in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD") if not cfg.get(k)]
    return (config.truthy(cfg.get("MAILBOX_WATCH")) or cfg.get("MAILBOX_WATCH") == "imap"), missing
