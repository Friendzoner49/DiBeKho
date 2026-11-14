/* DiBeKho web: the windows and detail pages -- the information the app's own windows show, computed from the shared
   tables loaded by app.js (data, productById, customerById, linesByDoc, ...) -- and the statistics screen.
   Statistics come from stats.js, which tests/test_web_stats.py keeps identical to the app's core/stats.py.
   Nothing here writes the shop's data. */

"use strict";

/* ---------------------------------------------------------------- the dialog window */

const dlg = $("dlg");

/** Open the window. buttons: [{label, primary?, run: async () => close?}]; a run that throws shows its message.
    asks: a question asked before closing while something is typed in (a form), or null. */
function openDialog(title, html, buttons, closeLabel = null, asks = null) {
  $("dlg-title").textContent = title;
  $("dlg-body").innerHTML = html;
  $("dlg-error").textContent = "";
  const bar = $("dlg-buttons");
  bar.innerHTML = "";
  dlgAsks = asks;
  dlg.classList.remove("narrow");  // a small window (the converter) asks for it after opening
  for (const b of [...buttons, { label: closeLabel || tr(buttons.length ? "btn.cancel" : "btn.close"), close: true, run: async () => true }]) {
    const el = document.createElement("button");
    el.textContent = b.label;
    if (b.primary) el.className = "primary-btn";
    el.addEventListener("click", async () => {
      $("dlg-error").textContent = "";
      bar.querySelectorAll("button").forEach((x) => { x.disabled = true; });
      try {
        if (b.close) closeDialog();
        else if (await b.run()) dlg.close();
      } catch (e) {
        $("dlg-error").textContent = e.message || String(e);
      } finally {
        bar.querySelectorAll("button").forEach((x) => { x.disabled = false; });
      }
    });
    bar.append(el);
  }
  if (!dlg.open) dlg.showModal();
  return $("dlg-body");
}

let dlgAsks = null;  // {dirty: () => bool, question: text} of the form in the window, like the app's confirm_close

function closeDialog() {
  if (dlgAsks && dlgAsks.dirty() && !confirm(dlgAsks.question)) return false;
  dlg.close();
  return true;
}

$("dlg-x").addEventListener("click", closeDialog);
dlg.addEventListener("cancel", (e) => { e.preventDefault(); closeDialog(); });  // the Esc key

function fail(message) { throw new Error(message); }

/** A button outside a dialog: show what went wrong in a message box, like the app. */
async function ownerAction(work) {
  try {
    await work();
  } catch (e) {
    alert(e.message || String(e));
  }
}

/* ---------------------------------------------------------------- helpers */

function plainTable(headers, bodyRows, numericFrom) {
  const head = headers.map((h, i) => `<th class="${numericFrom !== undefined && i >= numericFrom ? "num" : ""}">${esc(h)}</th>`).join("");
  return `<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${bodyRows.join("")}</tbody></table></div>`;
}

/** A file handed to the browser's downloads. */
function saveFile(name, bytes, type = "application/octet-stream") {
  const url = URL.createObjectURL(new Blob([bytes], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 2000);
}

/** A CSV the Excel on a Vietnamese Windows opens correctly: UTF-8 with a BOM, CRLF, ',' between cells. */
function csvDownload(filename, headers, rows) {
  const cell = (v) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  saveFile(filename, String.fromCharCode(0xfeff) + [headers, ...rows].map((r) => r.map(cell).join(",")).join("\r\n"), "text/csv;charset=utf-8");
}

function csvButton(container, filename, headers, rows) {
  const btn = document.createElement("button");
  btn.className = "flat"; btn.textContent = tr("btn.csv");
  btn.addEventListener("click", () => csvDownload(filename, headers, rows));
  container.append(btn);
}

function backBar(title) {
  return `<div class="backbar"><button class="back" id="detail-back">${esc(tr("back.back"))}</button><h1>${esc(title)}</h1></div>`;
}

function openDetail(html) {
  const back = backTo;
  const box = $("page-detail");
  box.innerHTML = html;
  showPage("detail");
  $("detail-back").addEventListener("click", () => showPage(back));
  return box;
}

const moveName = (k) => tr(`move.${k}`);

/* ---------------------------------------------------------------- order detail (the app's Chi tiết đơn window) */

/** The places a document's stock moved at: one, or both for a Phiếu xuất kho that took from Kho tổng and Văn phòng. */
function docPlaces(d) {
  const places = new Set();
  for (const m of data.movements) if (m.document_id === d.id && m.location_id) places.add(m.location_id);
  return [...places].sort();
}

function placeOf(d) {
  if (d.kind === "transfer") return `${placeName(d.location_id) || "?"} → ${placeName(d.to_location_id) || "?"}`;
  if (d.kind === "delivery" || d.kind === "receipt" || d.kind === "trial") {
    const both = d.kind === "delivery" && docPlaces(d).length > 1;
    const name = both ? tr("place.both") : placeName(d.location_id) || tr("place.1");
    return d.kind === "delivery" && d.location_set === false ? tr("place.unset", { place: name }) : name;
  }
  return "";
}

function orderDetailHtml(d) {
  const c = customerById[d.customer_id];
  const lines = (linesByDoc[d.id] || []).slice().sort((a, b) => a.line_no - b.line_no);
  const perLine = d.kind === "delivery" && docPlaces(d).length > 1;
  const info = [
    [tr("col.kind"), kindName(d.kind)], [tr("col.code"), d.code], [tr("col.date"), d.doc_date],
    [tr("col.status"), tr(`status.${d.status}_long`)],
    ...(c ? [[tr("col.customer"), [c.name, c.contact, c.phone, c.address].filter(Boolean).join(" · ")]] : []),
    ...(d.kind === "receipt" ? [[tr("col.source"), d.supplier_name || (d.receipt_source === "return" ? tr("source.return") : "")],
                                [tr("detail.ref_code"), d.ref_code]] : []),
    [d.kind === "receipt" ? tr("col.into") : d.kind === "transfer" ? tr("detail.transfer") : tr("detail.taken_from"), placeOf(d)],
    [tr("col.note"), d.note],
    ...(d.fee_amount ? [[tr("detail.fees"), fmtMoney(d.fee_amount)]] : []),
    ...(d.note_total !== null && d.note_total !== undefined ? [[tr("detail.note_total"), fmtMoney(d.note_total)]] : []),
    ...(d.source_file ? [[tr("detail.file"), d.source_file]] : []),
  ].filter(([, v]) => v !== "" && v !== null && v !== undefined);
  const rows = lines.map((l) => {
    const p = productById[l.product_id] || {};
    return `<tr><td>${esc(p.code || "?")}</td><td>${esc(pn(p))} ${esc(pnOther(p))}</td>` +
           `<td>${esc(p.spec || "")}</td>${perLine ? `<td>${esc(placeName(l.location_id))}</td>` : ""}<td class="num">${fmtQty(l.qty)}</td>` +
           `<td class="num">${fmtMoney(l.unit_price)}</td><td class="num">${fmtMoney(l.amount)}</td>` +
           `<td>${esc(l.note)}</td></tr>`;
  });
  const head = [tr("col.code"), tr("col.product"), tr("col.spec"), ...(perLine ? [tr("col.place")] : []), tr("col.qty_short"),
                tr("col.unit_price"), tr("col.amount"), tr("col.note")];
  return `<dl class="info">${info.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>` +
    plainTable(head, rows, perLine ? 4 : 3);
}

function showOrder(id) {
  const d = docById[id];
  if (!d) return;
  openDialog(`${kindName(d.kind)} ${d.code || ""}`.trim(), orderDetailHtml(d), []);
}

/** Phiếu chuyển hàng… / Phiếu dùng thử… / Phiếu kiểm kê… (the app's lists inside Kiểm kê). */
function docListWindow(kind) {
  const items = data.documents.filter((d) => d.kind === kind)
    .sort((a, b) => b.doc_date.localeCompare(a.doc_date) || String(b.created_at).localeCompare(String(a.created_at)));
  openDialog(tr(`doclist.${kind}`), `<p class="hint">${esc(tr("doclist.hint"))}</p><div id="dl-table"></div>`, []);
  buildTable("dl-table", [
    { label: tr("col.date"), get: (d) => d.doc_date }, { label: tr("col.code"), get: (d) => d.code },
    { label: tr("col.place"), get: placeOf },
    { label: tr("col.product"), get: (d) => (linesByDoc[d.id] || []).map((l) => `${(productById[l.product_id] || {}).code || "?"}×${fmtQty(l.qty)}`).join(", ") },
    { label: tr("col.status"), get: (d) => statusName(d.status) }, { label: tr("col.note"), get: (d) => d.note },
  ], items, { select: "one", open: (d) => showOrder(d.id), rowClass: (d) => (d.status !== "active" ? "closed" : ""), empty: tr("doclist.none") });
}

for (const b of document.querySelectorAll("[data-doclist]")) b.addEventListener("click", () => docListWindow(b.dataset.doclist));

/* ---------------------------------------------------------------- product detail */

function productHistory(id) {
  const docs = new Map(data.documents.map((d) => [d.id, d]));
  const moves = data.movements.filter((m) => m.product_id === id)
    .sort((a, b) => a.occurred_on.localeCompare(b.occurred_on) || String(a.created_at).localeCompare(String(b.created_at)));
  let balance = 0;
  return moves.map((m) => {
    balance += m.qty;
    const d = docs.get(m.document_id) || {};
    const who = d.kind === "receipt" ? (d.supplier_name || (customerById[d.customer_id] || {}).name || "")
                                     : (customerById[d.customer_id] || {}).name || "";
    return { ...m, balance, code: d.code || "", who, status: d.status };
  });
}

function showProduct(id) {
  const p = productById[id];
  if (!p) return;
  const st = stockByProduct[id] || { total: 0, 1: 0, 2: 0 };
  const history = productHistory(id);
  const top = topCustomersOfProduct(id);
  const box = openDetail(
    backBar(`${p.code} · ${productName(p)}`) +
    `<dl class="info"><dt>${esc(tr("col.other_name"))}</dt><dd>${esc(pnOther(p))}</dd><dt>${esc(tr("col.category"))}</dt><dd>${esc(p.category)}</dd>` +
    `<dt>${esc(tr("col.unit"))}</dt><dd>${esc(p.unit)}</dd><dt>${esc(tr("col.stock_note"))}</dt><dd>${esc(p.stock_note)}</dd></dl>` +
    `<div class="cards"><div class="stat"><span>${esc(tr("col.stock"))}</span><b>${fmtQty(st.total)}</b></div>` +
    `<div class="stat"><span>${esc(tr("place.1"))}</span><b>${fmtQty(st[1])}</b></div>` +
    `<div class="stat"><span>${esc(tr("place.2"))}</span><b>${fmtQty(st[2])}</b></div></div>` +
    `<h3>${esc(tr("product.history"))}</h3><div id="ph-table"></div>` +
    `<h3>${esc(tr("product.top_customers"))}</h3><div id="ph-top"></div>`);
  const newest = history.slice().reverse();
  const headers = [tr("col.date"), tr("col.kind"), tr("col.doc_code"), tr("col.who"), tr("col.place"), tr("col.qty"), tr("col.balance")];
  $("ph-table").innerHTML = plainTable([...headers, tr("col.doc_status")],
    newest.map((m) => `<tr class="${m.status && m.status !== "active" ? "closed" : ""}"><td>${esc(m.occurred_on)}</td>` +
      `<td>${esc(moveName(m.kind))}</td><td>${esc(m.code)}</td><td>${esc(m.who)}</td>` +
      `<td>${esc(placeName(m.location_id))}</td><td class="num">${m.qty > 0 ? "+" : ""}${fmtQty(m.qty)}</td>` +
      `<td class="num strong">${fmtQty(m.balance)}</td><td>${esc(m.status && m.status !== "active" ? tr(`status.${m.status}_long`) : "")}</td></tr>`), 5);
  $("ph-top").innerHTML = top.length ? plainTable([tr("col.customer"), tr("col.total_qty"), tr("col.orders"), tr("col.last"), tr("col.revenue")],
    top.map((t) => `<tr><td>${esc(t.name)}</td><td class="num">${fmtQty(t.qty)}</td><td class="num">${t.times}</td>` +
      `<td>${esc(t.last)}</td><td class="num">${fmtMoney(t.revenue)}</td></tr>`), 1) : `<p class="hint">${esc(tr("product.no_orders"))}</p>`;
  csvButton(box, `LichSu_${p.code}.csv`, headers,
    history.map((m) => [m.occurred_on, moveName(m.kind), m.code, m.who, placeName(m.location_id), m.qty, m.balance]));
}

function topCustomersOfProduct(productId, limit = 10) {
  const docs = new Map(data.documents.map((d) => [d.id, d]));
  const per = new Map();
  for (const l of data.lines) {
    if (l.product_id !== productId) continue;
    const d = docs.get(l.document_id);
    if (!d || (d.kind !== "delivery" && !isReturn(d)) || d.status !== "active" || !customerById[d.customer_id]) continue;
    const row = per.get(d.customer_id) || { name: customerById[d.customer_id].name, qty: 0, docs: new Set(), last: "", revenue: null };
    if (isReturn(d)) {  // sent back: only the money comes off (queries.product_top_customers)
      if (l.amount !== null && l.amount !== undefined) row.revenue = (row.revenue || 0) - l.amount;
      per.set(d.customer_id, row);
      continue;
    }
    row.qty += l.qty; row.docs.add(d.id);
    if (d.doc_date > row.last) row.last = d.doc_date;
    if (l.amount !== null && l.amount !== undefined) row.revenue = (row.revenue || 0) + l.amount;
    per.set(d.customer_id, row);
  }
  return [...per.values()].filter((r) => r.docs.size).map((r) => ({ ...r, times: r.docs.size })).sort((a, b) => b.qty - a.qty).slice(0, limit);
}

/* ---------------------------------------------------------------- customer detail */

function customerStats(id, from, to) {
  const docs = data.documents.filter((d) => d.customer_id === id && d.kind === "delivery" && d.status === "active" &&
                                           (!from || d.doc_date >= from) && (!to || d.doc_date <= to));
  let goods = 0, fees = 0, unpriced = 0;
  const perProduct = new Map();
  for (const d of docs) {
    fees += d.fee_amount || 0;
    const lines = linesByDoc[d.id] || [];
    if (lines.some((l) => l.amount === null || l.amount === undefined)) unpriced += 1;
    for (const l of lines) {
      if (l.amount !== null && l.amount !== undefined) goods += l.amount;
      const row = perProduct.get(l.product_id) || { qty: 0, docs: new Set(), last: "", revenue: null, min: null, max: null };
      row.qty += l.qty; row.docs.add(d.id);
      if (d.doc_date > row.last) row.last = d.doc_date;
      if (l.amount !== null && l.amount !== undefined) row.revenue = (row.revenue || 0) + l.amount;
      if (l.unit_price !== null && l.unit_price !== undefined) {
        row.min = row.min === null ? l.unit_price : Math.min(row.min, l.unit_price);
        row.max = row.max === null ? l.unit_price : Math.max(row.max, l.unit_price);
      }
      perProduct.set(l.product_id, row);
    }
  }
  // goods this customer sent back in the period: their money comes off the revenue, per product too
  let returned = 0;
  for (const d of data.documents) {
    if (d.customer_id !== id || !isReturn(d) || d.status !== "active" || (from && d.doc_date < from) || (to && d.doc_date > to)) continue;
    for (const l of linesByDoc[d.id] || []) {
      if (l.amount === null || l.amount === undefined) continue;
      returned += l.amount;
      const row = perProduct.get(l.product_id);
      if (row) row.revenue = (row.revenue || 0) - l.amount;
    }
  }
  return { returned, total: goods - returned, docs: docs.sort((a, b) => b.doc_date.localeCompare(a.doc_date) || String(b.code).localeCompare(String(a.code), "vi", { numeric: true })),
           goods, fees, unpriced, perProduct };
}

function showCustomer(id, from, to) {
  const c = customerById[id];
  if (!c) return;
  const s = customerStats(id, from, to);
  const stat = (label, value) => `<div class="stat"><span>${esc(label)}</span><b>${value}</b></div>`;
  const box = openDetail(
    backBar(c.name) +
    `<dl class="info"><dt>${esc(tr("col.contact"))}</dt><dd>${esc(c.contact)}</dd><dt>${esc(tr("col.phone"))}</dt><dd>${esc(c.phone)}</dd>` +
    `<dt>${esc(tr("col.address"))}</dt><dd>${esc(c.address)}</dd></dl>` +
    `<div class="grid period"><label>${esc(tr("st.from"))} <input id="cd-from" type="date" value="${esc(from || "")}"></label>` +
    `<label>${esc(tr("st.to"))} <input id="cd-to" type="date" value="${esc(to || "")}"></label></div>` +
    `<div class="cards">${stat(tr("col.orders"), s.docs.length)}${stat(tr("money.revenue"), fmtMoney(s.total))}` +
    (s.returned ? stat(tr("money.returned"), fmtMoney(s.returned)) : "") +
    `${stat(tr("detail.fees"), fmtMoney(s.fees))}${stat(tr("money.unpriced"), s.unpriced)}</div>` +
    `<h3>${esc(tr("customer.products"))}</h3><div id="cd-products"></div><h3>${esc(tr("customer.orders"))}</h3><div id="cd-orders"></div>`);
  for (const input of ["cd-from", "cd-to"]) {
    $(input).addEventListener("change", () => showCustomer(id, $("cd-from").value || null, $("cd-to").value || null));
  }
  const prodRows = [...s.perProduct.entries()].map(([pid, r]) => ({ p: productById[pid] || {}, ...r, times: r.docs.size }))
    .sort((a, b) => b.qty - a.qty);
  const heads = [tr("col.code"), tr("col.product"), tr("col.total_qty"), tr("col.orders"), tr("col.last"), tr("col.revenue"),
                 tr("col.price_low"), tr("col.price_high")];
  $("cd-products").innerHTML = prodRows.length ? plainTable(heads,
    prodRows.map((r) => `<tr><td>${esc(r.p.code)}</td><td>${esc(pn(r.p))} ${esc(pnOther(r.p))} ${esc(r.p.spec)}</td>` +
      `<td class="num">${fmtQty(r.qty)}</td><td class="num">${r.times}</td><td>${esc(r.last)}</td>` +
      `<td class="num">${fmtMoney(r.revenue)}</td><td class="num">${fmtMoney(r.min)}</td><td class="num">${fmtMoney(r.max)}</td></tr>`), 2)
    : `<p class="hint">${esc(tr("customer.none"))}</p>`;
  $("cd-orders").innerHTML = plainTable([tr("col.date"), tr("col.code"), tr("col.goods"), tr("col.fees"), ""],
    s.docs.map((d) => {
      const goods = (linesByDoc[d.id] || []).reduce((a, l) => a + (l.amount || 0), 0);
      return `<tr class="click" data-doc="${esc(d.id)}"><td>${esc(d.doc_date)}</td><td>${esc(d.code)}</td>` +
             `<td class="num">${fmtMoney(goods)}</td><td class="num">${fmtMoney(d.fee_amount)}</td><td class="hint">${esc(tr("customer.open"))}</td></tr>`;
    }), 2);
  for (const tr_ of $("cd-orders").querySelectorAll("tr[data-doc]")) tr_.addEventListener("dblclick", () => showOrder(tr_.dataset.doc));
  csvButton(box, `KhachHang_${c.name.replace(/[^\p{L}\p{N}]+/gu, "_")}.csv`,
    [tr("col.code"), tr("col.product"), tr("col.spec"), ...heads.slice(2)],
    prodRows.map((r) => [r.p.code, pn(r.p), r.p.spec, r.qty, r.times, r.last, r.revenue, r.min, r.max]));
}

/* ---------------------------------------------------------------- statistics */

let statsReady = false;

function initStats() {
  const now = new Date();
  $("st-month").value = todayLocal().slice(0, 7);
  $("st-day").value = todayLocal();
  $("st-from").value = `${now.getFullYear()}-01-01`;
  $("st-to").value = todayLocal();
  $("st-year").value = now.getFullYear();
  $("st-quarter").value = String(Math.floor(now.getMonth() / 3) + 1);
  if (!statsReady) {
    for (const id of ["st-period", "st-scope", "st-by", "st-day", "st-month", "st-year", "st-quarter", "st-from", "st-to", "st-value"]) {
      $(id).addEventListener("change", id === "st-period" || id === "st-scope" ? () => { syncStatsControls(); renderStats(); } : renderStats);
    }
    statsReady = true;
  }
  syncStatsControls();
  renderStats();
}

/* Never a blank page: no data yet says so, an error is written where the table would be. */
function renderStats() {
  const out = $("st-table");
  if (!data.products.length) {
    $("st-summary").innerHTML = ""; $("st-chart").innerHTML = ""; $("st-top").innerHTML = "";
    out.innerHTML = `<p class="hint">${esc(tr("st.no_data"))}</p>`;
    return;
  }
  try { drawStats(); } catch (e) {
    console.error(e);
    $("st-chart").innerHTML = ""; $("st-top").innerHTML = "";
    out.innerHTML = `<p class="error">${esc(tr("st.failed", { reason: e.message || String(e) }))}</p>`;
  }
}

function syncStatsControls() {
  const period = $("st-period").value;
  const show = { day: ["day"], month: ["month"], quarter: ["year", "quarter"], year: ["year"], range: ["from", "to"] }[period];
  for (const part of ["day", "month", "year", "quarter", "from", "to"]) $(`st-l-${part}`).classList.toggle("hidden", !show.includes(part));
  const scope = $("st-scope").value;
  $("st-l-value").classList.toggle("hidden", scope === "all");
  if (scope === "all") return;
  const options = scope === "category"
    ? [...new Set(data.products.map((p) => p.category).filter(Boolean))].sort((a, b) => a.localeCompare(b, "vi")).map((c) => [c, c])
    : scope === "product"
      ? data.products.slice().sort((a, b) => a.code.localeCompare(b.code)).map((p) => [String(p.id), `${p.code} · ${productName(p)}`])
      : data.customers.slice().sort((a, b) => a.name.localeCompare(b.name, "vi")).map((c) => [String(c.id), c.name]);
  const keep = $("st-value").value;
  $("st-value").innerHTML = options.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join("");
  if (options.some(([v]) => v === keep)) $("st-value").value = keep;
}

function statsRange() {
  const S = DibeStats;
  switch ($("st-period").value) {
    case "day": return [$("st-day").value, $("st-day").value];
    case "month": { const [y, m] = $("st-month").value.split("-").map(Number); return y ? S.monthRange(y, m) : [null, null]; }
    case "quarter": return S.quarterRange(Number($("st-year").value), Number($("st-quarter").value));
    case "year": return S.yearRange(Number($("st-year").value));
    default: return [$("st-from").value, $("st-to").value];
  }
}

function statsFilters() {
  const scope = $("st-scope").value, value = $("st-value").value;
  if (scope === "category") return { categories: [value] };
  if (scope === "product") return { productIds: [value] };
  if (scope === "customer") return { customerIds: [value] };
  return {};
}

const statsModel = () => ({ products: data.products, customers: data.customers, documents: data.documents, lines: data.lines,
                            movements: data.movements });

function drawStats() {
  const [start, end] = statsRange();
  const out = $("st-table");
  if (!start || !end || start > end || Number.isNaN(Date.parse(start)) || Number.isNaN(Date.parse(end))) {
    $("st-summary").innerHTML = ""; $("st-chart").innerHTML = ""; $("st-top").innerHTML = "";
    out.innerHTML = `<p class="error">${esc(tr("st.bad_period"))}</p>`;
    return;
  }
  const S = DibeStats, f = statsFilters(), by = $("st-by").value, model = statsModel();
  const rows = S.summary(model, start, end, f, by)
    .sort((a, b) => (a.category || "").localeCompare(b.category || "", "vi") || a.name_vi.localeCompare(b.name_vi, "vi") ||
                    (a.spec || "").localeCompare(b.spec || "", "vi"));
  const money = S.money(model, start, end, f);
  const stat = (label, value) => `<div class="stat"><span>${esc(label)}</span><b>${value}</b></div>`;
  $("st-summary").innerHTML =
    `<div class="cards">${stat(tr("money.revenue"), fmtMoney(money.total))}` +
    (money.returned ? stat(tr("money.returned"), fmtMoney(money.returned)) : "") +
    stat(tr("col.orders"), money.orders) +
    (money.fees === null ? "" : stat(tr("detail.fees"), fmtMoney(money.fees))) +
    `${stat(tr("money.unpriced"), money.unpriced)}</div>` +
    `<p class="hint">${esc(tr("st.range_note", { start, end }))}` +
    `${$("st-scope").value === "customer" ? " " + esc(tr("st.customer_note")) : ""}</p>`;

  const bucketLabels = rows.length && rows[0].per_bucket ? Object.keys(rows[0].per_bucket) : [];
  const cols = [
    { label: tr("col.code"), get: (r) => r.code }, { label: tr("col.product"), get: pn }, { label: tr("col.other_name"), get: pnOther },
    { label: tr("col.spec"), get: (r) => r.spec }, { label: tr("col.variant"), get: (r) => r.variant },
    { label: tr("col.opening"), get: (r) => r.opening, num: true, cls: "num", html: (r) => (r.opening === null ? "—" : fmtQty(r.opening)) },
    { label: tr("col.in"), get: (r) => r.qty_in, num: true, cls: "num", html: (r) => fmtQty(r.qty_in) },
    { label: tr("col.out"), get: (r) => r.qty_out, num: true, cls: "num", html: (r) => fmtQty(r.qty_out) },
    { label: tr("col.adjust"), get: (r) => r.adjust, num: true, cls: "num", html: (r) => fmtQty(r.adjust) },
    { label: tr("col.closing"), get: (r) => r.closing, num: true, cls: "num strong", html: (r) => (r.closing === null ? "—" : fmtQty(r.closing)) },
    { label: tr("col.revenue"), get: (r) => r.revenue, num: true, cls: "num", html: (r) => fmtMoney(r.revenue) },
    { label: tr("col.stock_note"), get: (r) => r.stock_note },
    ...bucketLabels.flatMap((b) => [
      { label: tr("st.bucket_in", { b }), get: (r) => r.per_bucket[b][0], num: true, cls: "num qty", html: (r) => fmtQty(r.per_bucket[b][0]) },
      { label: tr("st.bucket_out", { b }), get: (r) => r.per_bucket[b][1], num: true, cls: "num qty", html: (r) => fmtQty(r.per_bucket[b][1]) },
    ]),
  ];
  const el = buildTable("st-table", cols, rows, { key: (r) => r.product_id });
  el.insertAdjacentHTML("beforeend", `<p class="hint">${esc(tr("st.rows", { n: rows.length }))}</p>`);
  csvButton(el, `ThongKe_${start}_${end}.csv`, cols.map((c) => c.label), rows.map((r) => cols.map((c) => c.get(r))));

  $("st-chart").innerHTML = chartHtml(S.dailyOut(model, start, end, f));
  const top = S.topOut(model, start, end, f, 10);
  $("st-top").innerHTML = `<h3>${esc(tr("st.top"))}</h3>` + (top.length ? plainTable([tr("col.code"), tr("col.product"), tr("col.out"), tr("col.revenue")],
    top.map((r) => `<tr><td>${esc(r.code)}</td><td>${esc(productName(r))}</td><td class="num strong">${fmtQty(r.qty_out)}</td>` +
      `<td class="num">${fmtMoney(r.revenue)}</td></tr>`), 2) : `<p class="hint">${esc(tr("st.top_none"))}</p>`);
}

/** Outgoing quantity per day as SVG bars (classes are styled in style.css: the page's CSP forbids inline styles). */
function chartHtml(days) {
  if (days.length > 93) return `<p class="hint">${esc(tr("st.chart_long"))}</p>`;
  const max = Math.max(1, ...days.map(([, q]) => q));
  const w = 720, h = 160, pad = 24, bar = (w - 2 * pad) / days.length;
  const bars = days.map(([d, q], i) => {
    const bh = (q / max) * (h - 2 * pad);
    return `<rect class="bar" x="${(pad + i * bar + 1).toFixed(1)}" y="${(h - pad - bh).toFixed(1)}" width="${Math.max(1, bar - 2).toFixed(1)}" ` +
           `height="${bh.toFixed(1)}"><title>${esc(d)}: ${fmtQty(q)}</title></rect>`;
  }).join("");
  const step = Math.ceil(days.length / 8);
  const labels = days.map(([d], i) => (i % step === 0
    ? `<text class="axis" x="${(pad + i * bar).toFixed(1)}" y="${h - 6}">${esc(d.slice(8, 10) + "/" + d.slice(5, 7))}</text>` : "")).join("");
  return `<h3>${esc(tr("st.chart"))}</h3><svg viewBox="0 0 ${w} ${h}" class="chart" role="img" aria-label="${esc(tr("st.chart"))}">` +
         `<text class="axis" x="2" y="14">${fmtQty(max)}</text>${bars}${labels}</svg>`;
}

/* ---------------------------------------------------------------- gói dữ liệu .dibekho (package.js) */

async function pullEverything() {
  const { data, error } = await sb.rpc("sync_pull", { p_after: 0 });
  if (error) throw new Error(tr("pkg.pull_failed", { reason: error.message }));
  return data;
}

async function exportPackageWeb() {
  $("pkg-msg").textContent = tr("pkg.making");
  try {
    const { SQL, fflate } = await DBK_PKG.loadLibs();
    const pkg = DBK_PKG.buildPackage(SQL, fflate, await pullEverything(), new Date());
    saveFile(pkg.name, pkg.bytes);
    $("pkg-msg").textContent = tr("pkg.made", { name: pkg.name, products: pkg.manifest.products, deliveries: pkg.manifest.deliveries });
  } catch (e) {
    $("pkg-msg").textContent = "";
    alert(tr("pkg.failed", { reason: e.message || e }));
  }
}

$("pkg-export").addEventListener("click", exportPackageWeb);
