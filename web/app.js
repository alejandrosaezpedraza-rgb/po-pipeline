"use strict";
/* PO Intake UI. Plain JS, no build step. State is pushed by the server over SSE. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (x) => "$" + Number(x || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const round2 = (x) => Math.round((Number(x) + Number.EPSILON) * 100) / 100;
const clone = (o) => JSON.parse(JSON.stringify(o));

let snap = { run: null, log: [], mailbox: {} };
let cfg = null;
let emailRunId = null;

/* ------------------------------------------------------------------ api */
async function api(path, body, opts = {}) {
  const res = await fetch(path, {
    method: body === undefined && !opts.method ? "GET" : (opts.method || "POST"),
    headers: opts.headers || { "Content-Type": "application/json" },
    body: body === undefined ? undefined : (opts.raw ? body : JSON.stringify(body)),
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* not json */ }
  if (!res.ok) {
    const err = new Error((data && data.error) || `HTTP ${res.status}`);
    err.details = (data && data.details) || [];
    err.status = res.status;
    throw err;
  }
  return data;
}

function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (bad ? " bad" : "");
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), bad ? 6000 : 3200);
}

/* ------------------------------------------------------------------ live updates */
function connect() {
  const es = new EventSource("/events");
  es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.config) cfg = data.config;
    snap = data;
    render();
    if (route().name === "crm") loadCRM();
  };
  es.onerror = () => {
    renderBadges(true);
  };
}

/* ------------------------------------------------------------------ routing */
function route() {
  const h = location.hash || "#/";
  const m = h.match(/^#\/crm(?:\/(\d+))?/);
  return m ? { name: "crm", id: m[1] } : { name: "pipeline" };
}
function applyRoute() {
  const r = route();
  $("#view-pipeline").hidden = r.name !== "pipeline";
  $("#view-crm").hidden = r.name !== "crm";
  $$("nav a[data-route]").forEach((a) => a.classList.toggle("on", a.dataset.route === r.name));
  if (r.name === "crm") loadCRM();
  else requestAnimationFrame(drawWires);
}
window.addEventListener("hashchange", applyRoute);

/* ------------------------------------------------------------------ render */
function render() {
  renderBadges(false);
  renderNodes();
  renderLog();
  requestAnimationFrame(drawWires);
  const rv = snap.run && snap.run.nodes.review;
  if (!$("#sheet").hidden && (!rv || rv.status !== "waiting" || sheet.runId !== snap.run.id)) closeSheet();
}

function renderBadges(offline) {
  const el = $("#badges");
  if (!cfg) return;
  const b = [];
  const ex = cfg.extractor || {};
  b.push(`<span class="badge ${ex.ready ? "ok" : "bad"}" title="${esc(ex.hint || "")}">Extractor <b>${esc(ex.label)}</b>${ex.model ? " · " + esc(ex.model) : ""}</span>`);
  b.push(cfg.send_mode === "live"
    ? `<span class="badge warn">Send <b>live</b> · ${cfg.send_allowed.length} allowed</span>`
    : `<span class="badge">Send <b>dry run</b></span>`);
  const mb = snap.mailbox || {};
  if (mb.state && mb.state !== "off") {
    b.push(`<span class="badge ${mb.state === "error" ? "bad" : ""}" title="${esc(mb.error || mb.last_poll || "")}">Mailbox <b>${esc(mb.state)}</b></span>`);
  }
  if (!cfg.erp_up) b.push(`<span class="badge bad">ERP <b>offline</b></span>`);
  if (offline) b.push(`<span class="badge bad">Reconnecting…</span>`);
  el.innerHTML = b.join("");
  $("#erp-link").href = cfg.erp_url + "/";
}

const TITLES = {
  arrive: "PO arrives", read: "Claude reads the PO", review: "Review",
  erp: "ERP · Demo ERP", crm: "CRM · Demo CRM", folder: "Customer folder", email: "Confirmation email",
};
const NUMS = { arrive: "1", read: "2", review: "3", erp: "4", crm: "4", folder: "4", email: "5" };

function stateIcon(st) {
  if (st === "done") return `<span class="check" aria-label="done"></span>`;
  if (st === "running") return `<span class="spin" aria-label="running"></span>`;
  if (st === "error") return `<span class="xmark" aria-label="error">!</span>`;
  return `<span class="dot"></span>`;
}

function chipHTML(c, i = 0) {
  const icon = { ok: "✓", warn: "!", bad: "✕", info: "i" }[c.status] || "•";
  return `<span class="chip ${esc(c.status)}" style="animation-delay:${i * 60}ms" title="${esc(c.detail || "")}"><i>${icon}</i>${esc(c.label)}</span>`;
}

function setNode(key, status, inner) {
  const el = $("#n-" + key);
  const prev = el.dataset.status;
  const html = `<div class="head"><span class="num">${NUMS[key]}</span><span class="title">${TITLES[key]}</span><span class="state">${stateIcon(status === "waiting" ? "idle" : status)}</span></div>${inner}`;
  if (prev === status && el._html === html) return;  // unchanged: keep DOM (and animations) as they are
  el.dataset.status = status;
  if (prev && prev !== status && status === "done") {
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
  }
  el._html = html;
  el.innerHTML = html;
}

function renderNodes() {
  const run = snap.run;
  const N = run ? run.nodes : {};
  const st = (k) => (N[k] ? N[k].status : "idle");

  // 1 arrive
  if (!run) {
    const mb = snap.mailbox || {};
    const replay = cfg && cfg.extractor && cfg.extractor.kind === "replay";
    const intro = replay
      ? `<div class="detail">This demo plays back the 5 sample POs without AI. Choose one from <strong>Try a sample</strong>.</div>`
      : `<div class="detail">Drop a PO PDF anywhere on this page.</div>
      <div class="drop-zone">PDF · drag &amp; drop</div>`;
    setNode("arrive", "idle", intro +
      (mb.state && mb.state !== "off" ? `<div class="detail">Also watching the mailbox (read-only).</div>` : ""));
  } else {
    setNode("arrive", "done", `<div class="detail"><strong>${esc(N.arrive.detail)}</strong></div>
      ${run.email ? `<div class="detail">From ${esc(run.email.from)}</div>` : ""}`);
  }

  // 2 read
  const r = N.read || { status: "idle" };
  let readInner = "";
  if (r.status === "idle") readInner = `<div class="detail">Waiting for a PO.</div>`;
  else {
    const lines = (r.lines || []).slice(-7).map((l) => `<li>${esc(l.text)}</li>`).join("");
    if (r.status === "running") readInner = `<ul class="status-lines">${lines || "<li>Starting</li>"}</ul>`;
    if (r.status === "done") readInner = `<div class="detail"><strong>${esc(r.detail)}</strong></div><div class="chips">${(r.chips || []).map(chipHTML).join("")}</div>`;
    if (r.status === "error") readInner = `<div class="err">${esc(r.error)}</div><ul class="status-lines">${lines}</ul><div class="row"><button data-act="retry-read">Try again</button><button data-act="reset">Reset</button></div>`;
  }
  setNode("read", r.status, readInner);

  // 3 review
  const rv = N.review || { status: "idle" };
  let rvInner = `<div class="detail">Opens when Claude is done.</div>`;
  if (rv.status === "waiting") {
    const why = rv.level === "clean" ? "All checks passed." : (rv.reasons || []).join(" · ");
    rvInner = `<span class="review-badge">Needs your review</span><div class="detail">${esc(why)}</div>
      <div class="row"><button class="primary" data-act="open-review">Open review</button></div>`;
  } else if (rv.status === "done") rvInner = `<div class="detail"><strong>${esc(rv.detail)}</strong></div>`;
  setNode("review", rv.status, rvInner);
  $("#n-review").classList.toggle("clickable", rv.status === "waiting");

  // 4 branches
  const verbs = { erp: "Posting the order", crm: "Writing company and contact", folder: "Saving files" };
  for (const k of ["erp", "crm", "folder"]) {
    const n = N[k] || { status: "idle" };
    let inner = `<div class="detail">Runs after Accept.</div>`;
    if (n.status === "running") inner = `<div class="detail">${verbs[k]}…</div>`;
    if (n.status === "error") inner = `<div class="err">${esc(n.error)}</div><div class="row"><button data-act="retry" data-branch="${k}">Retry</button></div>`;
    if (n.status === "done") {
      const btn = k === "erp" ? `<a class="btn" href="${esc(n.link)}" target="_blank" rel="noopener">Open in ERP ↗</a>`
        : k === "crm" ? `<a class="btn" href="${esc(n.link)}">Open in CRM</a>`
        : cfg && cfg.hosted ? `<a class="btn" href="/folder" target="_blank" rel="noopener">Open folder ↗</a>`
        : `<button data-act="open-folder">Open folder</button>`;
      inner = `<div class="detail"><strong>${esc(n.detail)}</strong></div><div class="row">${btn}</div>`;
    }
    setNode(k, n.status, inner);
  }

  // 5 email
  const em = N.email || { status: "idle" };
  const el = $("#n-email");
  if (em.status === "waiting") {
    if (emailRunId !== run.id || el.dataset.status !== "waiting") {
      emailRunId = run.id;
      const d = em.draft;
      setNode("email", "waiting", `<div class="detail">Draft to the customer. Edit, then send.</div>
        <div class="mail">
          <label>To<input id="m-to" value="${esc(d.to)}"></label>
          <label>Subject<input id="m-subject" value="${esc(d.subject)}"></label>
          <label>Body<textarea id="m-body" rows="9">${esc(d.body)}</textarea></label>
          <div class="gate" id="m-gate"></div>
          <div class="row"><button class="primary" id="m-send" data-act="send"></button></div>
        </div>`);
      $("#m-to").addEventListener("input", debounce(updateGate, 250));
      showGate(em.gate);
    }
  } else {
    emailRunId = null;
    let inner = `<div class="detail">Drafted once the order is in the ERP, CRM and folder.</div>`;
    if (em.status === "done") {
      inner = `<div class="detail"><strong>${esc(em.detail)}</strong></div>
        <div class="detail">To ${esc(em.draft.to)} · “${esc(em.draft.subject)}”</div>`;
    }
    setNode("email", em.status, inner);
  }
  el.classList.toggle("warn", em.status === "done" && !!em.warn);
}

function showGate(g) {
  const btn = $("#m-send");
  if (!btn || !g) return;
  btn.textContent = g.action === "send" ? "Send" : g.action === "save" ? "Save email (dry run)" : "Save as draft";
  const gate = $("#m-gate");
  gate.className = "gate" + (g.action === "draft" ? " warn" : "");
  gate.textContent = g.action === "send" ? g.label : g.action === "save" ? "SEND_MODE=dry: the email is saved to the customer folder, not sent."
    : `Won't send: ${g.reason}. It will be kept as a draft.`;
}

async function updateGate() {
  try { showGate(await api("/api/email/gate", { to: $("#m-to").value })); } catch (_) { /* ignore */ }
}

function renderLog() {
  const items = snap.log || [];
  $("#log-count").textContent = items.length ? `${items.length} entr${items.length === 1 ? "y" : "ies"}` : "";
  $("#log").innerHTML = items.length
    ? items.map((l) => `<li class="${esc(l.level)}"><time>${esc(l.t.slice(11))}</time><span>${esc(l.msg)}</span></li>`).join("")
    : `<li class="empty">Nothing yet. Drop a PO or pick a sample to start.</li>`;
  const ol = $("#log");
  ol.scrollTop = ol.scrollHeight;
}

/* ------------------------------------------------------------------ wires */
const EDGES = [["arrive", "read"], ["read", "review"], ["review", "erp"], ["review", "crm"], ["review", "folder"],
  ["erp", "email"], ["crm", "email"], ["folder", "email"]];

function drawWires() {
  const svg = $("#wires");
  const canvas = $("#canvas");
  if (!svg || $("#view-pipeline").hidden || getComputedStyle(svg).display === "none") return;
  const cr = canvas.getBoundingClientRect();
  const N = snap.run ? snap.run.nodes : {};
  const st = (k) => (N[k] ? N[k].status : "idle");
  svg.setAttribute("viewBox", `0 0 ${cr.width} ${cr.height}`);
  svg.innerHTML = EDGES.map(([a, b]) => {
    const ra = $("#n-" + a).getBoundingClientRect();
    const rb = $("#n-" + b).getBoundingClientRect();
    const x1 = ra.right - cr.left, y1 = ra.top + ra.height / 2 - cr.top;
    const x2 = rb.left - cr.left, y2 = rb.top + rb.height / 2 - cr.top;
    const dx = Math.max(24, (x2 - x1) / 2);
    let cls = "";
    if (st(a) === "done" && (st(b) === "done" || st(b) === "waiting")) cls = "done";
    else if (st(a) === "done" && st(b) === "running") cls = "live";
    else if (st(a) === "done" && b === "review" && st(b) === "waiting") cls = "done";
    return `<path class="${cls}" d="M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}"/>`;
  }).join("");
}
window.addEventListener("resize", () => requestAnimationFrame(drawWires));

/* ------------------------------------------------------------------ actions */
document.addEventListener("click", async (e) => {
  const t = e.target.closest("[data-act]");
  if (!t) {
    if (e.target.closest("#n-review.clickable")) openSheet();
    return;
  }
  const act = t.dataset.act;
  try {
    if (act === "open-review") openSheet();
    if (act === "retry") await api("/api/retry/" + t.dataset.branch, {});
    if (act === "retry-read") await api("/api/retry-read", {});
    if (act === "open-folder") { const r = await api("/api/open-folder", {}); toast("Opened " + r.opened); }
    if (act === "reset") await doReset();
    if (act === "send") {
      t.disabled = true;
      const draft = { to: $("#m-to").value, subject: $("#m-subject").value, body: $("#m-body").value };
      const r = await api("/api/email/send", { draft });
      toast(r.sent ? `Sent to ${draft.to}` : r.action === "save" ? "Saved to the customer folder (dry run, not sent)" : `Kept as draft: ${r.reason}`, !r.ok);
    }
    if (act === "sample") { $("#samples-menu").hidden = true; await startFile(t.dataset.name, null); }
  } catch (err) {
    toast(err.message, true);
    t.disabled = false;
  }
});

async function doReset() {
  if (snap.run && !confirm("Clear this run and the log? Orders already posted stay in the ERP and CRM.")) return;
  await api("/api/reset", {});
  closeSheet();
}
$("#reset-btn").addEventListener("click", () => doReset().catch((e) => toast(e.message, true)));

function runInProgress() {
  const r = snap.run;
  if (!r) return false;
  return r.nodes.email.status !== "done" && r.nodes.read.status !== "error";
}

async function startFile(sampleName, file) {
  if (runInProgress() && !confirm("Start a new run? The current run will be cleared from this view.")) return;
  closeSheet();
  if (file) {
    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") return toast("That's not a PDF", true);
    await api("/api/upload", file, { raw: true, headers: { "X-Filename": encodeURIComponent(file.name), "Content-Type": "application/pdf" } });
  } else {
    await api("/api/sample/" + encodeURIComponent(sampleName), {});
  }
}

$("#file-input").addEventListener("change", (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (f) startFile(null, f).catch((err) => toast(err.message, true));
});

$("#samples-btn").addEventListener("click", async (e) => {
  e.stopPropagation();
  const m = $("#samples-menu");
  if (!m.hidden) { m.hidden = true; return; }
  const names = await api("/api/samples");
  m.innerHTML = names.map((n) => `<button data-act="sample" data-name="${esc(n)}">${esc(n)}</button>`).join("") || `<div class="dim">No samples</div>`;
  m.hidden = false;
});
document.addEventListener("click", (e) => { if (!e.target.closest(".samples")) $("#samples-menu").hidden = true; });

/* drag and drop anywhere */
let dragDepth = 0;
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
window.addEventListener("dragenter", (e) => { if (!hasFiles(e)) return; e.preventDefault(); dragDepth++; $("#drop").hidden = false; });
window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener("dragleave", (e) => { if (!hasFiles(e)) return; if (--dragDepth <= 0) { dragDepth = 0; $("#drop").hidden = true; } });
window.addEventListener("drop", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth = 0;
  $("#drop").hidden = true;
  const f = e.dataTransfer.files[0];
  if (f) startFile(null, f).catch((err) => toast(err.message, true));
});

/* ------------------------------------------------------------------ review sheet */
const sheet = { runId: null, po: null, orig: null, check: null };

function openSheet() {
  const run = snap.run;
  if (!run || run.nodes.review.status !== "waiting") return;
  if (sheet.runId !== run.id) {
    sheet.runId = run.id;
    sheet.po = clone(run.extracted);
    sheet.orig = clone(run.extracted);
    sheet.check = run.checks;
  }
  $("#sheet-title").textContent = `Review PO ${sheet.po.po_number || ""}`;
  $("#sheet-sub").textContent = `${run.pdf} · read by ${cfg?.extractor?.label || "Claude"}`;
  const fr = $("#pdf-frame");
  const src = `/api/pdf?run=${encodeURIComponent(run.id)}#navpanes=0&view=FitH`;
  if (fr.dataset.src !== src) { fr.src = src; fr.dataset.src = src; }
  buildForm();
  applyCheck(sheet.check);
  $("#sheet").hidden = false;
  recheck();
}

function closeSheet() { $("#sheet").hidden = true; $("#sheet-msg").textContent = ""; }
$("#sheet-close").addEventListener("click", closeSheet);
$("#sheet-cancel").addEventListener("click", closeSheet);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#sheet").hidden) closeSheet(); });

function getPath(o, path) { return path.split(".").reduce((a, k) => (a == null ? a : a[k]), o); }
function setPath(o, path, v) {
  const ks = path.split(".");
  const last = ks.pop();
  const tgt = ks.reduce((a, k) => a[k], o);
  tgt[last] = v;
}

const NUMERIC = new Set(["qty", "unit_price", "extended", "subtotal", "freight", "tax", "total"]);
const isNum = (path) => NUMERIC.has(path.split(".").pop());

function inp(path, opts = {}) {
  const v = getPath(sheet.po, path);
  const num = isNum(path);
  const shown = num ? (path.endsWith("qty") ? String(v ?? "") : Number(v ?? 0).toFixed(2)) : (v ?? "");
  return `<input data-k="${path}" class="${num ? "num" : ""}" value="${esc(shown)}" ${opts.ph ? `placeholder="${esc(opts.ph)}"` : ""} ${num ? 'inputmode="decimal"' : ""}>`;
}
const field = (label, path, cls = "") => `<label class="f ${cls}"><span>${label}</span>${inp(path)}</label>`;
const party = (key, withStore) => `
  ${field("Name", key + ".name", "s2")}${field("Street", key + ".street", "s2")}
  ${field("City", key + ".city", "s2")}${field("State", key + ".state")}${field("ZIP", key + ".zip")}
  ${withStore ? field("Store / location #", key + ".store_number", "s2") : ""}`;

function buildForm() {
  const f = $("#review-form");
  f.innerHTML = `
  <section>
    <h3>Going to the CRM <span class="to">· Demo CRM</span></h3>
    <div class="grid">
      ${field("Company", "buyer.company", "s2")}${field("Payment terms", "payment_terms", "s2")}
      ${field("Buyer name", "buyer.contact_name", "s2")}${field("Phone", "buyer.phone", "s2")}
      ${field("Email", "buyer.email", "s4")}
    </div>
    <div class="subhead">Bill to</div><div class="grid">${party("bill_to", false)}</div>
    <div class="subhead">Ship to</div><div class="grid">${party("ship_to", true)}</div>
  </section>
  <section>
    <h3>Going to the ERP <span class="to">· Demo ERP</span></h3>
    <div class="grid">
      ${field("PO number", "po_number")}${field("PO date", "po_date")}${field("Requested ship date", "requested_ship_date")}${field("Currency", "currency")}
    </div>
    <div class="subhead">Lines</div>
    <table class="lines"><thead><tr><th style="width:24px">#</th><th style="width:96px">SKU</th><th style="width:88px">Cust. item</th><th>Description</th>
      <th class="n" style="width:54px">Qty</th><th style="width:50px">UOM</th><th class="n" style="width:90px">Unit price</th><th class="n" style="width:98px">Extended</th><th style="width:28px"></th></tr></thead>
      <tbody id="line-body"></tbody></table>
    <button type="button" class="ghost add-line" id="add-line">+ Add line</button>
    <div class="totals">
      <span>Subtotal</span>${inp("subtotal")}
      <span>Freight</span>${inp("freight")}
      <span>Tax</span>${inp("tax")}
      <span class="grand">Total</span>${inp("total").replace('class="num"', 'class="num grand"')}
    </div>
    <div class="subhead">Notes</div>
    <label class="f"><textarea data-k="notes" rows="2">${esc(sheet.po.notes)}</textarea></label>
  </section>
  <section>
    <h3>Going to the customer folder</h3>
    <div class="path" id="plan-path"></div>
    <ul class="files" id="plan-files"></ul>
  </section>`;
  renderLines();
  $("#add-line").addEventListener("click", () => {
    sheet.po.lines.push({ line: sheet.po.lines.length + 1, sku: "", customer_item: "", description: "", qty: 1, uom: "EA", unit_price: 0, extended: 0 });
    renderLines();
    recompute();
    $(`#line-body tr.line-row:last-of-type input[data-k$=".sku"]`)?.focus();
  });
  markChanged();
}

function renderLines() {
  $("#line-body").innerHTML = sheet.po.lines.map((l, i) => `
    <tr class="line-row" data-i="${i}">
      <td class="dim" style="padding-top:9px">${i + 1}</td>
      <td>${inp(`lines.${i}.sku`)}</td><td>${inp(`lines.${i}.customer_item`)}</td><td>${inp(`lines.${i}.description`)}</td>
      <td>${inp(`lines.${i}.qty`)}</td><td>${inp(`lines.${i}.uom`)}</td><td>${inp(`lines.${i}.unit_price`)}</td><td>${inp(`lines.${i}.extended`)}</td>
      <td><button type="button" class="rm" data-rm="${i}" title="Remove line" aria-label="Remove line ${i + 1}">✕</button></td>
    </tr>
    <tr class="hint-row"><td></td><td colspan="8"><div class="hint" id="hint-${i}"></div></td></tr>`).join("");
  if (sheet.check) applyLineHints(sheet.check);
}

function renumber() { sheet.po.lines.forEach((l, i) => (l.line = i + 1)); }

function recompute(source) {
  const po = sheet.po;
  if (source !== "extended") po.lines.forEach((l) => (l.extended = round2((Number(l.qty) || 0) * (Number(l.unit_price) || 0))));
  if (source !== "subtotal") po.subtotal = round2(po.lines.reduce((a, l) => a + (Number(l.extended) || 0), 0));
  if (source !== "total") po.total = round2((Number(po.subtotal) || 0) + (Number(po.freight) || 0) + (Number(po.tax) || 0));
  // reflect computed values without disturbing the field being typed in
  $$("#review-form input[data-k]").forEach((el) => {
    const k = el.dataset.k;
    if (el === document.activeElement || !/(extended|subtotal|total)$/.test(k)) return;
    el.value = Number(getPath(po, k) || 0).toFixed(2);
  });
  markChanged();
  recheckSoon();
}

function markChanged() {
  $$("#review-form [data-k]").forEach((el) => {
    const a = getPath(sheet.po, el.dataset.k), b = getPath(sheet.orig, el.dataset.k);
    const diff = isNum(el.dataset.k) ? Math.abs((Number(a) || 0) - (Number(b) || 0)) > 0.0001 || b === undefined : String(a ?? "") !== String(b ?? "");
    el.classList.toggle("changed", diff);
  });
}

$("#review-form").addEventListener("input", (e) => {
  const k = e.target.dataset.k;
  if (!k) return;
  let v = e.target.value;
  if (isNum(k)) {
    const n = parseFloat(String(v).replace(/[$,\s]/g, ""));
    v = Number.isFinite(n) ? n : 0;
  }
  setPath(sheet.po, k, v);
  const leaf = k.split(".").pop();
  recompute(["extended", "subtotal", "total"].includes(leaf) ? leaf : undefined);
});
$("#review-form").addEventListener("focusout", (e) => {
  const k = e.target.dataset?.k;
  if (k && isNum(k) && !k.endsWith("qty")) e.target.value = Number(getPath(sheet.po, k) || 0).toFixed(2);
});
$("#review-form").addEventListener("click", (e) => {
  const rm = e.target.closest("[data-rm]");
  if (rm) {
    sheet.po.lines.splice(Number(rm.dataset.rm), 1);
    renumber();
    renderLines();
    recompute();
    return;
  }
  const fix = e.target.closest("[data-fix]");
  if (fix) {
    const i = Number(fix.dataset.i);
    const l = sheet.po.lines[i];
    if (fix.dataset.fix === "sku") { l.sku = fix.dataset.sku; if (!l.description) l.description = fix.dataset.desc; }
    if (fix.dataset.fix === "price") l.unit_price = Number(fix.dataset.price);
    renderLines();
    recompute();
  }
});

const recheckSoon = debounce(recheck, 300);
async function recheck() {
  const runId = sheet.runId;
  try {
    const r = await api("/api/recheck", { po: sheet.po });
    if (runId === sheet.runId) { sheet.check = r; applyCheck(r); }
  } catch (e) { $("#sheet-msg").textContent = e.message; }
}

function applyCheck(c) {
  if (!c) return;
  $("#sheet-chips").innerHTML = (c.chips || []).map(chipHTML).join("");
  const errs = c.errors || [];
  const blocking = (c.blocking || []).concat(errs);
  $("#sheet-accept").disabled = blocking.length > 0;
  $("#sheet-msg").textContent = blocking.length ? "To accept, fix: " + blocking.slice(0, 3).join("; ") : "";
  if (c.plan) {
    $("#plan-path").textContent = c.plan.path + "/";
    $("#plan-files").innerHTML = c.plan.files.map((f) => `<li>${esc(f)}</li>`).join("");
  }
  applyLineHints(c);
}

function applyLineHints(c) {
  (c.lines || []).forEach((info, i) => {
    const h = $("#hint-" + i);
    if (!h) return;
    const parts = [];
    const l = sheet.po.lines[i];
    if (!info.sku_known) {
      const s = (info.suggestions || [])[0];
      parts.push(`SKU not in item master${s ? ` <button type="button" data-fix="sku" data-i="${i}" data-sku="${esc(s.sku)}" data-desc="${esc(s.description)}">Use ${esc(s.sku)}</button> <span class="dim">${esc(s.description)}</span>` : ""}`);
    } else if (info.list_price != null && l && Math.abs(Number(l.unit_price) - info.list_price) > 0.005) {
      parts.push(`Price list ${money(info.list_price)} <button type="button" data-fix="price" data-i="${i}" data-price="${info.list_price}">Use list price</button>`);
    }
    h.innerHTML = parts.join(" · ");
    h.className = "hint" + (!info.sku_known ? " bad" : "");
    const row = h.closest("tr");
    if (row) row.style.display = parts.length ? "" : "none";
    const skuIn = $(`input[data-k="lines.${i}.sku"]`);
    if (skuIn) skuIn.classList.toggle("bad", !info.sku_known);
    const priceIn = $(`input[data-k="lines.${i}.unit_price"]`);
    if (priceIn) priceIn.classList.toggle("flag", info.sku_known && l && Math.abs(Number(l.unit_price) - info.list_price) > 0.005);
  });
}

$("#sheet-accept").addEventListener("click", async () => {
  const btn = $("#sheet-accept");
  btn.disabled = true;
  try {
    await api("/api/accept", { po: sheet.po });
    closeSheet();
    sheet.runId = null;
  } catch (e) {
    $("#sheet-msg").textContent = e.message + (e.details.length ? ": " + e.details.slice(0, 4).join("; ") : "");
    btn.disabled = false;
  }
});

/* ------------------------------------------------------------------ CRM page */
async function loadCRM() {
  const r = route();
  let list;
  try { list = await api("/api/crm"); } catch (e) { return toast(e.message, true); }
  const sel = r.id ? Number(r.id) : (list[0] && list[0].id);
  $("#crm-list").innerHTML = list.map((c) => `<li><a href="#/crm/${c.id}" class="${c.id === sel ? "on" : ""}">${esc(c.name)}
    ${c.source === "po-pipeline" ? '<span class="tag new">from PO</span>' : ""}<small>${c.contacts.length} contact${c.contacts.length === 1 ? "" : "s"} · ${esc(c.payment_terms || "no terms")}</small></a></li>`).join("")
    || `<li class="dim" style="padding:8px">No companies.</li>`;
  const c = list.find((x) => x.id === sel);
  if (!c) { $("#crm-detail").innerHTML = ""; return; }
  const addr = (a) => a && (a.street || a.name) ? [a.name, a.street, [a.city, a.state, a.zip].filter(Boolean).join(" "), a.store_number ? "Store " + a.store_number : ""].filter(Boolean).map(esc).join("<br>") : '<span class="dim">none</span>';
  $("#crm-detail").innerHTML = `<div class="crm-card">
    <h1>${esc(c.name)}</h1>
    <div class="meta">Company #${c.id} · source ${esc(c.source)} · created ${esc(c.created_at)} · updated ${esc(c.updated_at)}</div>
    <div class="cgrid">
      <div class="cbox"><div>Payment terms</div>${esc(c.payment_terms || "none")}</div>
      <div class="cbox"><div>Bill to</div>${addr(c.bill_to)}</div>
      <div class="cbox"><div>Last ship to</div>${addr(c.ship_to)}</div>
      <div class="cbox"><div>Known addresses (${c.addresses.length})</div>${c.addresses.map((a) => esc([a.street, a.city, a.state].filter(Boolean).join(", "))).join("<br>") || '<span class="dim">none</span>'}</div>
    </div>
    <h2>Contacts</h2>
    <table><tr><th>Name</th><th>Email</th><th>Phone</th><th>Updated</th></tr>
      ${c.contacts.map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.email)}</td><td>${esc(p.phone)}</td><td class="dim">${esc(p.updated_at)}</td></tr>`).join("") || '<tr><td colspan="4" class="dim">None</td></tr>'}
    </table>
    <h2 style="margin-top:20px">Activity</h2>
    <table><tr><th>When</th><th>What</th></tr>
      ${c.activities.map((a) => `<tr><td class="dim">${esc(a.at)}</td><td>${esc(a.text)}</td></tr>`).join("") || '<tr><td colspan="2" class="dim">None</td></tr>'}
    </table></div>`;
}

/* ------------------------------------------------------------------ util + boot */
function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

applyRoute();
connect();
