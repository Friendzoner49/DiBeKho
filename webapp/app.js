/* DiBeKho web viewer (MVP-1, read-only).
   Plain JS on purpose: no build step, easy to edit (docs/cloud/04-thiet-ke-chot.md, section 7).
   Reads the mirror_* tables the desktop pushes; writes nothing. */

"use strict";

const sb = supabase.createClient(DIBEKHO_CLOUD.url, DIBEKHO_CLOUD.key);
const EMAIL_DOMAIN = "dibekho.local";
const KIND_VI = { delivery: "Phiếu giao hàng", receipt: "Hàng về", stock_count: "Kiểm kê",
                  transfer: "Chuyển hàng", trial: "Dùng thử" };
const KIND_ORDER = ["delivery", "receipt", "stock_count", "transfer", "trial"];
const STATUS_VI = { active: "", cancelled: "đã huỷ", replaced: "đã thay" };

const $ = (id) => document.getElementById(id);
const data = { products: [], customers: [], documents: [], lines: [], stock: [] };
let stockByProduct = {}, customerById = {}, productById = {}, linesByDoc = {};
const sortState = { stock: { i: null, dir: 1 }, orders: { i: null, dir: 1 }, customers: { i: null, dir: 1 }, stats: { i: null, dir: 1 } };
let orderKind = "all";
let lowDefault = 30;  // the app's alarm level, sent with each push (sync_state.low_stock_default)

/* ---------------------------------------------------------------- helpers */

function unaccent(s) {
  return (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replaceAll("đ", "d");  // đ -> d, like the app's unaccent()
}

function matches(needle, hay) {
  return unaccent(needle).split(/\s+/).filter(Boolean).every((w) => unaccent(hay).includes(w));
}

function fmtQty(n) {
  if (n === null || n === undefined) return "";
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 1000) / 1000).replace(".", ",");
}

// the cloud keeps UTC: show the viewer's own time zone, like the app does
function fmtTime(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function fmtMoney(n) {
  return n === null || n === undefined ? "" : Number(n).toLocaleString("vi-VN");
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* Sortable table: cols = [{label, get, num?, cls?}], rowClass/rowAttr optional per item.
   Clicking a header sorts by that column; clicking again flips the direction. */
function buildTable(pane, cols, items, { rowClass = () => "", rowAttr = () => "", footer = "", into = null, rerender = null } = {}) {
  const st = sortState[pane];
  let rows = items;
  if (st.i !== null && cols[st.i]) {
    const c = cols[st.i];
    rows = items.slice().sort((a, b) => {
      const va = c.get(a), vb = c.get(b);
      if (c.num) return ((va ?? -Infinity) - (vb ?? -Infinity)) * st.dir;
      return String(va ?? "").localeCompare(String(vb ?? ""), "vi") * st.dir;
    });
  }
  const head = cols.map((c, i) =>
    `<th data-i="${i}" class="sortable ${st.i === i ? (st.dir > 0 ? "asc" : "desc") : ""}">${c.label}</th>`).join("");
  const body = rows.map((item) =>
    `<tr class="${rowClass(item)}" ${rowAttr(item)}>` +
    cols.map((c) => `<td class="${c.cls || ""}">${c.html ? c.html(item) : esc(c.get(item))}</td>`).join("") +
    "</tr>").join("");
  const el = $(into || `tab-${pane}`);
  el.innerHTML = `<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>${footer}`;
  for (const th of el.querySelectorAll("th.sortable")) {
    th.addEventListener("click", () => {
      const i = Number(th.dataset.i);
      if (st.i === i) st.dir *= -1; else { st.i = i; st.dir = 1; }
      (rerender || render)();
    });
  }
  return el;
}

/* ---------------------------------------------------------------- login */

async function signIn() {
  const user = $("user").value.trim();
  const email = user.includes("@") ? user : `${user}@${EMAIL_DOMAIN}`;
  $("login-error").textContent = "";
  const { error } = await sb.auth.signInWithPassword({ email, password: $("password").value });
  if (error) {
    $("login-error").textContent = /credentials/i.test(error.message)
      ? "Sai tên đăng nhập hoặc mật khẩu." : `Không đăng nhập được: ${error.message}`;
    return;
  }
  showApp();
}

async function showApp() {
  $("login").classList.add("hidden");
  $("app").classList.remove("hidden");
  // filter by our own id: the desktop account may read every profile row, which would break maybeSingle()
  const { data: { user } } = await sb.auth.getUser();
  const { data: prof } = await sb.from("profiles").select("role").eq("user_id", user.id).maybeSingle();
  if (prof && (prof.role === "editor" || prof.role === "desktop")) {
    $("send-tab").classList.remove("hidden");
  }
  await loadAll();
  initSendForm();
  initStats();
}

/* ---------------------------------------------------------------- data */

async function fetchAll(tableName, order) {
  // PostgREST pages at 1000 rows: loop so a long history still loads completely
  const out = [];
  for (let from = 0; ; from += 1000) {
    let q = sb.from(tableName).select("*").range(from, from + 999);
    if (order) q = q.order(...order);
    const { data: rows, error } = await q;
    if (error) throw error;
    out.push(...rows);
    if (rows.length < 1000) return out;
  }
}

async function loadAll() {
  $("load-error").textContent = "";
  try {
    const [products, customers, documents, lines, stock, state] = await Promise.all([
      fetchAll("mirror_products", ["category"]),
      fetchAll("mirror_customers", ["name"]),
      fetchAll("mirror_documents", ["doc_date", { ascending: false }]),
      fetchAll("mirror_document_lines"),
      fetchAll("mirror_stock"),
      sb.from("sync_state").select("*").maybeSingle(),
    ]);
    Object.assign(data, { products, customers, documents, lines, stock });
    stockByProduct = {}; linesByDoc = {}; customerById = {}; productById = {};
    for (const s of stock) {
      const t = stockByProduct[s.product_id] ||= { total: 0, 1: 0, 2: 0 };
      t.total += s.qty; t[s.location_id] = (t[s.location_id] || 0) + s.qty;
    }
    for (const l of lines) (linesByDoc[l.document_id] ||= []).push(l);
    for (const c of customers) customerById[c.id] = c;
    for (const p of products) productById[p.id] = p;
    if (state.data) {
      const when = fmtTime(state.data.last_push_at);
      $("freshness").textContent = `Dữ liệu từ máy ${state.data.device_name}, lúc ${when}`;
      // the app's alarm level (0 = off); an older push or a project without the column falls back to the app's 30
      const level = Number(state.data.low_stock_default);
      lowDefault = Number.isFinite(level) && state.data.low_stock_default !== null ? level : 30;
    }
    render();
  } catch (e) {
    $("load-error").textContent = `Không tải được dữ liệu: ${e.message || e}`;
  }
}

/* ---------------------------------------------------------------- render */

function render() {
  const f = $("filter").value;
  renderStock(f); renderOrders(f); renderCustomers(f);
}

function renderStock(f) {
  const stockOf = (p) => stockByProduct[p.id] || { total: 0, 1: 0, 2: 0 };
  const items = data.products
    .filter((p) => p.active)
    .filter((p) => !f || matches(f, `${p.code} ${p.name_vi} ${p.name_zh} ${p.spec} ${p.variant} ${p.category} ${p.stock_note}`));
  const stockTable = buildTable("stock", [
    { label: "Mã", get: (p) => p.code },
    { label: "Mặt hàng", get: (p) => p.name_vi },
    { label: "Tên Trung", get: (p) => p.name_zh },
    { label: "Quy cách", get: (p) => p.spec },
    { label: "Loại/màu", get: (p) => p.variant },
    { label: "Nhóm", get: (p) => p.category },
    { label: "Tồn", get: (p) => stockOf(p).total, num: true, cls: "num strong", html: (p) => fmtQty(stockOf(p).total) },
    { label: "Kho tổng", get: (p) => stockOf(p)[1], num: true, cls: "num qty", html: (p) => fmtQty(stockOf(p)[1]) },
    { label: "Văn phòng", get: (p) => stockOf(p)[2], num: true, cls: "num qty", html: (p) => fmtQty(stockOf(p)[2]) },
    { label: "Đơn vị", get: (p) => p.unit },
    { label: "Ghi chú", get: (p) => p.stock_note },
  ], items, {
    // same rule as the app (stock.is_low): negative = red, below the alarm level = orange
    rowClass: (p) => {
      const total = stockOf(p).total;
      return "click " + (total < 0 ? "neg" : (lowDefault && total < lowDefault ? "low" : ""));
    },
    rowAttr: (p) => `data-pid="${p.id}"`,
    footer: `<p class="hint">${items.length} mặt hàng. <span class="key low">Cam</span> dưới mức báo động` +
            `${lowDefault ? ` (${fmtQty(lowDefault)})` : " (đang tắt)"}, <span class="key neg">đỏ</span> tồn âm. ` +
            `Bấm tiêu đề cột để sắp xếp, bấm một dòng để xem lịch sử vào ra.</p>`,
  });
  for (const tr of stockTable.querySelectorAll("tr[data-pid]")) {
    tr.addEventListener("click", () => showProduct(Number(tr.dataset.pid)));
  }
}

function renderOrders(f) {
  const filtered = data.documents.filter((d) => {
    if (orderKind !== "all" && d.kind !== orderKind) return false;
    if (!f) return true;
    const customer = customerById[d.customer_id];
    const inLines = (linesByDoc[d.id] || []).some((l) => {
      const p = productById[l.product_id];
      return p && matches(f, `${p.code} ${p.name_vi} ${p.name_zh}`);
    });
    return matches(f, `${d.code} ${customer ? customer.name : ""} ${KIND_VI[d.kind] || d.kind} ${d.note}`) || inLines;
  });

  // one chip per document kind, like the app's separate lists; counts follow the search box
  const counts = {};
  for (const d of data.documents) counts[d.kind] = (counts[d.kind] || 0) + 1;
  const chips = ["all", ...KIND_ORDER.filter((k) => counts[k])].map((k) =>
    `<button class="chip ${orderKind === k ? "active" : ""}" data-kind="${k}">` +
    `${k === "all" ? "Tất cả" : KIND_VI[k]} (${k === "all" ? data.documents.length : counts[k]})</button>`).join("");

  const showCustomer = orderKind === "all" || orderKind === "delivery" || orderKind === "receipt";
  const cols = [
    { label: "Ngày", get: (d) => d.doc_date },
    ...(orderKind === "all" ? [{ label: "Loại", get: (d) => KIND_VI[d.kind] || d.kind }] : []),
    { label: "Mã", get: (d) => d.code },
    ...(showCustomer ? [{ label: "Khách hàng", get: (d) => (customerById[d.customer_id] || {}).name || "" }] : []),
    { label: "Trạng thái", get: (d) => STATUS_VI[d.status] ?? d.status },
    { label: "Tổng tiền", get: (d) => d.note_total, num: true, cls: "num", html: (d) => fmtMoney(d.note_total) },
  ];
  const el = buildTable("orders", cols, filtered.slice(0, 500), {
    rowClass: (d) => `doc ${d.status !== "active" ? "closed" : ""}`,
    rowAttr: (d) => `data-doc="${d.id}" data-cols="${cols.length}"`,
    footer: `<p class="hint">Bấm một dòng để xem chi tiết. Hiện tối đa 500 phiếu mới nhất.</p>`,
  });
  el.insertAdjacentHTML("afterbegin", `<div class="chips">${chips}</div>`);
  for (const chip of el.querySelectorAll(".chip")) {
    chip.addEventListener("click", () => { orderKind = chip.dataset.kind; render(); });
  }
  for (const tr of el.querySelectorAll("tr.doc")) tr.addEventListener("click", () => toggleLines(tr));
}

function toggleLines(tr) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains("detail")) { next.remove(); return; }
  const doc = data.documents.find((d) => String(d.id) === tr.dataset.doc);
  if (!doc) return;
  const detail = document.createElement("tr");
  detail.className = "detail";
  detail.innerHTML = `<td colspan="${tr.dataset.cols}">${orderDetailHtml(doc)}</td>`;
  tr.after(detail);
}

function renderCustomers(f) {
  const items = data.customers.filter((c) => !f || matches(f, `${c.name} ${c.contact} ${c.phone} ${c.address}`));
  const customerTable = buildTable("customers", [
    { label: "Khách hàng", get: (c) => c.name },
    { label: "Người liên hệ", get: (c) => c.contact },
    { label: "Điện thoại", get: (c) => c.phone },
    { label: "Địa chỉ", get: (c) => c.address },
  ], items, {
    rowClass: () => "click",
    rowAttr: (c) => `data-cid="${c.id}"`,
    footer: `<p class="hint">Bấm một dòng để xem doanh thu và các đơn của khách.</p>`,
  });
  for (const tr of customerTable.querySelectorAll("tr[data-cid]")) {
    tr.addEventListener("click", () => showCustomer(Number(tr.dataset.cid)));
  }
}

/* ---------------------------------------------------------------- staff requests (web_inbox) */

const XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const MAX_FILE = 2 * 1024 * 1024;  // same limit as the bucket and the desktop check
let productLabels = {};  // "SP001 · name · spec" -> product id

// the viewer's own calendar day: toISOString() would give the UTC day, a day off after midnight in Vietnam
function todayLocal() {
  const d = new Date(), p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function productLabel(p) {
  return [p.code, p.name_vi, p.spec, p.variant].filter(Boolean).join(" · ");
}

function initSendForm() {
  $("rc-date").value = todayLocal();
  $("ct-date").value = todayLocal();
  productLabels = {};
  $("products-dl").innerHTML = data.products.filter((p) => p.active).map((p) => {
    const label = productLabel(p);
    productLabels[label] = p.id;
    return `<option value="${esc(label)}">`;
  }).join("");
  if (!$("rc-lines").children.length) { addLine(); addLine(); addLine(); }
  if (!$("ct-lines").children.length) { addCountLine(); addCountLine(); addCountLine(); }
  loadSent();
}

/* ---- goods in */

function addLine() {
  const row = document.createElement("div");
  row.className = "line";
  row.innerHTML = `<input class="rc-product" list="products-dl" placeholder="Gõ mã hoặc tên hàng…">` +
    `<input class="rc-qty" type="number" min="0" step="any" placeholder="SL">` +
    `<input class="rc-lnote" placeholder="Ghi chú">` +
    `<button class="flat rc-del" title="Xoá dòng">✕</button>`;
  row.querySelector(".rc-del").addEventListener("click", () => row.remove());
  $("rc-lines").append(row);
}

async function sendReceipt() {
  $("rc-error").textContent = ""; $("rc-msg").textContent = "";
  const lines = [];
  for (const row of $("rc-lines").querySelectorAll(".line")) {
    const label = row.querySelector(".rc-product").value.trim();
    const qty = parseFloat(row.querySelector(".rc-qty").value.replace(",", "."));
    if (!label && !row.querySelector(".rc-qty").value) continue;  // empty row
    const id = productLabels[label];
    if (!id) { $("rc-error").textContent = `Không nhận ra mặt hàng "${label}". Hãy chọn từ danh sách gợi ý.`; return; }
    if (!(qty > 0)) { $("rc-error").textContent = `Số lượng của "${label}" phải lớn hơn 0.`; return; }
    lines.push({ product_id: id, qty, note: row.querySelector(".rc-lnote").value.trim() });
  }
  if (!lines.length) { $("rc-error").textContent = "Chưa có dòng hàng nào."; return; }
  if (!$("rc-source").value.trim()) { $("rc-error").textContent = "Hãy ghi nguồn hàng."; return; }
  const payload = {
    doc_date: $("rc-date").value,
    supplier_name: $("rc-source").value.trim(),
    location_id: Number($("rc-loc").value),
    note: $("rc-note").value.trim(),
    lines,
  };
  const { error } = await sb.from("web_inbox").insert({ kind: "receipt", payload });
  if (error) { $("rc-error").textContent = `Không gửi được: ${error.message}`; return; }
  $("rc-msg").textContent = "Đã gửi. Phiếu sẽ vào sổ sau khi máy chính duyệt.";
  $("rc-lines").innerHTML = ""; addLine(); addLine(); addLine();
  $("rc-note").value = "";
  loadSent();
}

/* ---- delivery note (Excel file) */

async function sendDelivery() {
  const fail = (text) => { $("dl-error").textContent = text; };
  $("dl-error").textContent = ""; $("dl-msg").textContent = "";
  const file = $("dl-file").files[0];
  if (!file) return fail("Hãy chọn file phiếu giao hàng.");
  if (!/\.xlsx$/i.test(file.name)) return fail("Chỉ nhận file Excel .xlsx. Nếu là file .xls, hãy mở bằng Excel rồi Lưu thành .xlsx.");
  if (file.size === 0) return fail("File trống.");
  if (file.size > MAX_FILE) return fail("File lớn hơn 2 MB.");
  $("dl-send").disabled = true;
  try {
    const buf = await file.arrayBuffer();
    const digest = await crypto.subtle.digest("SHA-256", buf);
    const sha256 = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
    // an ASCII-only storage key; the real file name travels in the payload
    const path = `${crypto.randomUUID()}/phieu.xlsx`;
    const up = await sb.storage.from("inbox-files").upload(path, buf, { contentType: XLSX_MIME, upsert: false });
    if (up.error) return fail(`Không tải được file lên: ${up.error.message}`);
    const { error } = await sb.from("web_inbox").insert({
      kind: "delivery_file",
      payload: { file_path: path, file_name: file.name, size: file.size, sha256, note: $("dl-note").value.trim() },
    });
    if (error) return fail(`Không gửi được: ${error.message}`);
    $("dl-msg").textContent = "Đã gửi. Phiếu sẽ được đọc sau khi máy chính duyệt.";
    $("dl-file").value = ""; $("dl-note").value = "";
    loadSent();
  } finally {
    $("dl-send").disabled = false;
  }
}

/* ---- stock count */

function addCountLine(product) {
  const row = document.createElement("div");
  row.className = "line count";
  row.innerHTML = `<input class="ct-product" list="products-dl" placeholder="Gõ mã hoặc tên hàng…">` +
    `<input class="ct-qty" inputmode="decimal" placeholder="Đếm được">` +
    `<button class="flat ct-del" title="Xoá dòng">✕</button>`;
  if (product) {
    const input = row.querySelector(".ct-product");
    input.value = productLabel(product);
    input.readOnly = true;  // pre-filled rows only need a number
  }
  row.querySelector(".ct-del").addEventListener("click", () => row.remove());
  $("ct-lines").append(row);
}

function fillCountLines() {
  $("ct-lines").innerHTML = "";
  data.products.filter((p) => p.active)
    .sort((a, b) => (a.category || "").localeCompare(b.category || "", "vi") || a.code.localeCompare(b.code))
    .forEach((p) => addCountLine(p));
}

async function sendCount() {
  const fail = (text) => { $("ct-error").textContent = text; };
  $("ct-error").textContent = ""; $("ct-msg").textContent = "";
  const day = $("ct-date").value;
  if (!day) return fail("Hãy chọn ngày kiểm kê.");
  if (day > todayLocal()) return fail("Ngày kiểm kê không được ở tương lai.");
  const lines = [], seen = new Set();
  for (const row of $("ct-lines").querySelectorAll(".line")) {
    const label = row.querySelector(".ct-product").value.trim();
    const raw = row.querySelector(".ct-qty").value.trim();
    if (!raw) continue;  // blank = this product was not counted
    const id = productLabels[label];
    if (!id) return fail(`Không nhận ra mặt hàng "${label}". Hãy chọn từ danh sách gợi ý.`);
    const qty = Number(raw.replace(",", "."));
    if (!Number.isFinite(qty) || qty < 0) return fail(`Số đếm của "${label}" không hợp lệ (phải là số từ 0 trở lên).`);
    if (seen.has(id)) return fail(`Mặt hàng "${label}" bị nhập hai lần.`);
    seen.add(id);
    lines.push({ product_id: id, qty });
  }
  if (!lines.length) return fail("Chưa có mặt hàng nào được đếm.");
  const place = $("ct-loc").selectedOptions[0].text;
  // a count cannot be edited after sending: ask once
  if (!confirm(`Gửi kiểm kê ${lines.length} mặt hàng tại ${place}, ngày ${day}?`)) return;
  const payload = { count_date: day, location_id: Number($("ct-loc").value), note: $("ct-note").value.trim(), lines };
  $("ct-send").disabled = true;
  try {
    const { error } = await sb.from("web_inbox").insert({ kind: "stock_count", payload });
    if (error) return fail(`Không gửi được: ${error.message}`);
    $("ct-msg").textContent = "Đã gửi. Kiểm kê sẽ vào sổ sau khi máy chính duyệt.";
    $("ct-lines").innerHTML = ""; addCountLine(); addCountLine(); addCountLine();
    $("ct-note").value = "";
    loadSent();
  } finally {
    $("ct-send").disabled = false;
  }
}

/* ---- what was sent */

const SENT_KIND = { receipt: "Hàng về", delivery_file: "Phiếu giao hàng", stock_count: "Kiểm kê" };

function sentDetail(r) {
  const p = r.payload || {};
  if (r.kind === "delivery_file") return p.file_name || "";
  if (r.kind === "stock_count") {
    return `${p.count_date || ""} · ${p.location_id === 2 ? "Văn phòng" : "Kho tổng"} · ${(p.lines || []).length} mặt hàng`;
  }
  return `${p.doc_date || ""} · ${p.supplier_name || ""} · ${(p.lines || []).length} dòng`;
}

function sentStatus(r) {
  if (r.status === "rejected") return "✖ Bị từ chối";
  if (r.status !== "applied") return "⏳ Chờ máy chính duyệt";
  const res = r.result || {};
  if (r.kind === "delivery_file") return res.already ? "✔ Máy chính đã có phiếu này" : "✔ Đã nhận, máy chính đang đọc";
  return `✔ Đã vào sổ${res.code ? ` (${esc(res.code)})` : ""}`;
}

async function loadSent() {
  const { data: rows, error } = await sb.from("web_inbox").select("*")
    .order("created_at", { ascending: false }).limit(50);
  if (error || !rows) return;
  $("rc-sent").innerHTML = `<div class="scroll"><table><thead><tr>` +
    `<th>Gửi lúc</th><th>Loại</th><th>Nội dung</th><th>Trạng thái</th></tr></thead><tbody>` +
    rows.map((r) => `<tr><td>${esc(fmtTime(r.created_at))}</td><td>${esc(SENT_KIND[r.kind] || r.kind)}</td>` +
      `<td>${esc(sentDetail(r))}</td><td>${sentStatus(r)}</td></tr>`).join("") +
    `</tbody></table></div>`;
}

/* ---------------------------------------------------------------- wiring */

let activeTab = "stock";
const NO_SEARCH_TABS = ["send", "stats"];  // the search box does not apply to the forms and the statistics

function showActivePane() {
  document.querySelectorAll(".pane").forEach((p) => p.classList.add("hidden"));
  $(`tab-${activeTab}`).classList.remove("hidden");
  $("toolbar").classList.toggle("hidden", NO_SEARCH_TABS.includes(activeTab));
}

for (const btn of document.querySelectorAll(".tab")) {
  btn.addEventListener("click", () => {
    activeTab = btn.dataset.tab;
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    showActivePane();
  });
}
for (const chip of document.querySelectorAll("#send-kinds .chip")) {
  chip.addEventListener("click", () => {
    document.querySelectorAll("#send-kinds .chip").forEach((c) => c.classList.toggle("active", c === chip));
    for (const kind of ["receipt", "delivery", "count"]) $(`send-${kind}`).classList.toggle("hidden", kind !== chip.dataset.send);
  });
}
$("rc-add").addEventListener("click", addLine);
$("rc-send").addEventListener("click", sendReceipt);
$("dl-send").addEventListener("click", sendDelivery);
$("ct-add").addEventListener("click", () => addCountLine());
$("ct-fill").addEventListener("click", fillCountLines);
$("ct-send").addEventListener("click", sendCount);
$("login-btn").addEventListener("click", signIn);
$("password").addEventListener("keydown", (e) => e.key === "Enter" && signIn());
$("filter").addEventListener("input", render);
$("reload").addEventListener("click", loadAll);
$("logout").addEventListener("click", async () => { await sb.auth.signOut(); location.reload(); });

sb.auth.getSession().then(({ data: { session } }) => {
  (session ? showApp() : Promise.resolve()).finally(() => {
    if (!session) $("login").classList.remove("hidden");
  });
});
