/* DiBeKho web, owner mode: what the owner (the 'desktop' account) can do from the web, like in the app.
   Every command is a row in web_inbox that the main machine carries out the next time it is open
   (core/cloud/commands.py). Rows are named by FINGERPRINT (id + code + created_at): if the shop's database was
   undone or restored since the page was loaded, the main machine refuses the command with a reason instead of
   hitting another row. Staff never see any of this: the server only lets the 'desktop' account send commands. */

"use strict";

let userRole = "";
let receiptEdit = null;  // { doc, fp } while the goods-in form edits an existing receipt
const isOwner = () => userRole === "desktop";

/* ---------------------------------------------------------------- fingerprints and commands */

const fpDoc = (d) => ({ id: d.id, kind: d.kind, code: d.code || "", created_at: d.created_at });
const fpProduct = (p) => ({ id: p.id, code: p.code, created_at: p.created_at });
const fpCustomer = (c) => ({ id: c.id, created_at: c.created_at });
const fpComplete = (fp) => fp && fp.id !== undefined && fp.created_at !== null && fp.created_at !== undefined && fp.created_at !== "";
const STALE_DATA = "Dữ liệu trên web chưa đủ mới (thiếu dấu nhận diện). Hãy mở app trên máy chính, bấm “Đồng bộ ngay”, rồi tải lại trang này.";

const lineOf = (p, qty, note) => ({ product_id: p.id, code: p.code, qty, note: note || "" });

async function sendCommand(kind, payload, summary, ui) {
  ui.error.textContent = ""; ui.msg.textContent = "";
  const { error } = await sb.from("web_inbox").insert({ kind, payload: { ...payload, summary } });
  if (error) { ui.error.textContent = `Không gửi được: ${error.message}`; return false; }
  ui.msg.textContent = "Đã gửi. Máy chính sẽ tự thực hiện khi app đang mở; kết quả hiện ở mục “Đã gửi” bên dưới.";
  loadSent();
  return true;
}

const formUi = (prefix) => ({ msg: $(`${prefix}-msg`), error: $(`${prefix}-error`) });

/** Product + quantity rows shared by the transfer, trial-use and goods-in forms. */
function addLineRow(prefix, withNote) {
  const row = document.createElement("div");
  row.className = "line" + (withNote ? "" : " count");
  row.innerHTML = `<input class="${prefix}-product" list="products-dl" placeholder="Gõ mã hoặc tên hàng…">` +
    `<input class="${prefix}-qty" inputmode="decimal" placeholder="SL">` +
    (withNote ? `<input class="${prefix}-lnote" placeholder="Ghi chú">` : "") +
    `<button class="flat" title="Xoá dòng">✕</button>`;
  row.querySelector("button").addEventListener("click", () => row.remove());
  $(`${prefix}-lines`).append(row);
}

/** -> { lines, error } from the rows of a form; empty rows are skipped. */
function collectLines(prefix) {
  const lines = [], seen = new Set();
  for (const row of $(`${prefix}-lines`).querySelectorAll(".line")) {
    const label = row.querySelector(`.${prefix}-product`).value.trim();
    const raw = row.querySelector(`.${prefix}-qty`).value.trim();
    if (!label && !raw) continue;
    const id = productLabels[label];
    if (!id) return { error: `Không nhận ra mặt hàng "${label}". Hãy chọn từ danh sách gợi ý.` };
    const qty = Number(raw.replace(",", "."));
    if (!(qty > 0)) return { error: `Số lượng của "${label}" phải lớn hơn 0.` };
    if (seen.has(id)) return { error: `Mặt hàng "${label}" bị nhập hai lần.` };
    seen.add(id);
    const note = row.querySelector(`.${prefix}-lnote`);
    lines.push(lineOf(productById[id], qty, note ? note.value.trim() : ""));
  }
  return lines.length ? { lines } : { error: "Chưa có dòng hàng nào." };
}

const placeName = (v) => (Number(v) === 2 ? "Văn phòng" : "Kho tổng");
const linesText = (lines) => lines.map((l) => `${l.code}×${fmtQty(l.qty)}`).join(", ");

/* ---------------------------------------------------------------- transfer and trial use */

async function sendTransfer() {
  const ui = formUi("tr"), fail = (m) => { ui.error.textContent = m; ui.msg.textContent = ""; };
  const from = Number($("tr-from").value), to = Number($("tr-to").value);
  if (!$("tr-date").value) return fail("Hãy chọn ngày.");
  if (from === to) return fail("Nơi chuyển đi và nơi nhận phải khác nhau.");
  const { lines, error } = collectLines("tr");
  if (error) return fail(error);
  await sendCommand("cmd_transfer", { date: $("tr-date").value, from, to, note: $("tr-note").value.trim(), lines },
    `Chuyển hàng ${placeName(from)} → ${placeName(to)}: ${linesText(lines)}`, ui);
}

async function sendTrial() {
  const ui = formUi("tu"), fail = (m) => { ui.error.textContent = m; ui.msg.textContent = ""; };
  if (!$("tu-date").value) return fail("Hãy chọn ngày.");
  const { lines, error } = collectLines("tu");
  if (error) return fail(error);
  const location = Number($("tu-loc").value);
  await sendCommand("cmd_trial", { date: $("tu-date").value, location, note: $("tu-note").value.trim(), lines },
    `Xuất dùng thử tại ${placeName(location)}: ${linesText(lines)}`, ui);
}

/* ---------------------------------------------------------------- products */

const PD_TEXT = { "pd-name-vi": "name_vi", "pd-name-zh": "name_zh", "pd-spec": "spec", "pd-variant": "variant",
                  "pd-unit": "unit", "pd-category": "category" };

function productFromLabel(text) {
  const id = productLabels[text.trim()];
  return id ? productById[id] : null;
}

function syncProductForm() {
  const action = $("pd-action").value;
  $("pd-pick-box").classList.toggle("hidden", action !== "edit");
  $("pd-fields").classList.toggle("hidden", action === "merge");
  $("pd-merge-box").classList.toggle("hidden", action !== "merge");
  $("pd-l-note").classList.toggle("hidden", action !== "edit");
  $("pd-l-active").classList.toggle("hidden", action !== "edit");
  $("pd-l-dup").classList.toggle("hidden", action !== "add");
  $("pd-send").textContent = "Gửi lệnh cho máy chính";
}

function fillProductForm(p) {
  for (const [id, key] of Object.entries(PD_TEXT)) $(id).value = p ? p[key] || "" : "";
  $("pd-note").value = p ? p.stock_note || "" : "";
  $("pd-active").checked = p ? !!p.active : true;
}

async function sendProduct() {
  const ui = formUi("pd"), fail = (m) => { ui.error.textContent = m; ui.msg.textContent = ""; };
  const action = $("pd-action").value;
  const fields = {};
  for (const [id, key] of Object.entries(PD_TEXT)) fields[key] = $(id).value.trim();
  if (action === "add") {
    if (!fields.name_vi) return fail("Mặt hàng phải có tên tiếng Việt.");
    return sendCommand("cmd_product_add", { ...fields, allow_duplicate: $("pd-dup").checked },
      `Thêm mặt hàng: ${fields.name_vi} ${fields.spec}`.trim(), ui);
  }
  if (action === "edit") {
    const p = productFromLabel($("pd-pick").value);
    if (!p) return fail("Hãy chọn mặt hàng cần sửa từ danh sách gợi ý.");
    if (!fpComplete(fpProduct(p))) return fail(STALE_DATA);
    if (!fields.name_vi) return fail("Mặt hàng phải có tên tiếng Việt.");
    return sendCommand("cmd_product_edit", { target: fpProduct(p),
      fields: { ...fields, stock_note: $("pd-note").value.trim(), active: $("pd-active").checked } },
      `Sửa mặt hàng ${p.code}${$("pd-active").checked ? "" : " (ngừng dùng)"}`, ui);
  }
  const a = productFromLabel($("pd-a").value), b = productFromLabel($("pd-b").value);
  if (!a || !b) return fail("Hãy chọn hai mặt hàng từ danh sách gợi ý.");
  if (a.id === b.id) return fail("Chọn hai mặt hàng khác nhau để gộp.");
  if (!fpComplete(fpProduct(a)) || !fpComplete(fpProduct(b))) return fail(STALE_DATA);
  if (!confirm(`Gộp ${a.code} và ${b.code}? Mã lớn hơn sẽ được gộp vào mã nhỏ hơn và biến mất.`)) return;
  await sendCommand("cmd_product_merge", { a: fpProduct(a), b: fpProduct(b) }, `Gộp ${a.code} với ${b.code}`, ui);
}

/* ---------------------------------------------------------------- customers */

function renderCustomerPicker() {
  const needle = $("cm-filter").value;
  const checked = new Set(Array.from($("cm-list").querySelectorAll("input:checked"), (i) => i.value));
  $("cm-list").innerHTML = data.customers.slice().sort((a, b) => a.name.localeCompare(b.name, "vi"))
    .filter((c) => !needle || matches(needle, `${c.name} ${c.phone} ${c.contact}`) || checked.has(String(c.id)))
    .map((c) => `<label><input type="checkbox" value="${c.id}" ${checked.has(String(c.id)) ? "checked" : ""}>` +
                `${esc(c.name)} <span class="hint">${esc(c.phone)}</span></label>`).join("");
}

async function sendCustomerMerge() {
  const ui = formUi("cm"), fail = (m) => { ui.error.textContent = m; ui.msg.textContent = ""; };
  const picked = Array.from($("cm-list").querySelectorAll("input:checked"), (i) => customerById[Number(i.value)]);
  const name = $("cm-name").value.trim();
  if (picked.length < 2) return fail("Chọn từ 2 khách hàng trở lên.");
  if (!name) return fail("Hãy nhập tên khách sau khi gộp.");
  if (!picked.every((c) => fpComplete(fpCustomer(c)))) return fail(STALE_DATA);
  if (!confirm(`Gộp ${picked.length} khách thành “${name}”? Các khách khác sẽ biến mất, phiếu của họ chuyển sang khách này.`)) return;
  if (await sendCommand("cmd_customer_merge", { targets: picked.map(fpCustomer), name },
      `Gộp ${picked.length} khách hàng thành “${name}”`, ui)) {
    $("cm-name").value = "";
  }
}

/* ---------------------------------------------------------------- goods in: source kinds and edit mode */

function syncReceiptKind() {
  const ret = $("rc-kind").value === "return";
  $("rc-l-source").classList.toggle("hidden", ret);
  $("rc-l-customer").classList.toggle("hidden", !ret);
  $("rc-l-ref").classList.toggle("hidden", !ret);
}

function startReceiptEdit(doc) {
  if (!fpComplete(fpDoc(doc))) { alert(STALE_DATA); return; }
  receiptEdit = { doc, fp: fpDoc(doc) };
  $("rc-title").textContent = `Sửa phiếu hàng về ${doc.code}`;
  $("rc-editing").textContent = "Gửi lệnh sửa: máy chính thay phiếu cũ bằng phiếu này (giữ nguyên mã phiếu, phiếu cũ vẫn lưu lại).";
  for (const id of ["rc-editing", "rc-cancel-edit"]) $(id).classList.remove("hidden");
  $("rc-send").textContent = "Gửi lệnh sửa phiếu";
  $("rc-date").value = doc.doc_date;
  $("rc-kind").value = doc.receipt_source === "return" ? "return" : "supplier";
  $("rc-source").value = doc.supplier_name || "";
  $("rc-customer").value = doc.customer_id ? String(doc.customer_id) : "";
  $("rc-ref").value = doc.ref_code || "";
  $("rc-loc").value = String(doc.location_id || 1);
  $("rc-note").value = doc.note || "";
  syncReceiptKind();
  $("rc-lines").innerHTML = "";
  for (const l of (linesByDoc[doc.id] || []).slice().sort((a, b) => a.line_no - b.line_no)) {
    addLine();
    const row = $("rc-lines").lastElementChild, p = productById[l.product_id];
    row.querySelector(".rc-product").value = p ? productLabel(p) : "";
    row.querySelector(".rc-qty").value = String(l.qty);
    row.querySelector(".rc-lnote").value = l.note || "";
  }
  goSend("receipt");
}

function stopReceiptEdit() {
  receiptEdit = null;
  $("rc-title").textContent = "Gửi phiếu hàng về";
  for (const id of ["rc-editing", "rc-cancel-edit"]) $(id).classList.add("hidden");
  $("rc-send").textContent = "Gửi lên máy chính";
  $("rc-lines").innerHTML = ""; addLine(); addLine(); addLine();
  $("rc-note").value = ""; $("rc-ref").value = "";
}

/** Called by sendReceipt (app.js) when the form is in edit mode. */
async function sendReceiptEdit(payload) {
  const ui = { msg: $("rc-msg"), error: $("rc-error") };
  const ok = await sendCommand("cmd_receipt_edit", { target: receiptEdit.fp, receipt: payload },
    `Sửa phiếu hàng về ${receiptEdit.doc.code}`, ui);
  if (ok) stopReceiptEdit();
}

/* ---------------------------------------------------------------- actions on a document and a product */

function ownerActionsHtml(d) {
  if (!isOwner()) return "";
  const parts = [];
  if (d.status === "active") parts.push(`<button class="flat danger" data-act="cancel">Huỷ phiếu này</button>`);
  if (d.kind === "delivery" || d.kind === "receipt") {
    parts.push(`<select data-act-place><option value="1">Kho tổng</option><option value="2">Văn phòng</option></select>` +
               `<button class="flat" data-act="place">Đặt nơi ${d.kind === "delivery" ? "lấy" : "nhập"} hàng</button>`);
  }
  if (d.kind === "receipt" && d.status === "active") parts.push(`<button class="flat" data-act="edit">Sửa phiếu hàng về</button>`);
  return parts.length ? `<div class="actions">${parts.join("")}<span class="hint" data-act-msg></span></div>` : "";
}

function bindOrderActions(container, doc) {
  const box = container.querySelector(".actions");
  if (!box) return;
  const say = (text) => { box.querySelector("[data-act-msg]").textContent = text; };
  const ui = { msg: { set textContent(v) { if (v) say(v); } }, error: { set textContent(v) { if (v) say(v); } } };
  const place = box.querySelector("[data-act-place]");
  if (place && doc.location_id) place.value = String(doc.location_id);
  box.addEventListener("click", async (event) => {
    event.stopPropagation();
    const act = event.target.dataset ? event.target.dataset.act : null;
    if (!act) return;
    if (!fpComplete(fpDoc(doc))) { say(STALE_DATA); return; }
    if (act === "cancel") {
      if (!confirm(`Huỷ phiếu ${doc.code || ""}? Tồn kho sẽ được hoàn lại (phiếu vẫn lưu lại, đánh dấu đã huỷ).`)) return;
      await sendCommand("cmd_cancel_doc", { target: fpDoc(doc) }, `Huỷ phiếu ${doc.code}`, ui);
    } else if (act === "place") {
      await sendCommand("cmd_set_location", { target: fpDoc(doc), location: Number(place.value) },
        `Đặt nơi ${doc.kind === "delivery" ? "lấy" : "nhập"} hàng của phiếu ${doc.code} = ${placeName(place.value)}`, ui);
    } else if (act === "edit") {
      startReceiptEdit(doc);
    }
  });
}

function addProductActions(box, p) {
  if (!isOwner()) return;
  const bar = document.createElement("div");
  bar.className = "actions";
  bar.innerHTML = `<button class="flat" data-act="edit">Sửa / ngừng dùng mặt hàng này</button>`;
  bar.querySelector("button").addEventListener("click", () => {
    goSend("product");
    $("pd-action").value = "edit"; syncProductForm();
    $("pd-pick").value = productLabel(p);
    fillProductForm(p);
  });
  box.querySelector(".backbar").after(bar);
}

/* ---------------------------------------------------------------- navigation and start */

function goSend(kind) {
  document.querySelector('.tab[data-tab="send"]').click();
  const chip = document.querySelector(`#send-kinds .chip[data-send="${kind}"]`);
  if (chip) chip.click();
}

function initOwnerMode() {
  if (!isOwner()) return;
  document.querySelectorAll(".chip.owner").forEach((c) => c.classList.remove("hidden"));
  $("send-tab").textContent = "Thao tác";
  $("owner-banner").classList.remove("hidden");
  $("staff-banner").classList.add("hidden");
  const today = todayLocal();
  for (const id of ["tr-date", "tu-date"]) $(id).value = today;
  for (const prefix of ["tr", "tu"]) if (!$(`${prefix}-lines`).children.length) { addLineRow(prefix, true); addLineRow(prefix, true); addLineRow(prefix, true); }
  $("categories-dl").innerHTML = [...new Set(data.products.map((p) => p.category).filter(Boolean))]
    .map((c) => `<option value="${esc(c)}">`).join("");
  syncProductForm(); fillProductForm(null);
  renderCustomerPicker();
}

function initReceiptCustomers() {
  $("rc-customer").innerHTML = `<option value="">— chọn khách —</option>` + data.customers.slice()
    .sort((a, b) => a.name.localeCompare(b.name, "vi")).map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  syncReceiptKind();
}

$("tr-add").addEventListener("click", () => addLineRow("tr", true));
$("tu-add").addEventListener("click", () => addLineRow("tu", true));
$("tr-send").addEventListener("click", sendTransfer);
$("tu-send").addEventListener("click", sendTrial);
$("pd-action").addEventListener("change", () => { syncProductForm(); fillProductForm(null); $("pd-pick").value = ""; });
$("pd-pick").addEventListener("change", () => { const p = productFromLabel($("pd-pick").value); if (p) fillProductForm(p); });
$("pd-send").addEventListener("click", sendProduct);
$("cm-filter").addEventListener("input", renderCustomerPicker);
$("cm-send").addEventListener("click", sendCustomerMerge);
$("rc-kind").addEventListener("change", syncReceiptKind);
$("rc-cancel-edit").addEventListener("click", stopReceiptEdit);
