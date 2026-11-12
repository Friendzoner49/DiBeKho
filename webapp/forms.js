/* DiBeKho web: the windows that write, laid out like the app's own (Nhập hàng về, Chuyển hàng, Xuất dùng thử,
   Kiểm kê, Sửa mặt hàng, Gộp…). The owner writes the shared data at once through cloud/supabase/009_web_rpc.sql
   (each function tested against the app's core in tests/test_cloud_web_rpc.py); staff send a request to web_inbox
   that the owner approves in the app (Cần xử lý). */

"use strict";

/* ---------------------------------------------------------------- the dialog window */

const dlg = $("dlg");

/** Open the window. buttons: [{label, primary?, run: async () => close?}]; a run that throws shows its message. */
function openDialog(title, html, buttons, closeLabel = "Huỷ bỏ") {
  $("dlg-title").textContent = title;
  $("dlg-body").innerHTML = html;
  $("dlg-error").textContent = "";
  const bar = $("dlg-buttons");
  bar.innerHTML = "";
  dlg.dataset.form = closeLabel === "Huỷ bỏ" && buttons.length ? "1" : "";
  for (const b of [...buttons, { label: buttons.length ? closeLabel : "Đóng", close: true, run: async () => true }]) {
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

/** A form with something typed in asks before closing, like the app (receipt_form.confirm_close). */
function dirtyForm() {
  return [...$("dlg-body").querySelectorAll("input.qty, input.rf-product")].some((i) => i.value.trim() !== "");
}

function closeDialog() {
  if (dlg.dataset.form && dirtyForm() && !confirm("Bỏ phiếu đang nhập? Những gì đã gõ sẽ không được lưu.")) return false;
  dlg.close();
  return true;
}

$("dlg-x").addEventListener("click", closeDialog);
dlg.addEventListener("cancel", (e) => { e.preventDefault(); closeDialog(); });  // the Esc key

function fail(message) { throw new Error(message); }

/** The owner's write: the function answers with the new state, then the page reloads everything. */
async function rpcWrite(fn, args) {
  const { data: answer, error } = await sb.rpc(fn, args);
  if (error) fail(error.message || "Không lưu được (lỗi không rõ). Hãy tải lại trang rồi thử lại.");
  await loadAll();
  return answer || {};
}

/** A button outside a dialog: show what went wrong in a message box, like the app. */
async function ownerAction(work) {
  try {
    await work();
  } catch (e) {
    alert(e.message || String(e));
  }
}

async function sendRequest(kind, payload) {
  const { error } = await sb.from("web_inbox").insert({ kind, payload });
  if (error) fail(`Không gửi được: ${error.message}`);
  loadInbox();
}

const placeOptions = (v) => `<option value="1" ${Number(v) !== 2 ? "selected" : ""}>Kho tổng</option>` +
                            `<option value="2" ${Number(v) === 2 ? "selected" : ""}>Văn phòng</option>`;

/* ---------------------------------------------------------------- Chi tiết đơn */

function showOrder(id) {
  const d = docById[id];
  if (!d) return;
  const title = `${KIND_VI[d.kind] || d.kind} ${d.code || ""}`.trim();
  const buttons = [];
  let html = orderDetailHtml(d);
  if (isOwner()) {
    if ((d.kind === "delivery" || d.kind === "receipt") && d.status === "active") {
      html += `<div class="row"><label>${d.kind === "delivery" ? "Lấy hàng từ" : "Nhập vào"} ` +
              `<select id="od-place">${placeOptions(d.location_id)}</select></label>` +
              `<button id="od-place-save">Lưu nơi ${d.kind === "delivery" ? "lấy" : "nhập"} hàng</button></div>`;
    }
    if (d.kind === "receipt" && d.status === "active") buttons.push({ label: "Sửa phiếu hàng về…", run: async () => { receiptForm(d); return false; } });
    if (d.kind === "transfer" && d.status === "active") buttons.push({ label: "Sửa phiếu…", run: async () => { transferForm(d); return false; } });
    if (d.status === "active") {
      buttons.push({ label: "Huỷ phiếu", run: async () => {
        if (!confirm(`Huỷ phiếu ${d.code || ""}? Tồn kho sẽ được hoàn lại (phiếu vẫn lưu lại, đánh dấu đã huỷ).`)) return false;
        await rpcWrite("web_cancel", { p_doc: d.id });
        alert(`Đã huỷ phiếu ${d.code || ""}.`);
        return true;
      } });
    }
  }
  openDialog(title, html, buttons, "Đóng");  // never "Huỷ bỏ" next to "Huỷ phiếu"
  const save = $("od-place-save");
  if (save) {
    save.addEventListener("click", async () => {
      $("dlg-error").textContent = "";
      try {
        await rpcWrite("web_set_location", { p_doc: d.id, p_location: Number($("od-place").value) });
        showOrder(d.id);
      } catch (e) { $("dlg-error").textContent = e.message; }
    });
  }
}

/* ---------------------------------------------------------------- Nhập hàng về (receipt_form) */

function receiptRow(product, qty, note) {
  return `<tr><td><input class="rf-product" list="products-dl" placeholder="— Gõ mã hoặc tên hàng —" value="${esc(product ? productLabel(product) : "")}"></td>` +
    `<td class="rf-spec">${esc(product ? product.spec : "")}</td><td class="rf-unit">${esc(product ? product.unit : "")}</td>` +
    `<td><input class="rf-qty qty" inputmode="decimal" value="${esc(qty ?? "")}"></td>` +
    `<td><input class="rf-note" value="${esc(note || "")}"></td><td><button class="flat rf-del" title="Xoá dòng này">✕</button></td></tr>`;
}

function receiptForm(edit) {
  const lines = edit ? (linesByDoc[edit.id] || []).slice().sort((a, b) => a.line_no - b.line_no) : [];
  const ret = edit && edit.receipt_source === "return";
  const customers = data.customers.slice().sort((a, b) => a.name.localeCompare(b.name, "vi"));
  const body = openDialog(edit ? `Sửa phiếu hàng về ${edit.code}` : "Nhập hàng về",
    `<p class="step">1. Hàng từ đâu về?</p>
     <div class="row"><label class="check big"><input type="radio" name="rf-src" value="supplier" ${ret ? "" : "checked"}> Cửa khẩu / công ty mẹ</label>
       <label class="check big"><input type="radio" name="rf-src" value="return" ${ret ? "checked" : ""}> Khách hàng trả lại</label></div>
     <p class="hint">Chỉ dùng cho hàng thật sự về kho. Muốn sửa số tồn bị sai, hãy dùng Kiểm kê.</p>
     <div class="form2">
       <label>Ngày về:</label><input id="rf-date" type="date" value="${esc(edit ? edit.doc_date : todayLocal())}">
       <label>Nhập vào:</label><select id="rf-loc">${placeOptions(edit ? edit.location_id : 1)}</select>
       <label class="rf-sup">Nhà cung cấp:</label><input class="rf-sup" id="rf-supplier" list="suppliers-dl"
         placeholder="Gõ tên hoặc chọn tên đã dùng (ví dụ: Cửa khẩu Lạng Sơn)" value="${esc(edit ? edit.supplier_name : "")}">
       <label class="rf-ret">Khách hàng:</label><select class="rf-ret" id="rf-customer"><option value="">— Chọn khách trong danh sách —</option>
         ${customers.map((c) => `<option value="${esc(c.id)}" ${edit && edit.customer_id === c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select>
       <label class="rf-ret">Đơn:</label><input class="rf-ret" id="rf-ref" placeholder="Mã đơn khách trả (không bắt buộc)" value="${esc(edit ? edit.ref_code : "")}">
       <label>Ghi chú:</label><input id="rf-note" value="${esc(edit ? edit.note : "")}">
     </div>
     <p class="step">2. Hàng về những gì?</p>
     <p class="hint">Gõ mã hoặc tên rồi chọn trong danh sách gợi ý. Dòng không gõ số lượng sẽ được bỏ qua. Mặt hàng mới: thêm ở Cài đặt → Danh mục mặt hàng trước.</p>
     <div class="scroll"><table class="edit"><thead><tr><th>Mặt hàng</th><th>Quy cách</th><th>Đơn vị</th><th>Số lượng</th><th>Ghi chú</th><th></th></tr></thead>
       <tbody id="rf-lines">${(lines.length ? lines.map((l) => receiptRow(productById[l.product_id], fmtQty(l.qty), l.note))
                                            : [1, 2, 3].map(() => receiptRow(null))).join("")}</tbody></table></div>
     <div class="row"><button id="rf-add">＋ Thêm dòng</button><span class="spacer"></span><span id="rf-sum" class="hint"></span></div>`,
    [{ label: edit ? "Lưu phiếu đã sửa" : "Lưu phiếu hàng về", primary: true, run: () => saveReceipt(edit) }]);
  const sync = () => {
    const r = body.querySelector('input[name="rf-src"]:checked').value === "return";
    body.querySelectorAll(".rf-sup").forEach((e) => e.classList.toggle("hidden", r));
    body.querySelectorAll(".rf-ret").forEach((e) => e.classList.toggle("hidden", !r));
  };
  const summary = () => {
    const rows = collectReceiptLines(true);
    $("rf-sum").textContent = `Sẽ ghi ${rows.length} mặt hàng · tổng ${fmtQty(rows.reduce((a, l) => a + l.qty, 0))}`;
  };
  body.querySelectorAll('input[name="rf-src"]').forEach((r) => r.addEventListener("change", sync));
  body.addEventListener("input", (e) => {
    if (e.target.classList.contains("rf-product")) {
      const p = productFromLabel(e.target.value), tr = e.target.closest("tr");
      tr.querySelector(".rf-spec").textContent = p ? p.spec : "";
      tr.querySelector(".rf-unit").textContent = p ? p.unit : "";
    }
    summary();
  });
  body.addEventListener("click", (e) => { if (e.target.classList.contains("rf-del")) { e.target.closest("tr").remove(); summary(); } });
  $("rf-add").addEventListener("click", () => { $("rf-lines").insertAdjacentHTML("beforeend", receiptRow(null)); });
  sync(); summary();
}

/** -> [{product, qty, note}] of the rows with a quantity; quiet: skip bad rows instead of failing. */
function collectReceiptLines(quiet) {
  const out = [], seen = new Map();
  [...$("rf-lines").querySelectorAll("tr")].forEach((tr, i) => {
    const label = tr.querySelector(".rf-product").value.trim();
    const qty = parseQty(tr.querySelector(".rf-qty").value);
    if (qty === null && !label) return;
    if (qty === null || qty === 0) return;  // no quantity: the row is skipped (like the app)
    const p = productFromLabel(label);
    if (!p) { if (quiet) return; fail(`Dòng ${i + 1}: không nhận ra mặt hàng “${label}”. Hãy chọn trong danh sách gợi ý.`); }
    if (!(qty > 0)) { if (quiet) return; fail(`Dòng ${i + 1}: số lượng phải là số lớn hơn 0.`); }
    if (seen.has(p.id)) { if (quiet) return; fail(`“${productName(p)}” có ở 2 dòng (dòng ${seen.get(p.id)} và ${i + 1}). Hãy gộp số lượng vào một dòng.`); }
    seen.set(p.id, i + 1);
    out.push({ product: p, qty, note: tr.querySelector(".rf-note").value.trim() });
  });
  return out;
}

async function saveReceipt(edit) {
  const source = document.querySelector('input[name="rf-src"]:checked').value;
  const day = $("rf-date").value;
  if (!day) fail("Hãy chọn ngày về.");
  const lines = collectReceiptLines(false);
  if (!lines.length) fail("Chưa có mặt hàng nào có số lượng.");
  const p = { doc_date: day, source, location_id: Number($("rf-loc").value), note: $("rf-note").value.trim() };
  let who;
  if (source === "supplier") {
    p.supplier_name = $("rf-supplier").value.trim();
    if (!p.supplier_name) fail("Gõ tên nhà cung cấp (cửa khẩu / công ty mẹ).");
    if (/^(kho|kho tong|van phong)$/.test(unaccent(p.supplier_name))) {
      if (!confirm(`Ô nhà cung cấp đang ghi “${p.supplier_name}”, giống tên nơi chứa hàng. Ô này là NƠI GỬI hàng tới (cửa khẩu / công ty mẹ). Vẫn lưu?`)) return false;
    }
    who = `Nhà cung cấp: ${p.supplier_name}`;
  } else {
    p.customer_id = $("rf-customer").value;
    if (!p.customer_id) fail("Chọn khách hàng trả lại hàng.");
    p.ref_code = $("rf-ref").value.trim();
    who = `Khách trả lại: ${(customerById[p.customer_id] || {}).name || ""}`;
  }
  if (day > todayLocal() && !confirm("Ngày về sau hôm nay. Vẫn lưu?")) return false;
  const total = lines.reduce((a, l) => a + l.qty, 0);
  const text = `Ngày về: ${day}\n${who}\nNhập vào: ${PLACE[p.location_id]}\n\n` +
    lines.map((l) => `• ${productName(l.product)}: ${fmtQty(l.qty)} ${l.product.unit || ""}`).join("\n") +
    `\n\nTổng: ${fmtQty(total)}\n` + (edit ? "\nPhiếu cũ sẽ được thay bằng phiếu này (phiếu cũ vẫn xem được trong lịch sử).\n" : "") +
    (isOwner() ? "\nLưu phiếu này vào kho?" : "\nGửi phiếu này cho chủ duyệt?");
  if (!confirm(text)) return false;
  if (isOwner()) {
    p.lines = lines.map((l) => ({ product_id: l.product.id, qty: l.qty, note: l.note }));
    const out = await rpcWrite("web_receipt", edit ? { p, p_replaces: edit.id } : { p });
    alert(`Đã lưu phiếu hàng về ${out.code}. File Excel của phiếu sẽ có trong app (output/hang-ve) khi app đồng bộ.`);
  } else {
    p.lines = lines.map((l) => ({ product_id: l.product.id, code: l.product.code, qty: l.qty, note: l.note }));
    await sendRequest("receipt", p);
    alert("Đã gửi. Phiếu sẽ vào sổ sau khi chủ duyệt trên app.");
  }
  return true;
}

/* ---------------------------------------------------------------- Chuyển hàng / Xuất dùng thử (a yellow column) */

/** Stock at a place, as if `editing` (a document being edited) had not happened. */
function availableAt(productId, place, editing) {
  let q = stockOf(productId)[place] || 0;
  if (editing) for (const m of data.movements) if (m.document_id === editing.id && m.product_id === productId && m.location_id === place) q -= m.qty;
  return q;
}

function qtyTable(id, availLabel, qtyLabel, preset) {
  return `<div class="scroll tall"><table class="edit"><thead><tr><th>Mã</th><th>Mặt hàng</th><th>Tên Trung</th><th>Quy cách</th>` +
    `<th>Loại / màu</th><th>Đơn vị</th><th>Nhóm hàng</th><th class="num">${esc(availLabel)}</th><th class="yellow">${esc(qtyLabel)}</th></tr></thead>` +
    `<tbody id="${id}">` + activeProducts().map((p) => `<tr data-pid="${esc(p.id)}"><td>${esc(p.code)}</td><td>${esc(p.name_vi)}</td>` +
      `<td>${esc(p.name_zh)}</td><td>${esc(p.spec)}</td><td>${esc(p.variant)}</td><td>${esc(p.unit)}</td><td>${esc(p.category)}</td>` +
      `<td class="num avail"></td><td class="yellow"><input class="qty" inputmode="decimal" value="${esc(preset[p.id] ?? "")}"></td></tr>`).join("") +
    `</tbody></table></div>`;
}

function readQtyTable(id) {
  const out = [];
  for (const tr of $(id).querySelectorAll("tr")) {
    const q = parseQty(tr.querySelector("input").value);
    if (q === null) continue;
    const p = productById[tr.dataset.pid];
    if (!(q > 0)) fail(`${p.code}: số lượng phải là số lớn hơn 0.`);
    out.push({ product: p, qty: q });
  }
  if (!out.length) fail("Chưa nhập số lượng nào (số phải lớn hơn 0).");
  return out;
}

function transferForm(edit) {
  const preset = {};
  if (edit) for (const l of linesByDoc[edit.id] || []) preset[l.product_id] = fmtQty(l.qty);
  const body = openDialog(edit ? `Sửa phiếu chuyển hàng ${edit.code}` : "Chuyển hàng giữa Kho tổng và Văn phòng",
    `<p class="hint">Mang hàng giữa Kho tổng và Văn phòng: gõ số lượng vào cột vàng. Tổng tồn không đổi, chỉ đổi số ở từng nơi. Huỷ phiếu được nếu nhầm.</p>
     <div class="form2"><label>Ngày chuyển:</label><input id="tf-date" type="date" value="${esc(edit ? edit.doc_date : todayLocal())}">
       <label>Chuyển từ:</label><select id="tf-from">${placeOptions(edit ? edit.location_id : 1)}</select>
       <label>Chuyển đến:</label><select id="tf-to">${placeOptions(edit ? edit.to_location_id : 2)}</select>
       <label>Ghi chú:</label><input id="tf-note" value="${esc(edit ? edit.note : "")}"></div>` +
    qtyTable("tf-lines", "Đang có ở nơi chuyển đi", "Số lượng chuyển", preset),
    [{ label: "Lưu phiếu chuyển", primary: true, run: async () => {
      const from = Number($("tf-from").value), to = Number($("tf-to").value);
      if (from === to) fail("Nơi chuyển đi và nơi nhận phải khác nhau.");
      if (!$("tf-date").value) fail("Hãy chọn ngày chuyển.");
      const lines = readQtyTable("tf-lines");
      const short = lines.filter((l) => availableAt(l.product.id, from, edit) < l.qty).map((l) => l.product.code);
      const text = `Chuyển từ ${PLACE[from]} sang ${PLACE[to]}:\n\n` + lines.map((l) => `• ${productName(l.product)}: ${fmtQty(l.qty)}`).join("\n") +
        "\n\nTổng tồn không đổi. Lưu phiếu chuyển hàng?" +
        (short.length ? `\n\nLưu ý: ${PLACE[from]} theo app không đủ hàng cho: ${short.join(", ")}. Vẫn lưu được (số ở ${PLACE[from]} sẽ âm cho tới khi kiểm kê).` : "");
      if (!confirm(text)) return false;
      await rpcWrite("web_transfer", { p: { date: $("tf-date").value, from, to, note: $("tf-note").value.trim(),
        lines: lines.map((l) => ({ product_id: l.product.id, qty: l.qty })) }, ...(edit ? { p_replaces: edit.id } : {}) });
      alert("Đã lưu phiếu chuyển hàng.");
      return true;
    } }]);
  const fill = () => {
    const from = Number($("tf-from").value);
    for (const tr of body.querySelectorAll("#tf-lines tr")) tr.querySelector(".avail").textContent = fmtQty(availableAt(tr.dataset.pid, from, edit));
  };
  $("tf-from").addEventListener("change", fill);
  fill();
}

function trialForm() {
  const body = openDialog("Xuất hàng dùng thử",
    `<p class="hint">Hàng mở ra dùng/thử nghiệm, không bán cho khách: gõ số lượng vào cột vàng. Tồn sẽ giảm đúng ở nơi đã chọn. Nhầm thì Huỷ phiếu rồi làm lại.</p>
     <div class="form2"><label>Ngày xuất:</label><input id="tu-date" type="date" value="${esc(todayLocal())}">
       <label>Nơi xuất:</label><select id="tu-loc">${placeOptions(1)}</select>
       <label>Ghi chú:</label><input id="tu-note"></div>` +
    qtyTable("tu-lines", "Đang có ở nơi này", "Số lượng dùng thử", {}),
    [{ label: "Lưu phiếu dùng thử", primary: true, run: async () => {
      const place = Number($("tu-loc").value);
      if (!$("tu-date").value) fail("Hãy chọn ngày xuất.");
      const lines = readQtyTable("tu-lines");
      const short = lines.filter((l) => availableAt(l.product.id, place) < l.qty).map((l) => l.product.code);
      const text = `Xuất dùng thử tại ${PLACE[place]}:\n\n` + lines.map((l) => `• ${productName(l.product)}: ${fmtQty(l.qty)}`).join("\n") +
        "\n\nTồn sẽ giảm theo số lượng này. Lưu phiếu dùng thử?" +
        (short.length ? `\n\nLưu ý: ${PLACE[place]} theo app không đủ hàng cho: ${short.join(", ")}. Vẫn lưu được (số ở ${PLACE[place]} sẽ âm cho tới khi kiểm kê).` : "");
      if (!confirm(text)) return false;
      await rpcWrite("web_trial", { p: { date: $("tu-date").value, location: place, note: $("tu-note").value.trim(),
        lines: lines.map((l) => ({ product_id: l.product.id, qty: l.qty })) } });
      alert("Đã lưu phiếu dùng thử.");
      return true;
    } }]);
  const fill = () => {
    const place = Number($("tu-loc").value);
    for (const tr of body.querySelectorAll("#tu-lines tr")) tr.querySelector(".avail").textContent = fmtQty(availableAt(tr.dataset.pid, place));
  };
  $("tu-loc").addEventListener("change", fill);
  fill();
}

/** Phiếu chuyển hàng… / Phiếu dùng thử… / Phiếu kiểm kê… (the app's lists inside Kiểm kê). */
function docListWindow(kind) {
  const title = { transfer: "Phiếu chuyển hàng", trial: "Phiếu dùng thử", stock_count: "Phiếu kiểm kê" }[kind];
  const items = data.documents.filter((d) => d.kind === kind)
    .sort((a, b) => b.doc_date.localeCompare(a.doc_date) || String(b.created_at).localeCompare(String(a.created_at)));
  openDialog(title, `<p class="hint">Nháy đúp một phiếu để xem chi tiết${isOwner() ? " (huỷ hoặc sửa phiếu ở đó)" : ""}.</p><div id="dl-table"></div>`, []);
  buildTable("dl-table", [
    { label: "Ngày", get: (d) => d.doc_date }, { label: "Mã", get: (d) => d.code },
    { label: "Nơi", get: placeOf },
    { label: "Mặt hàng", get: (d) => (linesByDoc[d.id] || []).map((l) => `${(productById[l.product_id] || {}).code || "?"}×${fmtQty(l.qty)}`).join(", ") },
    { label: "Trạng thái", get: (d) => STATUS_VI[d.status] ?? d.status }, { label: "Ghi chú", get: (d) => d.note },
  ], items, { select: "one", open: (d) => showOrder(d.id), rowClass: (d) => (d.status !== "active" ? "closed" : ""), empty: "Chưa có phiếu nào." });
}

/* ---------------------------------------------------------------- Kiểm kê (the page itself) */

const countTyped = {};  // product id -> {1: text, 2: text}, kept while the page is re-drawn after a reload

function renderCount() {
  if (!$("count-date").value) $("count-date").value = todayLocal();
  const writer = isOwner() || isStaff();
  const items = activeProducts();
  const cell = (p, place) => writer
    ? `<input class="qty" inputmode="decimal" data-count="${esc(p.id)}" data-place="${place}" value="${esc((countTyped[p.id] || {})[place] || "")}">`
    : "";
  buildTable("count-table", [
    { label: "Mã", get: (p) => p.code }, { label: "Mặt hàng", get: (p) => p.name_vi }, { label: "Tên Trung", get: (p) => p.name_zh },
    { label: "Quy cách", get: (p) => p.spec }, { label: "Loại / màu", get: (p) => p.variant }, { label: "Đơn vị", get: (p) => p.unit },
    { label: "Theo app Kho tổng", get: (p) => stockOf(p.id)[1], num: true, cls: "num", html: (p) => fmtQty(stockOf(p.id)[1]) },
    { label: "Theo app Văn phòng", get: (p) => stockOf(p.id)[2], num: true, cls: "num", html: (p) => fmtQty(stockOf(p.id)[2]) },
    { label: "Tồn theo app", get: (p) => stockOf(p.id).total, num: true, cls: "num", html: (p) => fmtQty(stockOf(p.id).total) },
    { label: "Đếm được Kho tổng", get: () => "", cls: "yellow", html: (p) => cell(p, 1) },
    { label: "Đếm được Văn phòng", get: () => "", cls: "yellow", html: (p) => cell(p, 2) },
    { label: "Ghi chú tồn kho", get: (p) => p.stock_note },
  ], items, {});
  countSummary();
}

function countSummary() {
  const total = activeProducts().length;
  const counted = Object.values(countTyped).filter((v) => (v[1] || "").trim() || (v[2] || "").trim()).length;
  $("count-summary").textContent = `Đã nhập ${counted}/${total} mặt hàng`;
}

$("count-table").addEventListener("input", (e) => {
  const el = e.target;
  if (!el.dataset.count) return;
  (countTyped[el.dataset.count] ||= {})[el.dataset.place] = el.value;
  countSummary();
});

async function saveCount() {
  $("count-msg").textContent = "";
  const day = $("count-date").value;
  if (!day) fail("Hãy chọn ngày kiểm kê.");
  if (day > todayLocal()) fail("Ngày kiểm kê không được ở tương lai.");
  const lines = [];
  for (const [pid, v] of Object.entries(countTyped)) {
    const p = productById[pid];
    if (!p) continue;
    for (const place of [1, 2]) {
      const q = parseQty(v[place]);
      if (q === null) continue;
      if (!(q >= 0)) fail(`${p.code}: số đếm không hợp lệ (phải là số từ 0 trở lên).`);
      lines.push({ product: p, place, qty: q });
    }
  }
  if (!lines.length) fail("Chưa nhập số đếm nào.");
  const products = new Set(lines.map((l) => l.product.id)).size;
  if (!confirm(`Lưu kiểm kê ${products} mặt hàng ngày ${day}? Tồn sẽ được chỉnh theo số đếm.`)) return;
  const note = $("count-note").value.trim();
  if (isOwner()) {
    await rpcWrite("web_stock_count", { p: { count_date: day, note,
      lines: lines.map((l) => ({ product_id: l.product.id, location_id: l.place, qty: l.qty })) } });
    $("count-msg").textContent = "Đã lưu kiểm kê.";
  } else {
    for (const place of [1, 2]) {  // a staff request counts one place (the app's approval window)
      const part = lines.filter((l) => l.place === place);
      if (part.length) {
        await sendRequest("stock_count", { count_date: day, location_id: place, note,
          lines: part.map((l) => ({ product_id: l.product.id, code: l.product.code, qty: l.qty })) });
      }
    }
    $("count-msg").textContent = "Đã gửi. Kiểm kê sẽ vào sổ sau khi chủ duyệt trên app.";
  }
  for (const k of Object.keys(countTyped)) delete countTyped[k];
  $("count-note").value = "";
  renderCount();
}

/* ---------------------------------------------------------------- mặt hàng / khách hàng */

function productForm(p) {
  openDialog(p ? `Sửa mặt hàng ${p.code}` : "Thêm mặt hàng",
    `<div class="form2">
       <label>Tên tiếng Việt:</label><input id="pf-name_vi" value="${esc(p ? p.name_vi : "")}">
       <label>Tên tiếng Trung:</label><input id="pf-name_zh" value="${esc(p ? p.name_zh : "")}">
       <label>Quy cách:</label><input id="pf-spec" value="${esc(p ? p.spec : "")}">
       <label>Loại / màu:</label><input id="pf-variant" value="${esc(p ? p.variant : "")}">
       <label>Đơn vị:</label><input id="pf-unit" value="${esc(p ? p.unit : "")}" placeholder="${p ? "" : "để trống: lấy theo quy cách (vd. 20kg/Thùng → thùng)"}">
       <label>Nhóm hàng:</label><input id="pf-category" list="categories-dl" value="${esc(p ? p.category : "")}">
       ${p ? `<label>Ghi chú tồn kho:</label><input id="pf-stock_note" value="${esc(p.stock_note)}">
              <span></span><label class="check"><input id="pf-active" type="checkbox" ${p.active ? "checked" : ""}> Đang dùng (bỏ chọn = ngừng dùng)</label>` : ""}
     </div>`,
    [{ label: p ? "Lưu" : "Thêm mặt hàng", primary: true, run: async () => {
      const fields = {};
      for (const k of ["name_vi", "name_zh", "spec", "variant", "unit", "category", ...(p ? ["stock_note"] : [])]) fields[k] = $(`pf-${k}`).value.trim();
      if (!fields.name_vi) fail("Mặt hàng phải có tên tiếng Việt.");
      if (p) {
        fields.active = $("pf-active").checked;
        await rpcWrite("web_product_edit", { p_id: p.id, p: fields });
        alert(`Đã lưu mặt hàng ${p.code}.`);
        return true;
      }
      let out;
      try {
        out = await rpcWrite("web_product_add", { p: fields });
      } catch (e) {
        if (!/Đã có mặt hàng/.test(e.message) || !confirm(`${e.message.split(" Nếu")[0]}\n\nVẫn tạo mặt hàng mới?`)) throw e;
        out = await rpcWrite("web_product_add", { p: { ...fields, allow_duplicate: true } });
      }
      alert(`Đã thêm mặt hàng ${out.code}.`);
      return true;
    } }]);
}

function mergeProductsWindow(first) {
  const others = data.products.filter((x) => x.id !== first.id).sort((a, b) => a.code.localeCompare(b.code, "vi", { numeric: true }));
  openDialog("Chọn mặt hàng trùng còn lại",
    `<p class="hint">Đã chọn: <b>${esc(first.code)} · ${esc(productName(first))}</b>. Bấm chọn mặt hàng trùng với nó rồi bấm Gộp.</p><div id="mg-table"></div>`,
    [{ label: "Gộp", primary: true, run: async () => {
      const [otherId] = selected("mg-table");
      const other = productById[otherId];
      if (!other) fail("Hãy bấm chọn mặt hàng trùng còn lại trong danh sách.");
      const num = (c) => (/^SP\d+$/.test(c) ? Number(c.slice(2)) : -1);
      const [keep, drop] = num(first.code) <= num(other.code) ? [first, other] : [other, first];
      if (!confirm(`Gộp 2 mặt hàng này thành 1?\n\nGiữ lại: ${keep.code} · ${productName(keep)}\nBỏ đi: ${drop.code} · ${productName(drop)}\n\n` +
                   "Mọi phiếu, số tồn và tên đã học của mặt hàng bỏ đi sẽ chuyển sang mặt hàng giữ lại.")) return false;
      const out = await rpcWrite("web_product_merge", { p_a: first.id, p_b: other.id });
      alert(`Đã gộp ${out.dropped} vào ${out.code}.`);
      return true;
    } }]);
  buildTable("mg-table", [
    { label: "Mã", get: (x) => x.code }, { label: "Mặt hàng", get: productName }, { label: "Tên Trung", get: (x) => x.name_zh },
    { label: "Nhóm hàng", get: (x) => x.category }, { label: "Tồn", get: (x) => stockOf(x.id).total, num: true, cls: "num" },
  ], others, { select: "one" });
}

function mergeCustomersWindow() {
  const picked = selected("customers-table").map((id) => customerById[id]).filter(Boolean);
  if (picked.length < 2) { alert("Bấm chọn từ 2 khách hàng trở lên trong bảng (bấm lần nữa để bỏ chọn), rồi bấm Gộp khách hàng…."); return; }
  openDialog("Gộp khách hàng",
    `<p>Gộp ${picked.length} khách hàng:</p><ul>${picked.map((c) => `<li>${esc(c.name)} <span class="hint">${esc(c.phone)}</span></li>`).join("")}</ul>
     <div class="form2"><label>Tên khách hàng chung:</label><input id="cm-name" value="${esc(picked[0].name)}"></div>
     <p class="hint">Mọi phiếu của các khách này chuyển sang một khách mang tên trên.</p>`,
    [{ label: "Gộp khách hàng", primary: true, run: async () => {
      const name = $("cm-name").value.trim();
      if (!name) fail("Hãy nhập tên khách hàng chung.");
      await rpcWrite("web_customer_merge", { p_ids: picked.map((c) => c.id), p_name: name });
      alert(`Đã gộp ${picked.length} khách hàng thành “${name}”.`);
      return true;
    } }]);
}

/* ---------------------------------------------------------------- phiếu giao hàng: file Excel (staff and owner) */

const XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const MAX_FILE = 2 * 1024 * 1024;  // same limit as the bucket and the app's check

function deliveryFileWindow() {
  openDialog("Gửi phiếu giao hàng (file Excel)",
    `<p class="hint">Chọn file Excel phiếu giao hàng (.xlsx, tối đa 2 MB), đúng file đang dùng. App trên máy tính sẽ đọc như mọi phiếu khác${isOwner() ? "" : " sau khi chủ duyệt"}.</p>
     <div class="form2"><label>File phiếu:</label><input id="df-file" type="file" accept=".xlsx"><label>Ghi chú:</label><input id="df-note"></div>`,
    [{ label: "Gửi", primary: true, run: async () => {
      const file = $("df-file").files[0];
      if (!file) fail("Hãy chọn file phiếu giao hàng.");
      if (!/\.xlsx$/i.test(file.name)) fail("Chỉ nhận file Excel .xlsx. Nếu là file .xls, hãy mở bằng Excel rồi Lưu thành .xlsx.");
      if (file.size === 0) fail("File trống.");
      if (file.size > MAX_FILE) fail("File lớn hơn 2 MB.");
      const buf = await file.arrayBuffer();
      const digest = await crypto.subtle.digest("SHA-256", buf);
      const sha256 = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
      const path = `${crypto.randomUUID()}/phieu.xlsx`;  // ASCII-only key; the real name travels in the payload
      const up = await sb.storage.from("inbox-files").upload(path, buf, { contentType: XLSX_MIME, upsert: false });
      if (up.error) fail(`Không tải được file lên: ${up.error.message}`);
      await sendRequest("delivery_file", { file_path: path, file_name: file.name, size: file.size, sha256, note: $("df-note").value.trim() });
      alert("Đã gửi. Phiếu sẽ được đọc trên app" + (isOwner() ? " khi app đang mở." : " sau khi chủ duyệt."));
      return true;
    } }]);
}

/* ---------------------------------------------------------------- wiring */

$("receipt-new").addEventListener("click", () => receiptForm(null));
$("receipt-edit").addEventListener("click", () => {
  const d = docById[selected("receipts-table")[0]];
  if (!d) { alert("Hãy bấm chọn một phiếu hàng về trong bảng trước."); return; }
  if (d.status !== "active") { alert("Phiếu này đã huỷ hoặc đã được thay bằng bản sửa, không sửa được nữa."); return; }
  receiptForm(d);
});
$("count-transfer").addEventListener("click", () => transferForm(null));
$("count-trial").addEventListener("click", trialForm);
for (const b of document.querySelectorAll("[data-doclist]")) b.addEventListener("click", () => docListWindow(b.dataset.doclist));
$("count-save").addEventListener("click", () => ownerAction(saveCount));
$("count-clear").addEventListener("click", () => {
  if (!confirm("Xoá hết các số đếm đã nhập (chưa lưu)?")) return;
  for (const k of Object.keys(countTyped)) delete countTyped[k];
  renderCount();
});
$("catalog-add").addEventListener("click", () => productForm(null));
$("catalog-edit").addEventListener("click", () => {
  const p = productById[selected("catalog-table")[0]];
  if (!p) { alert("Hãy chọn một dòng trước."); return; }
  productForm(p);
});
$("catalog-merge").addEventListener("click", () => {
  const p = productById[selected("catalog-table")[0]];
  if (!p) { alert("Bấm chọn một trong hai mặt hàng trùng trong danh sách trước, rồi bấm Gộp."); return; }
  mergeProductsWindow(p);
});
$("customers-merge").addEventListener("click", mergeCustomersWindow);
$("send-delivery").addEventListener("click", deliveryFileWindow);

/* ---------------------------------------------------------------- gói dữ liệu .dibekho (package.js) */

function saveFile(name, bytes) {
  const url = URL.createObjectURL(new Blob([bytes], { type: "application/octet-stream" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 2000);
}

async function pullEverything() {
  const { data, error } = await sb.rpc("sync_pull", { p_after: 0 });
  if (error) throw new Error(`Không đọc được dữ liệu trên Cloud: ${error.message}`);
  return data;
}

function packageMessage(text) {
  $("pkg-msg").textContent = text;
}

async function exportPackageWeb() {
  packageMessage("Đang tạo gói dữ liệu…");
  try {
    const { SQL, fflate } = await DBK_PKG.loadLibs();
    const pkg = DBK_PKG.buildPackage(SQL, fflate, await pullEverything(), new Date());
    saveFile(pkg.name, pkg.bytes);
    packageMessage(`Đã tạo ${pkg.name} (${pkg.manifest.products} mặt hàng, ${pkg.manifest.deliveries} phiếu giao hàng). ` +
                   "File nằm trong thư mục Tải về của trình duyệt.");
  } catch (e) {
    packageMessage("");
    alert(`Không tạo được gói dữ liệu.\n\n${e.message || e}`);
  }
}

async function importPackageWeb(file) {
  let read = null;
  try {
    const { SQL, fflate } = await DBK_PKG.loadLibs();
    read = DBK_PKG.readPackage(SQL, fflate, new Uint8Array(await file.arrayBuffer()));
    const m = read.manifest, n = DBK_PKG.summary(read.db);
    const when = String(m.exported_at || "").replace("T", " ");
    if (!confirm(`Nhập gói dữ liệu từ ${m.device_name || "?"} (tạo lúc ${when}): ${n.products} mặt hàng, ` +
                 `${n.deliveries} phiếu giao hàng?\n\nToàn bộ dữ liệu chung trên Cloud sẽ được thay bằng gói này: trang web, ` +
                 "nhân viên và mọi máy đều thấy dữ liệu mới, mọi việc ghi sau lúc tạo gói mất đi.")) return;
    if (!confirm("Chắc chắn thay toàn bộ dữ liệu chung?\n\nTrang web sẽ tải về một bản sao dữ liệu hiện tại trước khi thay. " +
                 "Máy nào còn thay đổi chưa gửi lên Cloud nên đồng bộ xong trước.")) return;
    packageMessage("Đang sao lưu dữ liệu hiện tại…");
    const pulled = await pullEverything();
    const backup = DBK_PKG.buildPackage(SQL, fflate, pulled, new Date(), "Web-truoc-nhap");
    saveFile(backup.name, backup.bytes);
    packageMessage("Đang gửi dữ liệu lên Cloud…");
    const batch = DBK_PKG.buildBatch(read.db, pulled);
    const { data: answer, error } = await sb.rpc("sync_push",
      { p_device: "web", p_expected: Number(pulled.max_rev || 0), p_batch: batch });
    if (error) throw new Error(`${error.message}\nDữ liệu trên Cloud chưa bị đổi.`);
    if (!answer || !answer.ok) {
      throw new Error("Có máy khác hoặc người khác vừa ghi dữ liệu trong lúc nhập. Dữ liệu trên Cloud chưa bị đổi; hãy thử lại.");
    }
    packageMessage(`Đã nhập dữ liệu từ ${m.device_name || "gói"}. Bản sao trước khi nhập: ${backup.name} (thư mục Tải về).`);
    await loadAll();
  } catch (e) {
    packageMessage("");
    alert(`Nhập dữ liệu thất bại.\n\n${e.message || e}`);
  } finally {
    if (read) read.db.close();
  }
}

$("pkg-export").addEventListener("click", exportPackageWeb);
$("pkg-import").addEventListener("click", () => { $("pkg-file").value = ""; $("pkg-file").click(); });
$("pkg-file").addEventListener("change", () => { if ($("pkg-file").files[0]) importPackageWeb($("pkg-file").files[0]); });
