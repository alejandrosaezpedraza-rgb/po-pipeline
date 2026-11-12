"""The one AI step: Claude reads the PO PDF and returns JSON matching the data contract.

Backends, picked by PO_EXTRACTOR (default "auto"):
  api     Anthropic Messages API, used when ANTHROPIC_API_KEY is set
  cli     `claude -p` headless (Claude Code), used when the CLI is installed and signed in
  replay  plays back samples/truth/<name>.json. For UI testing only; the UI labels it.
The reply is validated; on a bad reply we retry once, then raise ExtractionError.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

from . import config
from .validate import parse_json_reply, validate_po


class ExtractionError(Exception):
    pass


CONTRACT = """{
  "po_number": "", "po_date": "YYYY-MM-DD", "requested_ship_date": "YYYY-MM-DD",
  "buyer": {"company": "", "contact_name": "", "email": "", "phone": ""},
  "bill_to": {"name": "", "street": "", "city": "", "state": "", "zip": ""},
  "ship_to": {"name": "", "street": "", "city": "", "state": "", "zip": "", "store_number": ""},
  "payment_terms": "", "currency": "USD",
  "lines": [{"line": 1, "sku": "", "customer_item": "", "description": "", "qty": 0, "uom": "EA",
             "unit_price": 0.00, "extended": 0.00}],
  "subtotal": 0.00, "freight": 0.00, "tax": 0.00, "total": 0.00, "notes": ""
}"""

RULES = """Rules:
- Transcribe what the document says. Do not compute, correct or invent values.
- "sku" is the supplier's (Corvane Steel Works) item number, often labelled vendor part, mfr part, our item or VP.
  "customer_item" is the buyer's own item number if one is printed, else "".
- Dates as YYYY-MM-DD. Two-digit years are 20xx. Use "" for a date that is not printed.
- Numbers are plain JSON numbers: no currency symbols or thousands separators. Use 0 for freight or tax if none is shown.
- "buyer" is the purchasing company and the person who placed the order (buyer / purchasing agent / store manager).
- "bill_to" and "ship_to" are postal addresses; put a store or location number in ship_to.store_number.
- An address "name" is the organization or location name only: leave out "Attn:" lines, department names
  such as Accounts Payable, and store or branch numbers (those go in store_number).
- If no separate bill-to / invoice-to block is printed, bill_to is the buyer's own company name and address
  (usually its letterhead).
- "payment_terms" is the terms themselves (e.g. "Net 30", "2% 10 Net 30"), without remarks in parentheses.
- "street" is the street line only (include suite or PO box); "state" is the 2-letter code; "zip" as printed.
- If this is a change or revision to a PO, return the revised, current values (new quantities, new dates, new totals).
- "notes" holds any delivery or handling instructions printed on the PO, briefly, else "".
- Every key must be present. Reply with the JSON object only, no prose, no code fences."""


def build_prompt(pdf_ref, feedback=None):
    p = (f"You are reading a customer purchase order sent to Corvane Steel Works. {pdf_ref}\n\n"
         f"Return exactly one JSON object with this shape:\n{CONTRACT}\n\n{RULES}")
    if feedback:
        p += ("\n\nYour previous reply could not be used because:\n- " + "\n- ".join(feedback[:12])
              + "\nRead the document again and reply with corrected JSON only.")
    return p


def pdf_page_count(path):
    with open(path, "rb") as f:
        data = f.read()
    return max(1, len(re.findall(rb"/Type\s*/Page(?![s\w])", data)))


class ProgressParser:
    """Turns the streamed JSON text into short status lines as fields appear."""

    def __init__(self, emit):
        self.emit, self.buf, self.seen, self.skus = emit, "", set(), 0

    def feed(self, text):
        self.buf += text
        b = self.buf
        m = re.search(r'"po_number"\s*:\s*"([^"]+)"', b)
        if m and "po" not in self.seen:
            self.seen.add("po")
            self.emit(f"PO number {m.group(1)}")
        m = re.search(r'"company"\s*:\s*"([^"]+)"', b)
        if m and "company" not in self.seen:
            self.seen.add("company")
            self.emit(f"Found the customer: {m.group(1)}")
        m = re.search(r'"requested_ship_date"\s*:\s*"([^"]+)"', b)
        if m and "ship" not in self.seen:
            self.seen.add("ship")
            self.emit(f"Ship date {m.group(1)}")
        skus = re.findall(r'"sku"\s*:\s*"([^"]*)"', b)
        while self.skus < len(skus):
            self.skus += 1
            self.emit(f"Line {self.skus}: {skus[self.skus - 1] or '(no SKU)'}")
        m = re.search(r'"total"\s*:\s*([0-9.]+)\s*[,}\n]', b)
        if m and "total" not in self.seen:
            self.seen.add("total")
            self.emit(f"Total ${float(m.group(1)):,.2f}")


# ------------------------------------------------------------------ backends

def find_cli(cfg):
    if cfg.get("CLAUDE_BIN"):
        return cfg["CLAUDE_BIN"]
    found = shutil.which("claude")
    if found:
        return found
    # the official installer puts it here, and doesn't always add it to PATH
    for name in ("claude.exe", "claude"):
        p = os.path.join(os.path.expanduser("~"), ".local", "bin", name)
        if os.path.isfile(p):
            return p
    return ""


_auth_cache = {}


def cli_signed_in(binpath):
    """True / False from `claude auth status`, None if that can't be determined."""
    if binpath in _auth_cache and time.time() - _auth_cache[binpath][1] < 60:
        return _auth_cache[binpath][0]
    val = None
    try:
        r = subprocess.run([binpath, "auth", "status"], capture_output=True, text=True, timeout=20)
        val = bool(json.loads(r.stdout).get("loggedIn"))
    except Exception:
        val = None
    _auth_cache[binpath] = (val, time.time())
    return val


def describe_backend(cfg):
    mode = (cfg.get("PO_EXTRACTOR") or "auto").lower()
    model = cfg.get("PO_MODEL")
    if mode == "replay":
        return {"kind": "replay", "label": "Sample replay (no AI)", "model": "", "ready": True,
                "hint": "PO_EXTRACTOR=replay plays back samples/truth files. Set PO_EXTRACTOR=auto for real extraction."}
    if mode in ("auto", "api") and cfg.get("ANTHROPIC_API_KEY"):
        return {"kind": "api", "label": "Claude API", "model": model, "ready": True, "hint": ""}
    if mode == "api":
        return {"kind": "api", "label": "Claude API", "model": model, "ready": False,
                "hint": "PO_EXTRACTOR=api but ANTHROPIC_API_KEY is empty in .env"}
    binpath = find_cli(cfg)
    if not binpath:
        return {"kind": "none", "label": "No extractor", "model": model, "ready": False,
                "hint": "Install Claude Code and sign in (run `claude` once), or set ANTHROPIC_API_KEY in .env"}
    signed = cli_signed_in(binpath)
    if signed is False:
        return {"kind": "cli", "label": "Claude CLI (not signed in)", "model": model, "ready": False,
                "hint": "Run `claude` in a terminal and sign in, or set ANTHROPIC_API_KEY in .env"}
    return {"kind": "cli", "label": "Claude CLI", "model": model, "ready": True, "hint": "", "bin": binpath}


def _run_cli(pdf_path, prompt_feedback, cfg, on_text, on_status):
    binpath = find_cli(cfg)
    if not binpath:
        raise ExtractionError("Claude CLI not found. Install Claude Code and sign in, or set ANTHROPIC_API_KEY.")
    work = tempfile.mkdtemp(prefix="po-extract-")
    try:
        target = os.path.join(work, "po.pdf")
        shutil.copyfile(pdf_path, target)
        prompt = build_prompt(f"Use the Read tool to read the PDF file at {target}, every page.", prompt_feedback)
        cmd = [binpath, "-p", "--model", cfg["PO_MODEL"], "--output-format", "stream-json", "--verbose",
               "--include-partial-messages", "--allowedTools", "Read", "--max-turns", "8",
               "--no-session-persistence", "--add-dir", work]
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)  # CLI mode uses the CLI's own sign-in
        proc = subprocess.Popen(cmd, cwd=work, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, text=True, encoding="utf-8", errors="replace")
        timeout = float(cfg.get("EXTRACT_TIMEOUT") or 240)
        timer = threading.Timer(timeout, proc.kill)
        timer.start()
        err_chunks = []
        threading.Thread(target=lambda: err_chunks.append(proc.stderr.read()), daemon=True).start()
        proc.stdin.write(prompt)
        proc.stdin.close()
        result, is_error, pages = None, False, pdf_page_count(pdf_path)
        reads = 0
        for raw in proc.stdout:
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if t == "stream_event":
                e = ev.get("event") or {}
                d = e.get("delta") or {}
                if e.get("type") == "content_block_delta" and d.get("type") == "text_delta":
                    on_text(d.get("text", ""))
            elif t == "assistant":
                for block in (ev.get("message") or {}).get("content") or []:
                    if block.get("type") == "tool_use" and block.get("name") == "Read":
                        reads += 1
                        on_status(f"Reading page 1 of {pages}" if pages > 1 else "Reading page 1")
            elif t == "user" and reads:
                if pages > 1:
                    on_status(f"Read {pages} pages")
            elif t == "result":
                result, is_error = ev.get("result"), bool(ev.get("is_error"))
        proc.wait()
        timer.cancel()
        stderr = "".join(err_chunks).strip()
        if is_error or result is None:
            msg = str(result or stderr or "no output").strip()
            low = msg.lower()
            if "login" in low or "log in" in low or "api key" in low or "not logged" in low:
                raise ExtractionError("Claude CLI is not signed in. Run `claude` in a terminal and sign in, "
                                      "or set ANTHROPIC_API_KEY in .env.")
            if proc.returncode and proc.returncode < 0:
                msg = f"timed out after {timeout:.0f}s"
            raise ExtractionError(f"Claude CLI failed (exit {proc.returncode}): {msg[:300]}")
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _run_api(pdf_path, prompt_feedback, cfg, on_text, on_status):
    with open(pdf_path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    pages = pdf_page_count(pdf_path)
    on_status(f"Sending {pages} page{'s' if pages > 1 else ''} to Claude")
    body = {"model": cfg["PO_MODEL"], "max_tokens": 8000, "stream": True,
            "messages": [{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}},
                {"type": "text", "text": build_prompt("The PDF is attached.", prompt_feedback)}]}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                 method="POST", headers={"x-api-key": cfg["ANTHROPIC_API_KEY"],
                                                         "anthropic-version": "2023-06-01",
                                                         "content-type": "application/json"})
    out, first = [], True
    try:
        with urllib.request.urlopen(req, timeout=float(cfg.get("EXTRACT_TIMEOUT") or 240)) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:].strip() or "{}")
                if ev.get("type") == "content_block_delta" and (ev.get("delta") or {}).get("type") == "text_delta":
                    if first:
                        on_status("Reading page 1" + (f" of {pages}" if pages > 1 else ""))
                        first = False
                    out.append(ev["delta"]["text"])
                    on_text(ev["delta"]["text"])
                elif ev.get("type") == "error":
                    raise ExtractionError(f"Claude API error: {ev.get('error', {}).get('message')}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", {}).get("message")
        except Exception:
            msg = ""
        raise ExtractionError(f"Claude API returned HTTP {e.code}: {msg or e.reason}") from None
    except urllib.error.URLError as e:
        raise ExtractionError(f"Could not reach the Claude API: {e.reason}") from None
    return "".join(out)


def _run_replay(pdf_path, prompt_feedback, cfg, on_text, on_status):
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    truth_dir = os.path.join(config.ROOT, "samples", "truth")
    path = os.path.join(truth_dir, stem + ".json")
    if not os.path.exists(path):
        # an uploaded copy of a sample keeps its original name in the run folder's meta
        meta = os.path.join(os.path.dirname(pdf_path), "meta.json")
        if os.path.exists(meta):
            with open(meta, encoding="utf-8") as f:
                stem = os.path.splitext(json.load(f).get("filename", ""))[0]
            path = os.path.join(truth_dir, stem + ".json")
    if not os.path.exists(path):
        raise ExtractionError("This setup only plays back the 5 sample POs, without AI. Choose one from Try a sample. "
                              "(To read any PDF with Claude, set PO_EXTRACTOR=auto.)")
    with open(path, encoding="utf-8") as f:
        text = json.dumps(json.load(f), indent=1)
    on_status("Reading page 1 (replay)")
    for i in range(0, len(text), 40):
        on_text(text[i:i + 40])
        time.sleep(0.06)
    return text


BACKENDS = {"cli": _run_cli, "api": _run_api, "replay": _run_replay}


def extract(pdf_path, cfg, status=lambda s: None, backend=None):
    """Return a validated PO dict. `backend` overrides the configured one (tests use this)."""
    info = describe_backend(cfg)
    run = backend or BACKENDS.get(info["kind"])
    if run is None or (backend is None and not info["ready"]):
        raise ExtractionError(info.get("hint") or "No extractor configured")
    feedback = None
    for attempt in (1, 2):
        parser = ProgressParser(status)
        if attempt == 2:
            status("Reply didn't validate, asking again")
        text = run(pdf_path, feedback, cfg, parser.feed, status)
        try:
            obj = parse_json_reply(text)
            clean, errors = validate_po(obj)
        except ValueError as e:
            errors = [str(e)]
        if not errors:
            status(f"{len(clean['lines'])} line item{'s' if len(clean['lines']) != 1 else ''}")
            return clean
        feedback = errors
    raise ExtractionError("Claude's reply didn't match the data contract twice: " + "; ".join(feedback[:4]))
