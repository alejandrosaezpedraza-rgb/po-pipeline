"""PO pipeline web app: static UI, JSON API and live updates (Server-Sent Events).

Run:  python -m app.server        then open http://127.0.0.1:7820
"""
from __future__ import annotations

import html
import http.client
import json
import mimetypes
import os
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import access, config, extract, mailbox
from .crm import CRM
from .erp_client import ERPClient
from .pipeline import Pipeline, PipelineError

HOST = "127.0.0.1"
WEB = os.path.join(config.ROOT, "web")
SAMPLES = os.path.join(config.ROOT, "samples")
MAX_UPLOAD = 25 * 1024 * 1024


class App:
    def __init__(self, cfg, pipeline, crm, erp):
        self.cfg, self.pipeline, self.crm, self.erp = cfg, pipeline, crm, erp
        self.port = int(cfg["APP_PORT"])
        self.hosted = config.truthy(cfg.get("HOSTED"))
        self.gate = access.Gate(cfg.get("DEMO_PASSWORD"), cfg.get("SESSION_SECRET"), secure=self.hosted)

    def public_config(self):
        enabled, missing = mailbox.settings_ok(self.cfg)
        return {
            "extractor": {k: v for k, v in extract.describe_backend(self.cfg).items() if k != "bin"},
            "send_mode": (self.cfg.get("SEND_MODE") or "dry").lower(),
            "send_allowed": [a for a in (self.cfg.get("SEND_ALLOWED") or "").replace(";", ",").split(",") if a.strip()],
            "erp_url": self.erp.public, "erp_up": self.erp.health(), "hosted": self.hosted,
            "mailbox": {"enabled": enabled, "missing": missing, "folder": self.cfg.get("IMAP_FOLDER")},
        }


def make_handler(app: App):
    erp_target = urlparse(app.erp.base)

    class Handler(BaseHTTPRequestHandler):
        server_version = "POPipeline/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            if "/events" not in str(args[0] if args else ""):
                sys.stderr.write("[app] " + fmt % args + "\n")

        # ---------------------------------------------------- helpers
        def _send(self, code, body, ctype="application/json", headers=None):
            if isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj))

        def _body(self, limit=MAX_UPLOAD):
            """The request body, read once. Every POST reads it, so a keep-alive connection stays in sync."""
            if not hasattr(self, "_raw_body"):
                n = int(self.headers.get("Content-Length") or 0)
                if n > limit:
                    self.close_connection = True
                    raise PipelineError("Upload too large", 413)
                self._raw_body = self.rfile.read(n) if n else b""
            return self._raw_body

        def _jbody(self):
            try:
                return json.loads(self._body() or b"{}")
            except json.JSONDecodeError:
                raise PipelineError("Body is not valid JSON") from None

        def _static(self, rel):
            path = os.path.realpath(os.path.join(WEB, rel))
            if not path.startswith(os.path.realpath(WEB)) or not os.path.isfile(path):
                return self._send(404, "not found", "text/plain")
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            with open(path, "rb") as f:
                self._send(200, f.read(), ctype)

        # ---------------------------------------------------- GET
        def _gate(self, path):
            """True when the request may continue. Answers it otherwise (login redirect or 401)."""
            if path in ("/login", "/favicon.svg") or app.gate.allowed(self.headers.get("Cookie")):
                return True
            self.close_connection = True  # a refused request's body is never read
            if path.startswith("/api/") or path == "/events" or self.command != "GET":
                self._json(401, {"error": "Sign in with the demo password first"})
            else:
                self._send(303, b"", "text/plain", {"Location": "/login"})
            return False

        def _proxy_erp(self):
            """Hosted: the demo ERP runs inside this service; /erp/... reaches it."""
            rest = self.path[len("/erp"):] or "/"
            body = self._body() if self.command == "POST" else None
            conn = http.client.HTTPConnection(erp_target.hostname, erp_target.port, timeout=15)
            try:
                headers = {"Content-Type": self.headers.get("Content-Type") or "application/octet-stream"}
                conn.request(self.command, rest, body=body, headers=headers)
                r = conn.getresponse()
                data = r.read()
                extra = {"Location": r.getheader("Location")} if r.getheader("Location") else None
                self._send(r.status, data, r.getheader("Content-Type") or "text/plain", extra)
            except OSError:
                self._send(502, "The demo ERP is not responding", "text/plain")
            finally:
                conn.close()

        def _folder(self, path):
            """Hosted: show the customer folder's files in the browser (there is no file manager to open)."""
            run = app.pipeline.run
            node = run["nodes"]["folder"] if run else {}
            if node.get("status") != "done":
                return self._send(404, "The folder has not been written yet", "text/plain")
            folder = node["path"]
            names = sorted(f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)))
            name = unquote(path[len("/folder/"):]) if path.startswith("/folder/") else ""
            if name:
                if name not in names:
                    return self._send(404, "No such file", "text/plain")
                ctype = {".pdf": "application/pdf", ".json": "application/json; charset=utf-8"}.get(
                    os.path.splitext(name)[1].lower(), "text/plain; charset=utf-8")
                with open(os.path.join(folder, name), "rb") as f:
                    return self._send(200, f.read(), ctype)
            rows = "".join(f'<li><a href="/folder/{html.escape(n)}" target="_blank">{html.escape(n)}</a></li>' for n in names)
            page = (f'<!doctype html><meta charset="utf-8"><title>{html.escape(run["folder"]["path"])}</title>'
                    '<style>body{background:#0c0e12;color:#e8ebf1;font:14px/1.6 system-ui,sans-serif;padding:24px}'
                    'a{color:#6ea8fe}code{color:#8a93a5}</style>'
                    f'<h1 style="font-size:16px">Customer folder</h1><code>{html.escape(run["folder"]["path"])}/</code><ul>{rows}</ul>')
            self._send(200, page, "text/html; charset=utf-8")

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/healthz":
                return self._send(200, "ok", "text/plain")
            if not self._gate(path):
                return
            try:
                if path == "/login":
                    return self._send(200, access.login_page(), "text/html; charset=utf-8")
                if path == "/erp" or path.startswith("/erp/"):
                    return self._proxy_erp()
                if app.hosted and (path == "/folder" or path.startswith("/folder/")):
                    return self._folder(path)
                if path == "/":
                    return self._static("index.html")
                if path in ("/app.js", "/style.css", "/favicon.svg"):
                    return self._static(path[1:])
                if path == "/events":
                    return self._events()
                if path == "/api/state":
                    return self._json(200, dict(app.pipeline.snapshot(), config=app.public_config()))
                if path == "/api/config":
                    return self._json(200, app.public_config())
                if path == "/api/pdf":
                    p = app.pipeline.pdf_path()
                    if not p or not os.path.exists(p):
                        return self._send(404, "no PDF", "text/plain")
                    with open(p, "rb") as f:
                        return self._send(200, f.read(), "application/pdf",
                                          {"Content-Disposition": f'inline; filename="{os.path.basename(p)}"'})
                if path == "/api/samples":
                    names = sorted(f for f in os.listdir(SAMPLES) if f.endswith(".pdf"))
                    return self._json(200, names)
                if path == "/api/crm":
                    return self._json(200, app.crm.companies())
                if path.startswith("/api/crm/"):
                    c = app.crm.company(path.rsplit("/", 1)[1]) if path.rsplit("/", 1)[1].isdigit() else None
                    return self._json(200, c) if c else self._json(404, {"error": "no such company"})
                self._send(404, "not found", "text/plain")
            except PipelineError as e:
                self._json(e.code, {"error": str(e), "details": e.details})

        def _events(self):
            q = queue.Queue(maxsize=200)

            def push(snap):
                try:
                    q.put_nowait(snap)
                except queue.Full:
                    pass
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            app.pipeline.subscribe(push)
            try:
                first = dict(app.pipeline.snapshot(), config=app.public_config())
                self.wfile.write(f"data: {json.dumps(first)}\n\n".encode())
                self.wfile.flush()
                while True:
                    try:
                        snap = q.get(timeout=15)
                        while not q.empty():  # coalesce bursts, send the newest
                            snap = q.get_nowait()
                        self.wfile.write(f"data: {json.dumps(snap)}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                app.pipeline.unsubscribe(push)
                self.close_connection = True

        # ---------------------------------------------------- POST
        def do_POST(self):
            origin = self.headers.get("Origin")
            if origin and origin != "null" and urlparse(origin).netloc != self.headers.get("Host"):
                self.close_connection = True
                return self._json(403, {"error": "cross-origin request refused"})
            path = urlparse(self.path).path
            try:
                self._body()
            except PipelineError as e:
                return self._json(e.code, {"error": str(e)})
            if path == "/login":
                typed = parse_qs(self._body().decode("utf-8", "replace")).get("password", [""])[0]
                if app.gate.enabled and app.gate.check_password(typed):
                    return self._send(303, b"", "text/plain", {"Location": "/", "Set-Cookie": app.gate.set_cookie()})
                return self._send(401, access.login_page("That password is not right."), "text/html; charset=utf-8")
            if not self._gate(path):
                return
            if path.startswith("/erp/"):
                return self._proxy_erp()
            p = app.pipeline
            try:
                if path == "/api/upload":
                    data = self._body(MAX_UPLOAD)
                    name = unquote(self.headers.get("X-Filename") or "po.pdf")
                    return self._json(200, {"run": p.start(data, name, "upload")})
                if path.startswith("/api/sample/"):
                    name = os.path.basename(unquote(path.rsplit("/", 1)[1]))
                    fp = os.path.join(SAMPLES, name)
                    if not name.endswith(".pdf") or not os.path.isfile(fp):
                        raise PipelineError("No such sample", 404)
                    with open(fp, "rb") as f:
                        return self._json(200, {"run": p.start(f.read(), name, "sample")})
                if path == "/api/recheck":
                    return self._json(200, p.recheck(self._jbody().get("po") or {}))
                if path == "/api/accept":
                    p.accept(self._jbody().get("po") or {})
                    return self._json(200, {"ok": True})
                if path == "/api/email/gate":
                    return self._json(200, p.email_gate(self._jbody().get("to")))
                if path == "/api/email/send":
                    return self._json(200, p.send_email(self._jbody().get("draft") or {}))
                if path == "/api/retry-read":
                    p.rerun_read()
                    return self._json(200, {"ok": True})
                if path.startswith("/api/retry/"):
                    p.retry(path.rsplit("/", 1)[1])
                    return self._json(200, {"ok": True})
                if path == "/api/reset":
                    p.reset()
                    return self._json(200, {"ok": True})
                if path == "/api/open-folder":
                    return self._json(200, {"opened": p.open_folder()})
                self._json(404, {"error": "not found"})
            except PipelineError as e:
                self._json(e.code, {"error": str(e), "details": e.details})

    return Handler


def build(cfg=None):
    cfg = cfg or config.load()
    erp = ERPClient(cfg["ERP_URL"], public_url=cfg.get("ERP_PUBLIC_URL"))
    crm = CRM(os.path.join(cfg["STATE_DIR"], "crm.db"), os.path.join(SAMPLES, "customers.json"))
    pipeline = Pipeline(cfg, erp, crm)
    return App(cfg, pipeline, crm, erp)


def start_mailbox(app: App):
    enabled, missing = mailbox.settings_ok(app.cfg)
    if not enabled:
        app.pipeline.mailbox = {"state": "off"}
        return None
    if missing:
        app.pipeline.mailbox = {"state": "error", "error": "Missing in .env: " + ", ".join(missing)}
        return None
    handled = mailbox.HandledList(os.path.join(app.cfg["STATE_DIR"], "handled_messages.json"))

    def on_message(m):
        p = app.pipeline
        run = p.run
        idle = run is None or run["nodes"]["email"]["status"] == "done" or run["nodes"]["read"]["status"] == "error"
        if not idle or p.busy():
            return False
        fn, data = m["pdfs"][0]
        p.start(data, fn, "email", {"subject": m["subject"], "from": m["from"], "message_id": m["message_id"],
                                    "raw": m["raw"]})
        return True

    w = mailbox.Watcher(app.cfg, handled, on_message, app.pipeline.set_mailbox)
    app.pipeline.mailbox = {"state": "starting"}
    w.start()
    return w


def main(host=HOST, cfg=None):
    app = build(cfg)
    threading.Thread(target=app.public_config, daemon=True).start()  # warm the CLI sign-in check
    start_mailbox(app)
    srv = ThreadingHTTPServer((host, app.port), make_handler(app))
    srv.daemon_threads = True
    print(f"PO pipeline on http://{host}:{app.port}" + (" (demo password on)" if app.gate.enabled else ""), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
