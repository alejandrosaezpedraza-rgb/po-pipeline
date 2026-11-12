"""Hosted entry point (Render and similar): one public web service.

    python -m app.hosted

- Listens on 0.0.0.0:$PORT (the host sets PORT).
- Runs the demo ERP inside the same process on 127.0.0.1:7811; people reach it at /erp.
- Turns on the demo password when DEMO_PASSWORD is set.
- Defaults to PO_EXTRACTOR=replay (the 5 samples, no AI) and SEND_MODE=dry unless the
  host's environment says otherwise. The mailbox watcher stays off.
"""
from __future__ import annotations

import os
import threading
from http.server import ThreadingHTTPServer

os.environ.setdefault("ERP_BASE_PATH", "/erp")  # read when erp.server is imported

from erp import core as erp_core  # noqa: E402
from erp import server as erp_server  # noqa: E402

from . import config, server  # noqa: E402

ERP_PORT = int(os.environ.get("ERP_INTERNAL_PORT", "7811"))


def main():
    erp_core.init_db()
    erp = ThreadingHTTPServer(("127.0.0.1", ERP_PORT), erp_server.Handler)
    erp.daemon_threads = True
    threading.Thread(target=erp.serve_forever, daemon=True).start()
    print(f"Demo ERP inside the service on 127.0.0.1:{ERP_PORT}, public at /erp", flush=True)

    cfg = config.load(overrides={
        "HOSTED": "1",
        "APP_PORT": os.environ.get("PORT", "10000"),
        "ERP_URL": f"http://127.0.0.1:{ERP_PORT}",
        "ERP_PUBLIC_URL": "/erp",
        "MAILBOX_WATCH": "off",
        "PO_EXTRACTOR": os.environ.get("PO_EXTRACTOR") or "replay",
        "SEND_MODE": os.environ.get("SEND_MODE") or "dry",
    })
    if not cfg.get("DEMO_PASSWORD"):
        print("WARNING: DEMO_PASSWORD is not set, so anyone with the link can use the demo.", flush=True)
    server.main(host="0.0.0.0", cfg=cfg)


if __name__ == "__main__":
    main()
