# PO pipeline

A local web app that takes a customer purchase order PDF and gets it into the ERP and the CRM, for a fictional
manufacturer of steel carts, shelving and workbenches (Corvane Steel Works). All companies, people and addresses
are made up.

```
PDF ─▶ 1 PO arrives ─▶ 2 Claude reads it ─▶ 3 a person reviews ─┬▶ 4 ERP (sales order)
       (drop / mailbox)   + code checks       and clicks Accept   ├▶ 4 CRM (company + contact)   ─▶ 5 confirmation email
                                                                  └▶ 4 customer folder
```

- **Claude does one job:** read a messy PDF and return JSON matching the data contract (`app/extract.py`).
- **Everything after that is ordinary code** that does the same thing every time: validation (`app/validate.py`),
  checks and routing (`app/checks.py`), ERP posting, CRM upsert, files, email.
- **A person approves every order.** Nothing is written to the ERP or the CRM until Accept is clicked in the review
  sheet, and the routing code has no auto-approve path (tested in `tests/test_checks.py` and `tests/test_pipeline.py`).

Every step is a node on a dark pipeline view that updates live (Server-Sent Events). There is a timestamped run log
and a Reset button.

## Run it

Needs Python 3.9+ and nothing else (standard library only; no build step, nothing from a CDN). On Windows, run it
from Git Bash.

```bash
./start.sh
```

That checks what's needed, starts the demo ERP on http://127.0.0.1:7811 and the app on http://127.0.0.1:7820,
and opens the page. Ctrl-C stops both. Logs go to `state/logs/`.

```bash
./start.sh --reset
```

Restores a clean state first: deletes ERP orders, the CRM (re-seeded from `samples/customers.json`), runs,
`customers/` folders and the handled-mail list.

Then drop a PDF anywhere on the page, or use **Try a sample**.

### Extraction: sign in once

Extraction uses, in this order:

1. The **Anthropic API** if `ANTHROPIC_API_KEY` is set in `.env`.
2. Otherwise the **`claude` CLI** (Claude Code) in headless mode, if it is installed and signed in. No API key
   needed. Run `claude` once in a terminal and sign in. If it isn't on your PATH, set `CLAUDE_BIN` to its full path.

The model comes from `PO_MODEL` (default `claude-haiku-5-5`, a fast current model). The reply is validated
against the data contract. A bad reply is retried once with the validation errors, then the node shows a clear
error and a **Try again** button.

The badge in the top bar shows which extractor is active. For UI work without any AI there is
`PO_EXTRACTOR=replay`, which plays back the truth files for the 5 samples only and is labeled "Replay (test mode,
no AI)" everywhere it appears.

### Settings

Copy `.env.example` to `.env`. Every setting is explained there. The ones that matter most:

| Setting | Default | What it does |
|---|---|---|
| `PO_MODEL` | `claude-haiku-5-5` | Model that reads the PDF |
| `ANTHROPIC_API_KEY` | empty | Use the API instead of the CLI |
| `SEND_MODE` | `dry` | `dry` saves the confirmation email as `confirmation_email.eml` and sends nothing |
| `SEND_ALLOWED` | empty | In `live` mode, the only addresses (or `@domain`s) that can receive mail |
| `MAILBOX_WATCH` | `off` | `on` polls an IMAP folder for POs |

## The pipeline, step by step

1. **PO arrives.** Drag a PDF onto the window, choose one, pick a sample, or (optionally) the mailbox watcher
   picks one up. The node shows the source.
2. **Claude reads the PO.** Status lines stream in as fields appear in the reply ("Reading page 1 of 2",
   "Found the customer: …", "Line 3: WB-4824", "8 line items"). Then the checks run and show as chips:
   - totals add up (qty × price = extended, lines = subtotal, subtotal + freight + tax = total)
   - every SKU exists in the ERP item master (with a typo-tolerant suggestion if not)
   - prices match the price list
   - customer known or new (exact name, then normalized name, then normalized street + ZIP)
   - ship date present (and not before the PO date)
   - PO number not already in the ERP
3. **Review.** A yellow "Needs your review" badge. The sheet shows the PDF on the left and, on the right, what goes
   to the CRM, what goes to the ERP, and which files go to the customer folder. Every field is editable, lines can
   be added and removed, totals recompute as you type, changed fields are highlighted and the checks re-run.
   Accept stays disabled while something would make the ERP refuse the order (unknown SKU, totals that don't add
   up, duplicate PO, missing PO number or company).
4. **Fan-out**, in parallel:
   - **ERP:** stages the order, then approves it, through the same two functions the ERP's own UI uses
     (`erp/core.py: stage_order`, `approve_order`), so the order looks the same in the ERP however it got there.
     **Open in ERP** goes to the order page.
   - **CRM:** creates or updates the company and the buyer contact, and logs the PO. **Open in CRM** goes to
     `#/crm/<id>`.
   - **Customer folder:** `customers/<Customer>/<PO number>/` gets the PDF, the original email (if it came by mail),
     `extracted.json` as approved, and the confirmation email. **Open folder** opens it.
5. **Confirmation email.** An editable draft back to the buyer, built from the approved data:
   "We received PO 88213 for 4 lines, $16,110.00, shipping Nov 12, 2026. Our sales order number is SO-11901."
   The button says what it will do: save (dry run), send, or keep as a draft and why.

## Sample POs

`samples/make_samples.py` (needs `pip install reportlab`) generates five POs with very different layouts, their
true values in `samples/truth/<slug>.json`, and `samples/customers.json` (which customers the CRM already knows).
The PDFs are committed, so you only need to re-run it if you change it.

| File | Customer | Layout | CRM |
|---|---|---|---|
| `edi-printout.pdf` | Bristow Wholesale Foods | EDI 850 translator printout, YYYYMMDD dates | known (matched by normalized name) |
| `corporate-form.pdf` | Northfield Market Co. | Designed corporate form, PO 88213 | new |
| `store-order.pdf` | Pinecrest Hardware & Home | Store-level order form, store #0417, handwritten note | known (matched by address) |
| `change-form.pdf` | Calloway Logistics Group | PO change notice: original vs revised qty and date | known (exact name) |
| `distributor-po.pdf` | Meridian Industrial Distributors | Distributor PO, 8 lines over 2 pages | new |

All SKUs and prices come from the demo ERP's item master (`erp/seed_data.py`), so the checks pass.

## Online demo

`render.yaml` and `app/hosted.py` put a password-protected, AI-free demo on Render, with a
GitHub job that keeps it awake. Steps: [DEPLOY.md](DEPLOY.md).

## Tests

```bash
python -m unittest discover -s tests
```

Covers routing, totals, SKU and price checks, customer matching, the send allowlist (including look-alike domains,
display-name tricks and header injection), the JSON validator, the read-only mailbox watcher, the ERP, extraction
retry behaviour, and the full pipeline for all 5 samples with a stubbed extractor. The pipeline test checks that
nothing reaches the ERP or CRM before Accept and that an edit made in review shows up in the posted ERP order.
No test calls an AI, a mail server or the network beyond 127.0.0.1.

To score the real extraction against the truth files and rewrite `EXTRACTION.md`:

```bash
python eval_extraction.py
```

## Connect a mailbox (optional)

The watcher is off by default and strictly read-only:

- The folder is opened read-only (`EXAMINE`), messages are fetched with `BODY.PEEK[]` so they are never marked
  read, and no command that moves, flags or deletes mail is ever issued (`tests/test_mailbox.py` enforces this).
- Handled Message-IDs are kept locally in `state/handled_messages.json`, so each email is processed once.
- Only messages from the last `IMAP_LOOKBACK_DAYS` days that have a PDF attached are picked up. The first PDF
  starts a run when the pipeline is idle (never while an order is waiting for review).

In `.env`:

```
MAILBOX_WATCH=on
IMAP_HOST=imap.example.com
IMAP_PORT=993
IMAP_USER=orders@example.com
IMAP_PASSWORD=your-app-password
IMAP_FOLDER=INBOX
```

Use an app password if your mail provider offers them (most require one for IMAP), and consider pointing it at a
dedicated folder or a test mailbox first. Restart `start.sh` after changing `.env`. The top bar shows the
watcher's state and the last error, if any.

## Sending email

- `SEND_MODE=dry` (default): nothing is sent. Send writes `confirmation_email.eml` (marked `dry-run, not sent`)
  into the customer folder.
- `SEND_MODE=live`: sends through `SMTP_HOST` **only** if every recipient is listed in `SEND_ALLOWED` (exact
  address, or `@domain` for a whole domain). Anything else stays a draft, and the button says why. Start with your
  own address in `SEND_ALLOWED`.

## Swapping in a real ERP and CRM

The demo systems sit behind two small seams. Replace these and leave the rest alone:

| Replace | With | Keep the interface |
|---|---|---|
| `app/erp_client.py` | A client for your ERP's API | `items()` → `{SKU: {sku, description, uom, list_price}}`, `search(q)`, `find_po(customer, po_number)`, `post_order(po)` → `{so_number, lines, total}`, `order_url(so)` |
| `app/crm.py` | A client for your CRM's API | `companies()` → `[{id, name, addresses: [{street, zip}]}]`, `company(id)`, `upsert_from_po(po, match, activity)` → `{company_id, summary}` |

Then:

- Rename the nodes (`TITLES` in `web/app.js`) to the real system names, and point the **Open in CRM** link
  (`link` in `app/pipeline.py: _branch`) at the real CRM's record URL. Keep the demo names until writes really go
  to the real systems.
- If your ERP prices by customer, give `items()` that customer's price list, or change `check_prices` in
  `app/checks.py`.
- Post in two steps if your ERP supports it (create as draft or held, then release), as the demo ERP does, so
  a failed release never leaves a half-entered order.
- `CUSTOMERS_DIR` can point at a shared drive.
- Delete `erp/` once nothing calls it.

## Layout

```
start.sh               one-command start, --reset
.env.example           every setting, explained
app/                   the pipeline app (port 7820)
  server.py            HTTP + SSE + JSON API
  pipeline.py          the state machine: arrive, read, review, fan-out, email
  extract.py           the AI step: Claude CLI or API, streaming status, validation, one retry
  validate.py          strict data-contract validator
  checks.py            totals, SKU, price, customer match, ship date, routing
  crm.py               demo CRM (SQLite)
  erp_client.py        talks to the ERP over HTTP
  sender.py            dry / live sending with the allowlist
  mailbox.py           read-only IMAP watcher
web/                   index.html, style.css, app.js (no build step)
erp/                   demo ERP (port 7811): item master, search, staged-then-approved orders, web UI
samples/               5 POs, truth JSON, customers.json, make_samples.py
tests/                 unittest suite
eval_extraction.py     scores real extraction against the truth files, writes EXTRACTION.md
```

Runtime data (`state/`, `erp/data/`, `customers/`) and `.env` are git-ignored.
