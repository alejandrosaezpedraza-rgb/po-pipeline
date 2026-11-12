"""Settings: .env file, then real environment variables (which win)."""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "APP_PORT": "7820",
    "ERP_URL": "http://127.0.0.1:7811",
    "ERP_PUBLIC_URL": "",            # ERP address for links in the page; hosted: "/erp"
    "HOSTED": "",                    # set by app/hosted.py: one public web service
    "DEMO_PASSWORD": "",             # hosted: the password visitors type
    "SESSION_SECRET": "",            # hosted: signs the sign-in cookie
    "PO_MODEL": "claude-haiku-5-5",
    "PO_EXTRACTOR": "auto",          # auto | cli | api | replay
    "CLAUDE_BIN": "",
    "ANTHROPIC_API_KEY": "",
    "EXTRACT_TIMEOUT": "240",
    "SEND_MODE": "dry",              # dry | live
    "SEND_ALLOWED": "",
    "SMTP_HOST": "", "SMTP_PORT": "587", "SMTP_USER": "", "SMTP_PASSWORD": "",
    "SMTP_FROM": "orders@corvane.example", "SMTP_STARTTLS": "true",
    "MAILBOX_WATCH": "off",
    "IMAP_HOST": "", "IMAP_PORT": "993", "IMAP_USER": "", "IMAP_PASSWORD": "",
    "IMAP_FOLDER": "INBOX", "IMAP_POLL_SECONDS": "60", "IMAP_LOOKBACK_DAYS": "3",
    "STATE_DIR": os.path.join(ROOT, "state"),
    "CUSTOMERS_DIR": os.path.join(ROOT, "customers"),
}


def read_env_file(path):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[k.strip()] = v
    return out


def load(env_path=None, overrides=None):
    cfg = dict(DEFAULTS)
    cfg.update(read_env_file(env_path or os.path.join(ROOT, ".env")))
    for k in DEFAULTS:
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    cfg.update(overrides or {})
    return cfg


def truthy(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on")
