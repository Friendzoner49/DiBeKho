/* DiBeKho web viewer (MVP-1, read-only).
   Plain JS on purpose: no build step, easy to edit (docs/cloud/04-thiet-ke-chot.md, section 7).
   Reads the mirror_* tables the desktop pushes; writes nothing. */

"use strict";

const sb = supabase.createClient(DIBEKHO_CLOUD.url, DIBEKHO_CLOUD.key);
const EMAIL_DOMAIN = "dibekho.local";
const KIND_VI = { delivery: "Phiếu giao hàng", receipt: "Hàng về", stock_count: "Kiểm kê",
                  transfer: "Chuyển hàng", trial: "Dùng thử" };
const STATUS_VI = { active: "", cancelled: "đã huỷ", replaced: "đã thay" };

const $ = (id) => document.getElementById(id);
const data = { products: [], customers: [], documents: [], lines: [], stock: [] };
let stockByProduct = {}, customerById = {}, productById = {}, linesByDoc = {};

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

function table(headers, rows) {
  return `<div class="scroll"><table><thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>` +
         `<tbody>${rows.join("")}</tbody></table></div>`;
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
  await loadAll();
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
  const rows = data.products
    .filter((p) => p.active)
    .filter((p) => !f || matches(f, `${p.code} ${p.name_vi} ${p.name_zh} ${p.spec} ${p.variant} ${p.category} ${p.stock_note}`))
    .map((p) => {
      const s = stockByProduct[p.id] || { total: 0, 1: 0, 2: 0 };
      const cls = s.total < 0 ? "neg" : "";
      return `<tr class="${cls}"><td>${esc(p.code)}</td><td>${esc(p.name_vi)}</td><td>${esc(p.name_zh)}</td>` +
             `<td>${esc(p.spec)}</td><td>${esc(p.variant)}</td><td class="num">${fmtQty(s.total)}</td>` +
             `<td class="num">${fmtQty(s[1])}</td><td class="num">${fmtQty(s[2])}</td>` +
             `<td>${esc(p.unit)}</td><td>${esc(p.stock_note)}</td></tr>`;
    });
  $("tab-stock").innerHTML =
    table(["Mã", "Mặt hàng", "Tên Trung", "Quy cách", "Loại/màu", "Tồn", "Kho tổng", "Văn phòng", "Đơn vị", "Ghi chú"], rows)
    + `<p class="hint">${rows.length} mặt hàng. Tồn âm tô đỏ.</p>`;
}

function renderOrders(f) {
  const rows = data.documents
    .filter((d) => {
      if (!f) return true;
      const customer = customerById[d.customer_id];
      const inLines = (linesByDoc[d.id] || []).some((l) => {
        const p = productById[l.product_id];
        return p && matches(f, `${p.code} ${p.name_vi} ${p.name_zh}`);
      });
      return matches(f, `${d.code} ${customer ? customer.name : ""} ${KIND_VI[d.kind] || d.kind} ${d.note}`) || inLines;
    })
    .slice(0, 500)
    .map((d) => {
      const customer = customerById[d.customer_id];
      const status = STATUS_VI[d.status] ?? d.status;
      return `<tr class="doc ${d.status !== "active" ? "closed" : ""}" data-doc="${d.id}">` +
             `<td>${esc(d.doc_date)}</td><td>${esc(KIND_VI[d.kind] || d.kind)}</td><td>${esc(d.code)}</td>` +
             `<td>${esc(customer ? customer.name : "")}</td><td>${status}</td>` +
             `<td class="num">${fmtMoney(d.note_total)}</td></tr>`;
    });
  $("tab-orders").innerHTML =
    table(["Ngày", "Loại", "Mã", "Khách hàng", "Trạng thái", "Tổng tiền"], rows)
    + `<p class="hint">Bấm một dòng để xem chi tiết. Hiện tối đa 500 phiếu mới nhất.</p>`;
  for (const tr of $("tab-orders").querySelectorAll("tr.doc")) {
    tr.addEventListener("click", () => toggleLines(tr));
  }
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
  detail.innerHTML = `<td colspan="6">${table(["Mã", "Mặt hàng", "Quy cách", "SL", "Đơn giá", "Thành tiền", "Ghi chú"], [inner])}</td>`;
  tr.after(detail);
}

function renderCustomers(f) {
  const rows = data.customers
    .filter((c) => !f || matches(f, `${c.name} ${c.contact} ${c.phone} ${c.address}`))
    .map((c) => `<tr><td>${esc(c.name)}</td><td>${esc(c.contact)}</td><td>${esc(c.phone)}</td><td>${esc(c.address)}</td></tr>`);
  $("tab-customers").innerHTML = table(["Khách hàng", "Người liên hệ", "Điện thoại", "Địa chỉ"], rows);
}

/* ---------------------------------------------------------------- wiring */

for (const btn of document.querySelectorAll(".tab")) {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".pane").forEach((p) => p.classList.add("hidden"));
    $(`tab-${btn.dataset.tab}`).classList.remove("hidden");
  });
}
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
