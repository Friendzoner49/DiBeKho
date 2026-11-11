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
const sortState = { stock: { i: null, dir: 1 }, orders: { i: null, dir: 1 }, customers: { i: null, dir: 1 } };
let orderKind = "all";

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

function fmtMoney(n) {
  return n === null || n === undefined ? "" : Number(n).toLocaleString("vi-VN");
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* Sortable table: cols = [{label, get, num?, cls?}], rowClass/rowAttr optional per item.
   Clicking a header sorts by that column; clicking again flips the direction. */
function buildTable(pane, cols, items, { rowClass = () => "", rowAttr = () => "", footer = "" } = {}) {
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
  const el = $(`tab-${pane}`);
  el.innerHTML = `<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>${footer}`;
  for (const th of el.querySelectorAll("th.sortable")) {
    th.addEventListener("click", () => {
      const i = Number(th.dataset.i);
      if (st.i === i) st.dir *= -1; else { st.i = i; st.dir = 1; }
      render();
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
      const when = String(state.data.last_push_at).slice(0, 16).replace("T", " ");
      $("freshness").textContent = `Dữ liệu từ máy ${state.data.device_name}, lúc ${when}`;
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
  buildTable("stock", [
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
    rowClass: (p) => (stockOf(p).total < 0 ? "neg" : ""),
    footer: `<p class="hint">${items.length} mặt hàng. Tồn âm tô đỏ. Bấm tiêu đề cột để sắp xếp.</p>`,
  });
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
  const docLines = (linesByDoc[tr.dataset.doc] || []).slice().sort((a, b) => a.line_no - b.line_no);
  const inner = docLines.map((l) => {
    const p = productById[l.product_id] || {};
    return `<tr><td>${esc(p.code || "?")}</td><td>${esc(p.name_vi || "")} ${esc(p.name_zh || "")}</td>` +
           `<td>${esc(p.spec || "")}</td><td class="num">${fmtQty(l.qty)}</td>` +
           `<td class="num">${fmtMoney(l.unit_price)}</td><td class="num">${fmtMoney(l.amount)}</td>` +
           `<td>${esc(l.note)}</td></tr>`;
  }).join("");
  const detail = document.createElement("tr");
  detail.className = "detail";
  detail.innerHTML = `<td colspan="${tr.dataset.cols}"><div class="scroll"><table>` +
    `<thead><tr><th>Mã</th><th>Mặt hàng</th><th>Quy cách</th><th>SL</th><th>Đơn giá</th><th>Thành tiền</th><th>Ghi chú</th></tr></thead>` +
    `<tbody>${inner}</tbody></table></div></td>`;
  tr.after(detail);
}

function renderCustomers(f) {
  const items = data.customers.filter((c) => !f || matches(f, `${c.name} ${c.contact} ${c.phone} ${c.address}`));
  buildTable("customers", [
    { label: "Khách hàng", get: (c) => c.name },
    { label: "Người liên hệ", get: (c) => c.contact },
    { label: "Điện thoại", get: (c) => c.phone },
    { label: "Địa chỉ", get: (c) => c.address },
  ], items);
}

/* ---------------------------------------------------------------- send goods-in (web_inbox) */

let productLabels = {};  // "SP001 · name · spec" -> product id

function initSendForm() {
  $("rc-date").value = new Date().toISOString().slice(0, 10);
  productLabels = {};
  $("products-dl").innerHTML = data.products.filter((p) => p.active).map((p) => {
    const label = [p.code, p.name_vi, p.spec, p.variant].filter(Boolean).join(" · ");
    productLabels[label] = p.id;
    return `<option value="${esc(label)}">`;
  }).join("");
  if (!$("rc-lines").children.length) { addLine(); addLine(); addLine(); }
  loadSent();
}

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

async function loadSent() {
  const { data: rows, error } = await sb.from("web_inbox").select("*")
    .order("created_at", { ascending: false }).limit(50);
  if (error || !rows) return;
  const label = (r) => r.status === "applied" ? `✔ Đã vào sổ${r.result && r.result.code ? ` (${r.result.code})` : ""}`
    : r.status === "rejected" ? "✖ Bị từ chối" : "⏳ Chờ máy chính duyệt";
  $("rc-sent").innerHTML = `<div class="scroll"><table><thead><tr>` +
    `<th>Gửi lúc</th><th>Ngày phiếu</th><th>Nguồn</th><th>Số dòng</th><th>Trạng thái</th></tr></thead><tbody>` +
    rows.map((r) => `<tr><td>${esc(String(r.created_at).slice(0, 16).replace("T", " "))}</td>` +
      `<td>${esc((r.payload || {}).doc_date || "")}</td><td>${esc((r.payload || {}).supplier_name || "")}</td>` +
      `<td class="num">${((r.payload || {}).lines || []).length}</td><td>${label(r)}</td></tr>`).join("") +
    `</tbody></table></div>`;
}

/* ---------------------------------------------------------------- wiring */

for (const btn of document.querySelectorAll(".tab")) {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".pane").forEach((p) => p.classList.add("hidden"));
    $(`tab-${btn.dataset.tab}`).classList.remove("hidden");
  });
}
$("rc-add").addEventListener("click", addLine);
$("rc-send").addEventListener("click", sendReceipt);
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
