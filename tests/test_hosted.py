"""The hosted service: demo password, the ERP reached through /erp, same-site POSTs only."""
import http.client
import os
import shutil
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode

from helpers import SAMPLES, TempERP

from app import server
from app.crm import CRM
from app.erp_client import ERPClient
from app.pipeline import Pipeline
from erp import server as erp_server

PASSWORD = "copper kettle seven"


class HostedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.erp = TempERP()
        cls.tmp = tempfile.mkdtemp(prefix="hosted-test-")
        cfg = {"STATE_DIR": os.path.join(cls.tmp, "state"), "CUSTOMERS_DIR": os.path.join(cls.tmp, "customers"),
               "APP_PORT": "0", "HOSTED": "1", "DEMO_PASSWORD": PASSWORD, "SESSION_SECRET": "test-secret",
               "PO_EXTRACTOR": "replay", "SEND_MODE": "dry", "PO_MODEL": "", "ERP_URL": cls.erp.url,
               "ERP_PUBLIC_URL": "/erp"}
        erp = ERPClient(cls.erp.url, public_url="/erp")
        crm = CRM(os.path.join(cls.tmp, "state", "crm.db"), os.path.join(SAMPLES, "customers.json"))
        cls.app = server.App(cfg, Pipeline(cfg, erp, crm), crm, erp)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(cls.app))
        cls.srv.daemon_threads = True
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls._base = erp_server.BASE
        erp_server.BASE = "/erp"  # as app/hosted.py sets it

    @classmethod
    def tearDownClass(cls):
        erp_server.BASE = cls._base
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.erp.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r, data

    def cookie(self):
        r, _ = self.req("POST", "/login", urlencode({"password": PASSWORD}),
                        {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status, 303)
        return r.getheader("Set-Cookie").split(";")[0]

    def test_health_check_needs_no_password(self):
        r, data = self.req("GET", "/healthz")
        self.assertEqual((r.status, data), (200, b"ok"))

    def test_everything_else_needs_the_password(self):
        r, _ = self.req("GET", "/")
        self.assertEqual((r.status, r.getheader("Location")), (303, "/login"))
        for path in ("/api/state", "/events", "/erp/"):
            r, _ = self.req("GET", path)
            self.assertIn(r.status, (303, 401), path)
        r, _ = self.req("POST", "/api/reset", "{}")
        self.assertEqual(r.status, 401)
        r, data = self.req("GET", "/login")
        self.assertEqual(r.status, 200)
        self.assertIn(b'name="password"', data)

    def test_wrong_password(self):
        r, data = self.req("POST", "/login", urlencode({"password": "guess"}),
                           {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status, 401)
        self.assertIsNone(r.getheader("Set-Cookie"))
        self.assertIn(b"not right", data)

    def test_right_password_signs_in(self):
        cookie = self.cookie()
        self.assertIn("HttpOnly", self.req("POST", "/login", urlencode({"password": PASSWORD}),
                                           {"Content-Type": "application/x-www-form-urlencoded"})[0].getheader("Set-Cookie"))
        r, _ = self.req("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(r.status, 200)
        r, _ = self.req("GET", "/api/state", headers={"Cookie": cookie})
        self.assertEqual(r.status, 200)
        r, _ = self.req("GET", "/", headers={"Cookie": "po_demo=forged"})
        self.assertEqual(r.status, 303)

    def test_erp_is_reached_through_erp_path(self):
        cookie = self.cookie()
        r, data = self.req("GET", "/erp/", headers={"Cookie": cookie})
        self.assertEqual(r.status, 200)
        self.assertIn(b'href="/erp/items"', data)
        r, data = self.req("GET", "/erp/items?q=workbnch", headers={"Cookie": cookie})
        self.assertIn(b"WB-", data)
        r, data = self.req("GET", "/api/config", headers={"Cookie": cookie})
        self.assertIn(b'"erp_url": "/erp"', data)
        self.assertIn(b'"hosted": true', data)

    def test_cross_site_post_refused(self):
        cookie = self.cookie()
        r, _ = self.req("POST", "/api/reset", "{}", {"Cookie": cookie, "Origin": "https://evil.example"})
        self.assertEqual(r.status, 403)
        r, _ = self.req("POST", "/api/reset", "{}", {"Cookie": cookie, "Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(r.status, 200)

    def test_folder_view_before_folder_exists(self):
        cookie = self.cookie()
        self.req("POST", "/api/reset", "{}", {"Cookie": cookie})
        r, _ = self.req("GET", "/folder", headers={"Cookie": cookie})
        self.assertEqual(r.status, 404)


if __name__ == "__main__":
    unittest.main()
