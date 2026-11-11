/* DiBeKho web: the detail windows and the statistics screen -- the information the app's own windows show,
   computed from the mirror tables loaded by app.js (data, productById, customerById, linesByDoc, ...).
   Statistics come from stats.js, which tests/test_web_stats.py keeps identical to the app's core/stats.py. */

"use strict";

const DOC_KIND = { delivery: "Phiếu giao hàng", receipt: "Hàng về", stock_count: "Kiểm kê", transfer: "Chuyển hàng",
                   trial: "Dùng thử" };
const MOVE_KIND = {
  delivery_out: "Phiếu giao hàng", delivery_reverse: "Huỷ phiếu giao hàng",
  receipt_in: "Hàng về", receipt_reverse: "Huỷ hàng về",
  count_adjust: "Kiểm kê", count_reverse: "Huỷ kiểm kê",
  transfer_out: "Chuyển đi", transfer_in: "Chuyển đến", transfer_reverse: "Huỷ chuyển hàng",
  trial_out: "Dùng thử", trial_reverse: "Huỷ dùng thử",
};
const PLACE = { 1: "Kho tổng", 2: "Văn phòng" };
const STATUS_TEXT = { active: "Hiệu lực", cancelled: "Đã huỷ", replaced: "Đã thay bằng bản sửa" };

/* ---------------------------------------------------------------- helpers */

function plainTable(headers, bodyRows, numericFrom) {
  const head = headers.map((h, i) => `<th class="${numericFrom !== undefined && i >= numericFrom ? "num" : ""}">${esc(h)}</th>`).join("");
  return `<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${bodyRows.join("")}</tbody></table></div>`;
}

/** A CSV the Excel on a Vietnamese Windows opens correctly: UTF-8 with a BOM, CRLF, ';' is NOT used (Excel reads ',' fine). */
function csvDownload(filename, headers, rows) {
  const cell = (v) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const text = "﻿" + [headers, ...rows].map((r) => r.map(cell).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

function csvButton(container, filename, headers, rows) {
  const btn = document.createElement("button");
  btn.className = "flat"; btn.textContent = "⭳ Xuất file CSV (mở được bằng Excel)";
  btn.addEventListener("click", () => csvDownload(filename, headers, rows));
  container.append(btn);
}

function backBar(title) {
  return `<div class="backbar"><button class="flat" id="detail-back">← Quay lại</button><h2>${esc(title)}</h2></div>`;
}

function openDetail(html) {
  document.querySelectorAll(".pane").forEach((p) => p.classList.add("hidden"));
  $("toolbar").classList.add("hidden");
  const box = $("detail");
  box.innerHTML = html;
  box.classList.remove("hidden");
  $("detail-back").addEventListener("click", showActivePane);
  window.scrollTo(0, 0);
  return box;
}

const todayIso = () => todayLocal();

function productName(p) {
  return [p.name_vi, p.spec, p.variant].filter(Boolean).join(" · ");
}

/* ---------------------------------------------------------------- order detail (inside the orders table) */

function placeOf(d) {
  if (d.kind === "transfer") return `${PLACE[d.location_id] || "?"} → ${PLACE[d.to_location_id] || "?"}`;
  if (d.kind === "delivery" || d.kind === "receipt" || d.kind === "trial") {
    const name = PLACE[d.location_id] || "Kho tổng";
    return d.kind === "delivery" && d.location_set === false ? `${name} (chưa chọn nơi lấy hàng)` : name;
  }
  return "";
}

function orderDetailHtml(d) {
  const c = customerById[d.customer_id];
  const lines = (linesByDoc[d.id] || []).slice().sort((a, b) => a.line_no - b.line_no);
  const info = [
    ["Loại", DOC_KIND[d.kind] || d.kind], ["Mã", d.code], ["Ngày", d.doc_date],
    ["Trạng thái", STATUS_TEXT[d.status] || d.status],
    ...(c ? [["Khách hàng", [c.name, c.contact, c.phone, c.address].filter(Boolean).join(" · ")]] : []),
    ...(d.kind === "receipt" ? [["Nguồn hàng", d.supplier_name || (d.receipt_source === "return" ? "Khách trả lại" : ""),
                                  ], ["Mã đơn gốc", d.ref_code]] : []),
    [d.kind === "receipt" ? "Nhập vào" : d.kind === "transfer" ? "Chuyển" : "Lấy hàng từ", placeOf(d)],
    ["Ghi chú", d.note],
    ...(d.fee_amount ? [["Phí khác (tính riêng)", fmtMoney(d.fee_amount)]] : []),
    ...(d.note_total !== null && d.note_total !== undefined ? [["Tổng tiền trên phiếu", fmtMoney(d.note_total)]] : []),
    ...(d.source_file ? [["File gốc", d.source_file]] : []),
  ].filter(([, v]) => v !== "" && v !== null && v !== undefined);
  const rows = lines.map((l) => {
    const p = productById[l.product_id] || {};
    return `<tr><td>${esc(p.code || "?")}</td><td>${esc(p.name_vi || "")} ${esc(p.name_zh || "")}</td>` +
           `<td>${esc(p.spec || "")}</td><td class="num">${fmtQty(l.qty)}</td>` +
           `<td class="num">${fmtMoney(l.unit_price)}</td><td class="num">${fmtMoney(l.amount)}</td>` +
           `<td>${esc(l.note)}</td></tr>`;
  });
  return `<dl class="info">${info.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>` +
    plainTable(["Mã", "Mặt hàng", "Quy cách", "SL", "Đơn giá", "Thành tiền", "Ghi chú"], rows, 3);
}

/* ---------------------------------------------------------------- product detail */

function productHistory(id) {
  const docs = new Map(data.documents.map((d) => [d.id, d]));
  const moves = data.movements.filter((m) => m.product_id === id)
    .sort((a, b) => a.occurred_on.localeCompare(b.occurred_on) || a.id - b.id);
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
    `<dl class="info"><dt>Tên Trung</dt><dd>${esc(p.name_zh)}</dd><dt>Nhóm</dt><dd>${esc(p.category)}</dd>` +
    `<dt>Đơn vị</dt><dd>${esc(p.unit)}</dd><dt>Ghi chú tồn kho</dt><dd>${esc(p.stock_note)}</dd></dl>` +
    `<div class="cards"><div class="stat"><span>Tồn</span><b>${fmtQty(st.total)}</b></div>` +
    `<div class="stat"><span>Kho tổng</span><b>${fmtQty(st[1])}</b></div>` +
    `<div class="stat"><span>Văn phòng</span><b>${fmtQty(st[2])}</b></div></div>` +
    `<h3>Lịch sử vào ra (mới nhất trước)</h3><div id="ph-table"></div>` +
    `<h3>Khách lấy nhiều nhất</h3><div id="ph-top"></div>`);
  const newest = history.slice().reverse();
  $("ph-table").innerHTML = plainTable(["Ngày", "Loại", "Mã phiếu", "Khách / nguồn", "Nơi", "Số lượng", "Tồn sau", "Phiếu"],
    newest.map((m) => `<tr class="${m.status && m.status !== "active" ? "closed" : ""}"><td>${esc(m.occurred_on)}</td>` +
      `<td>${esc(MOVE_KIND[m.kind] || m.kind)}</td><td>${esc(m.code)}</td><td>${esc(m.who)}</td>` +
      `<td>${esc(PLACE[m.location_id] || "")}</td><td class="num">${m.qty > 0 ? "+" : ""}${fmtQty(m.qty)}</td>` +
      `<td class="num strong">${fmtQty(m.balance)}</td><td>${esc(m.status && m.status !== "active" ? STATUS_TEXT[m.status] : "")}</td></tr>`), 5);
  $("ph-top").innerHTML = top.length ? plainTable(["Khách hàng", "Tổng số lượng", "Số đơn", "Lần cuối", "Doanh thu"],
    top.map((t) => `<tr><td>${esc(t.name)}</td><td class="num">${fmtQty(t.qty)}</td><td class="num">${t.times}</td>` +
      `<td>${esc(t.last)}</td><td class="num">${fmtMoney(t.revenue)}</td></tr>`), 1) : `<p class="hint">Chưa có đơn nào.</p>`;
  csvButton(box, `LichSu_${p.code}.csv`, ["Ngày", "Loại", "Mã phiếu", "Khách / nguồn", "Nơi", "Số lượng", "Tồn sau"],
    history.map((m) => [m.occurred_on, MOVE_KIND[m.kind] || m.kind, m.code, m.who, PLACE[m.location_id] || "", m.qty, m.balance]));
}

function topCustomersOfProduct(productId, limit = 10) {
  const docs = new Map(data.documents.map((d) => [d.id, d]));
  const per = new Map();
  for (const l of data.lines) {
    if (l.product_id !== productId) continue;
    const d = docs.get(l.document_id);
    if (!d || d.kind !== "delivery" || d.status !== "active" || !customerById[d.customer_id]) continue;
    const row = per.get(d.customer_id) || { name: customerById[d.customer_id].name, qty: 0, docs: new Set(), last: "", revenue: null };
    row.qty += l.qty; row.docs.add(d.id);
    if (d.doc_date > row.last) row.last = d.doc_date;
    if (l.amount !== null && l.amount !== undefined) row.revenue = (row.revenue || 0) + l.amount;
    per.set(d.customer_id, row);
  }
  return [...per.values()].map((r) => ({ ...r, times: r.docs.size })).sort((a, b) => b.qty - a.qty).slice(0, limit);
}

/* ---------------------------------------------------------------- customer detail */

function customerStats(id, from, to) {
  const docs = data.documents.filter((d) => d.customer_id === id && d.kind === "delivery" && d.status === "active" &&
                                           (!from || d.doc_date >= from) && (!to || d.doc_date <= to));
  const ids = new Set(docs.map((d) => d.id));
  const docById = new Map(docs.map((d) => [d.id, d]));
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
  return { docs: docs.sort((a, b) => b.doc_date.localeCompare(a.doc_date) || b.id - a.id), goods, fees, unpriced, perProduct, ids, docById };
}

function showCustomer(id, from, to) {
  const c = customerById[id];
  if (!c) return;
  const s = customerStats(id, from, to);
  const box = openDetail(
    backBar(c.name) +
    `<dl class="info"><dt>Người liên hệ</dt><dd>${esc(c.contact)}</dd><dt>Điện thoại</dt><dd>${esc(c.phone)}</dd>` +
    `<dt>Địa chỉ</dt><dd>${esc(c.address)}</dd></dl>` +
    `<div class="grid period"><label>Từ ngày <input id="cd-from" type="date" value="${esc(from || "")}"></label>` +
    `<label>Đến ngày <input id="cd-to" type="date" value="${esc(to || "")}"></label></div>` +
    `<div class="cards"><div class="stat"><span>Số đơn</span><b>${s.docs.length}</b></div>` +
    `<div class="stat"><span>Doanh thu (tiền hàng)</span><b>${fmtMoney(s.goods)}</b></div>` +
    `<div class="stat"><span>Phí khác (tính riêng)</span><b>${fmtMoney(s.fees)}</b></div>` +
    `<div class="stat"><span>Đơn chưa có giá</span><b>${s.unpriced}</b></div></div>` +
    `<h3>Mặt hàng hay mua</h3><div id="cd-products"></div><h3>Các đơn</h3><div id="cd-orders"></div>`);
  for (const input of ["cd-from", "cd-to"]) {
    $(input).addEventListener("change", () => showCustomer(id, $("cd-from").value || null, $("cd-to").value || null));
  }
  const prodRows = [...s.perProduct.entries()].map(([pid, r]) => ({ p: productById[pid] || {}, ...r, times: r.docs.size }))
    .sort((a, b) => b.qty - a.qty);
  $("cd-products").innerHTML = prodRows.length ? plainTable(
    ["Mã", "Mặt hàng", "Tổng SL", "Số đơn", "Lần cuối", "Doanh thu", "Giá thấp", "Giá cao"],
    prodRows.map((r) => `<tr><td>${esc(r.p.code)}</td><td>${esc(r.p.name_vi)} ${esc(r.p.name_zh)} ${esc(r.p.spec)}</td>` +
      `<td class="num">${fmtQty(r.qty)}</td><td class="num">${r.times}</td><td>${esc(r.last)}</td>` +
      `<td class="num">${fmtMoney(r.revenue)}</td><td class="num">${fmtMoney(r.min)}</td><td class="num">${fmtMoney(r.max)}</td></tr>`), 2)
    : `<p class="hint">Chưa có đơn nào trong kỳ này.</p>`;
  $("cd-orders").innerHTML = plainTable(["Ngày", "Mã", "Tiền hàng", "Phí khác", ""],
    s.docs.map((d) => {
      const goods = (linesByDoc[d.id] || []).reduce((a, l) => a + (l.amount || 0), 0);
      return `<tr class="doc" data-doc="${d.id}" data-cols="5"><td>${esc(d.doc_date)}</td><td>${esc(d.code)}</td>` +
             `<td class="num">${fmtMoney(goods)}</td><td class="num">${fmtMoney(d.fee_amount)}</td><td class="hint">xem chi tiết</td></tr>`;
    }), 2);
  for (const tr of $("cd-orders").querySelectorAll("tr.doc")) tr.addEventListener("click", () => toggleLines(tr));
  csvButton(box, `KhachHang_${c.name.replace(/[^\p{L}\p{N}]+/gu, "_")}.csv`,
    ["Mã", "Mặt hàng", "Quy cách", "Tổng SL", "Số đơn", "Lần cuối", "Doanh thu", "Giá thấp", "Giá cao"],
    prodRows.map((r) => [r.p.code, r.p.name_vi, r.p.spec, r.qty, r.times, r.last, r.revenue, r.min, r.max]));
}

/* ---------------------------------------------------------------- statistics */

let statsReady = false;

function initStats() {
  const now = new Date();
  $("st-month").value = todayIso().slice(0, 7);
  $("st-day").value = todayIso();
  $("st-from").value = `${now.getFullYear()}-01-01`;
  $("st-to").value = todayIso();
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
  $("st-value").innerHTML = options.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join("");
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
  if (scope === "product") return { productIds: [Number(value)] };
  if (scope === "customer") return { customerIds: [Number(value)] };
  return {};
}

function renderStats() {
  if (!data.products.length) return;
  const [start, end] = statsRange();
  const out = $("st-table");
  if (!start || !end || start > end || Number.isNaN(Date.parse(start)) || Number.isNaN(Date.parse(end))) {
    $("st-summary").innerHTML = ""; $("st-chart").innerHTML = ""; $("st-top").innerHTML = "";
    out.innerHTML = `<p class="error">Hãy chọn kỳ hợp lệ (ngày bắt đầu không sau ngày kết thúc).</p>`;
    return;
  }
  const S = DibeStats, f = statsFilters(), by = $("st-by").value;
  const model = { products: data.products, customers: data.customers, documents: data.documents, lines: data.lines, movements: data.movements };
  const rows = S.summary(model, start, end, f, by)
    .sort((a, b) => (a.category || "").localeCompare(b.category || "", "vi") || a.name_vi.localeCompare(b.name_vi, "vi") ||
                    (a.spec || "").localeCompare(b.spec || "", "vi"));
  const money = S.money(model, start, end, f);
  $("st-summary").innerHTML =
    `<div class="cards"><div class="stat"><span>Doanh thu (tiền hàng)</span><b>${fmtMoney(money.goods)}</b></div>` +
    `<div class="stat"><span>Số đơn</span><b>${money.orders}</b></div>` +
    (money.fees === null ? "" : `<div class="stat"><span>Phí khác (tính riêng)</span><b>${fmtMoney(money.fees)}</b></div>`) +
    `<div class="stat"><span>Đơn chưa có giá</span><b>${money.unpriced}</b></div></div>` +
    `<p class="hint">Từ ${esc(start)} đến ${esc(end)}. Chuyển hàng giữa hai nơi không tính là nhập hay xuất; xuất dùng thử tính vào “điều chỉnh”.` +
    `${$("st-scope").value === "customer" ? " Lọc theo khách chỉ áp dụng cho số xuất (tồn đầu/cuối không có)." : ""}</p>`;

  const bucketLabels = rows.length && rows[0].per_bucket ? Object.keys(rows[0].per_bucket) : [];
  const cols = [
    { label: "Mã", get: (r) => r.code }, { label: "Mặt hàng", get: (r) => r.name_vi }, { label: "Tên Trung", get: (r) => r.name_zh },
    { label: "Quy cách", get: (r) => r.spec }, { label: "Loại/màu", get: (r) => r.variant },
    { label: "Tồn đầu", get: (r) => r.opening, num: true, cls: "num", html: (r) => (r.opening === null ? "—" : fmtQty(r.opening)) },
    { label: "Nhập", get: (r) => r.qty_in, num: true, cls: "num", html: (r) => fmtQty(r.qty_in) },
    { label: "Xuất", get: (r) => r.qty_out, num: true, cls: "num", html: (r) => fmtQty(r.qty_out) },
    { label: "Điều chỉnh", get: (r) => r.adjust, num: true, cls: "num", html: (r) => fmtQty(r.adjust) },
    { label: "Tồn cuối", get: (r) => r.closing, num: true, cls: "num strong", html: (r) => (r.closing === null ? "—" : fmtQty(r.closing)) },
    { label: "Doanh thu", get: (r) => r.revenue, num: true, cls: "num", html: (r) => fmtMoney(r.revenue) },
    { label: "Ghi chú tồn kho", get: (r) => r.stock_note },
    ...bucketLabels.flatMap((b) => [
      { label: `${b} nhập`, get: (r) => r.per_bucket[b][0], num: true, cls: "num qty", html: (r) => fmtQty(r.per_bucket[b][0]) },
      { label: `${b} xuất`, get: (r) => r.per_bucket[b][1], num: true, cls: "num qty", html: (r) => fmtQty(r.per_bucket[b][1]) },
    ]),
  ];
  const el = buildTable("stats", cols, rows, {
    into: "st-table", rerender: renderStats,
    footer: `<p class="hint">${rows.length} mặt hàng. Bấm tiêu đề cột để sắp xếp.</p>`,
  });
  csvButton(el, `ThongKe_${start}_${end}.csv`, cols.map((c) => c.label), rows.map((r) => cols.map((c) => c.get(r))));

  $("st-chart").innerHTML = chartHtml(S.dailyOut(model, start, end, f));
  const top = S.topOut(model, start, end, f, 10);
  $("st-top").innerHTML = `<h3>Mặt hàng xuất nhiều nhất</h3>` + (top.length ? plainTable(["Mã", "Mặt hàng", "Xuất", "Doanh thu"],
    top.map((r) => `<tr><td>${esc(r.code)}</td><td>${esc(productName(r))}</td><td class="num strong">${fmtQty(r.qty_out)}</td>` +
      `<td class="num">${fmtMoney(r.revenue)}</td></tr>`), 2) : `<p class="hint">Chưa có hàng xuất trong kỳ này.</p>`);
}

/** Outgoing quantity per day as SVG bars (classes are styled in style.css: the page's CSP forbids inline styles). */
function chartHtml(days) {
  if (days.length > 93) return `<p class="hint">Biểu đồ theo ngày chỉ hiện cho kỳ tối đa 93 ngày; chọn “Chia theo tháng” để xem theo tháng.</p>`;
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
  return `<h3>Hàng xuất theo ngày</h3><svg viewBox="0 0 ${w} ${h}" class="chart" role="img" aria-label="Biểu đồ hàng xuất theo ngày">` +
         `<text class="axis" x="2" y="14">${fmtQty(max)}</text>${bars}${labels}</svg>`;
}
