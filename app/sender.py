"""Confirmation email: build, gate and send-or-save.

SEND_MODE=dry (default): the email is saved as a file. Nothing is sent.
SEND_MODE=live: sent over SMTP only if every recipient is in SEND_ALLOWED
(exact addresses, or "@domain.example" for a whole domain). Otherwise it stays a draft.
"""
from __future__ import annotations

import os
import re
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid

from . import config

ADDR_RE = re.compile(r"^[^@\s<>\",;]+@[^@\s<>\",;]+\.[^@\s<>\",;]+$")


def parse_allowed(raw):
    return [a.strip().lower() for a in re.split(r"[,\s;]+", raw or "") if a.strip()]


def recipients(to_field):
    """Split a To field into bare addresses. Raises ValueError on anything odd."""
    s = str(to_field or "")
    if "\n" in s or "\r" in s:
        raise ValueError("recipient field contains a line break")
    pairs = getaddresses([s])
    out = []
    for _name, addr in pairs:
        addr = addr.strip().lower()
        if not addr:
            continue
        if not ADDR_RE.match(addr):
            raise ValueError(f"'{addr}' is not a valid email address")
        out.append(addr)
    if not out:
        raise ValueError("no recipient")
    return out


def is_allowed(addr, allowed):
    addr = addr.lower()
    for a in allowed:
        if a.startswith("@") and addr.endswith(a) and addr.count("@") == 1:
            return True
        if a == addr:
            return True
    return False


def gate(cfg, to_field):
    """What the Send button will do. Returns {action: send|save|draft, ok, reason, label}."""
    mode = (cfg.get("SEND_MODE") or "dry").lower()
    try:
        addrs = recipients(to_field)
    except ValueError as e:
        return {"action": "draft", "mode": mode, "ok": False, "reason": str(e), "label": f"Save draft · {e}"}
    if mode != "live":
        return {"action": "save", "mode": "dry", "ok": True, "reason": "SEND_MODE=dry, nothing is sent",
                "label": "Save email (dry run)"}
    allowed = parse_allowed(cfg.get("SEND_ALLOWED"))
    blocked = [a for a in addrs if not is_allowed(a, allowed)]
    if blocked:
        return {"action": "draft", "mode": "live", "ok": False,
                "reason": f"{', '.join(blocked)} not in SEND_ALLOWED",
                "label": f"Save draft · {', '.join(blocked)} not in SEND_ALLOWED"}
    if not cfg.get("SMTP_HOST"):
        return {"action": "draft", "mode": "live", "ok": False, "reason": "SMTP_HOST is not set",
                "label": "Save draft · SMTP_HOST not set"}
    return {"action": "send", "mode": "live", "ok": True, "reason": "", "label": f"Send to {', '.join(addrs)}"}


def build_message(cfg, draft):
    msg = EmailMessage()
    msg["From"] = cfg.get("SMTP_FROM") or "orders@corvane.example"
    msg["To"] = draft["to"].replace("\n", " ").replace("\r", " ")
    msg["Subject"] = draft["subject"].replace("\n", " ").replace("\r", " ")
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="corvane.example")
    msg.set_content(draft["body"])
    return msg


def deliver(cfg, draft, folder, smtp_factory=None):
    """Send or save according to gate(). Always writes confirmation_email.eml to `folder`."""
    g = gate(cfg, draft.get("to"))
    msg = build_message(cfg, draft) if g["action"] != "draft" or recipients_ok(draft) else None
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "confirmation_email.eml")
    if msg is None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"X-Status: draft ({g['reason']})\nTo: {draft.get('to', '')}\nSubject: {draft.get('subject', '')}\n\n{draft.get('body', '')}")
        return {"sent": False, "saved": path, **g}
    if g["action"] == "send":
        factory = smtp_factory or smtplib.SMTP
        port = int(cfg.get("SMTP_PORT") or 587)
        with factory(cfg["SMTP_HOST"], port, timeout=20) as s:
            if config.truthy(cfg.get("SMTP_STARTTLS", "true")):
                s.starttls()
            if cfg.get("SMTP_USER"):
                s.login(cfg["SMTP_USER"], cfg.get("SMTP_PASSWORD") or "")
            s.send_message(msg)
        msg["X-Status"] = "sent"
    else:
        msg["X-Status"] = "dry-run, not sent" if g["action"] == "save" else f"draft ({g['reason']})"
    with open(path, "wb") as f:
        f.write(bytes(msg))
    return {"sent": g["action"] == "send", "saved": path, **g}


def save_draft(cfg, draft, folder):
    """Write the unsent draft to the customer folder. Sends nothing."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "confirmation_email.eml")
    try:
        msg = build_message(cfg, draft)
        msg["X-Status"] = "draft, not sent yet"
        data = bytes(msg)
    except Exception:
        data = (f"X-Status: draft, not sent yet\nTo: {draft.get('to', '')}\nSubject: {draft.get('subject', '')}"
                f"\n\n{draft.get('body', '')}").encode()
    with open(path, "wb") as f:
        f.write(data)
    return path


def recipients_ok(draft):
    try:
        recipients(draft.get("to"))
        return True
    except ValueError:
        return False
