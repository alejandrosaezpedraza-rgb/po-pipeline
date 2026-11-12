"""Shared test fixtures: a throwaway demo ERP on a random port, temp state, truth files."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SAMPLES = os.path.join(ROOT, "samples")
SLUGS = ["edi-printout", "corporate-form", "store-order", "change-form", "distributor-po"]


def truth(slug):
    with open(os.path.join(SAMPLES, "truth", slug + ".json"), encoding="utf-8") as f:
        return json.load(f)


def erp_items():
    from erp import seed_data
    return {s: {"sku": s, "description": d, "category": c, "uom": u, "list_price": p}
            for s, d, c, u, p in seed_data.ITEMS}


class TempERP:
    """Runs the real demo ERP server in-process against a temp database."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="erp-test-")
        os.environ["ERP_DB"] = os.path.join(self.dir, "erp.db")
        os.environ["ERP_QUIET"] = "1"
        from erp import core, server
        core.init_db()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.srv.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
        os.environ.pop("ERP_DB", None)
        shutil.rmtree(self.dir, ignore_errors=True)


def wait_for(fn, timeout=10.0, msg="condition"):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {msg}")
