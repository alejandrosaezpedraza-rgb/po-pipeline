"""Demo password for the hosted version. Off when DEMO_PASSWORD is empty (local use)."""
from __future__ import annotations

import hashlib
import hmac
import html
import secrets

COOKIE = "po_demo"
MAX_AGE = 30 * 24 * 3600  # one sign-in lasts 30 days on that device


class Gate:
    def __init__(self, password, secret, secure=False):
        self.password = password or ""
        # Without a fixed secret everyone is signed out whenever the server restarts.
        self.secret = (secret or secrets.token_hex(32)).encode()
        self.secure = secure

    @property
    def enabled(self):
        return bool(self.password)

    def token(self):
        # Includes the password, so changing it signs everyone out.
        return hmac.new(self.secret, b"po-demo:" + self.password.encode(), hashlib.sha256).hexdigest()

    def check_password(self, typed):
        return hmac.compare_digest(str(typed or "").encode(), self.password.encode())

    def allowed(self, cookie_header):
        if not self.enabled:
            return True
        for part in (cookie_header or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and hmac.compare_digest(value.encode(), self.token().encode()):
                return True
        return False

    def set_cookie(self):
        c = f"{COOKIE}={self.token()}; Path=/; Max-Age={MAX_AGE}; HttpOnly; SameSite=Lax"
        return c + ("; Secure" if self.secure else "")


def login_page(error=""):
    msg = f'<p class="err" role="alert">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>PO Intake · demo</title>
<link rel="icon" href="/favicon.svg">
<style>
:root {{ --bg:#0c0e12; --bg-glow:#161b26; --panel:#161a22; --line:#262c38; --line2:#323a48; --text:#e8ebf1; --dim:#8a93a5;
  --blue:#6ea8fe; --ink-on-blue:#0a0d14; --red:#ef6b6b; --green:#45c486;
  --font-sans:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; min-height:100vh; display:grid; place-items:center; padding:16px; color:var(--text);
  background:radial-gradient(1200px 600px at 50% -200px, var(--bg-glow) 0%, var(--bg) 60%); font:14px/1.45 var(--font-sans); }}
form {{ width:min(360px,100%); background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:24px; display:grid; gap:14px; }}
.brand {{ display:flex; align-items:center; gap:10px; font-weight:700; font-size:15px; }}
.mark {{ width:10px; height:10px; border-radius:3px; background:linear-gradient(135deg,var(--blue),var(--green)); }}
p {{ margin:0; color:var(--dim); }}
label {{ display:grid; gap:4px; font-size:12px; color:var(--dim); }}
input {{ font:inherit; color:inherit; background:#11141a; border:1px solid var(--line2); border-radius:7px; padding:8px 10px; }}
input:focus {{ outline:none; border-color:var(--blue); }}
button {{ font:inherit; font-weight:600; background:var(--blue); color:var(--ink-on-blue); border:0; border-radius:8px; padding:8px 12px; cursor:pointer; }}
.err {{ color:var(--red); }}
</style></head><body>
<form method="post" action="/login">
  <div class="brand"><span class="mark"></span>PO Intake</div>
  <p>A demo of purchase order intake for a made-up manufacturer. Enter the password you were sent.</p>
  {msg}
  <label for="password">Password<input id="password" name="password" type="password" autocomplete="current-password" autofocus required></label>
  <button type="submit">Open the demo</button>
</form></body></html>"""
