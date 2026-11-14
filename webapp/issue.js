/* DiBeKho web: the Phiếu xuất kho window (customer's request 14/11/2026), like the app's (ui/issue_form.py): the
   customer, then per product how many come from Kho tổng and how many from Văn phòng; the price is suggested from the
   latest order and stays editable. The web writes nothing: the window makes the Excel file (xlsx.js) and the browser
   downloads it. The stock is taken when the file goes into the app's notes folder and the app reads it, like a
   delivery note; the same file read twice is never counted twice. Prices are typed and shown in dong (the file keeps
   VND), whatever the ₫ / ¥ switch says. */

"use strict";

/** The price of this product on the customer's latest priced order, else on anyone's (core/issues.last_price; the
    app breaks a tie of dates by its row number, the web by the time the order came in). */
function lastPrice(customerName, productId) {
  if (!productId) return null;
  const name = String(customerName || "").replace(/\s+/g, " ").trim();
  let best = null, bestAny = null;
  const later = (a, b) => !b || a.d.doc_date > b.d.doc_date ||
    (a.d.doc_date === b.d.doc_date && (String(a.d.created_at) > String(b.d.created_at) ||
      (String(a.d.created_at) === String(b.d.created_at) && a.l.line_no < b.l.line_no)));
  for (const d of data.documents) {
    if (d.kind !== "delivery" || d.status !== "active") continue;
    for (const l of linesByDoc[d.id] || []) {
      if (l.product_id !== productId || l.unit_price === null || l.unit_price === undefined) continue;
      const hit = { d, l };
      if (later(hit, bestAny)) bestAny = hit;
      if (name && (customerById[d.customer_id] || {}).name === name && later(hit, best)) best = hit;
    }
  }
  return (best || bestAny) ? (best || bestAny).l.unit_price : null;
}

function issueRowHtml() {
  return `<tr class="ix-row"><td><input class="ix-product" list="products-dl" placeholder="${esc(tr("issue.pick_ph"))}"></td>` +
    `<td class="ix-spec"></td><td class="ix-unit"></td>` +
    `<td class="num ix-have" data-place="1"></td><td class="yellow"><input class="qty ix-qty" data-place="1" inputmode="decimal"></td>` +
    `<td class="num ix-have" data-place="2"></td><td class="yellow"><input class="qty ix-qty" data-place="2" inputmode="decimal"></td>` +
    `<td><input class="qty ix-price" inputmode="decimal"></td><td class="num ix-amount"></td>` +
    `<td><input class="ix-note"></td><td><button class="flat ix-remove" title="${esc(tr("issue.remove"))}">✕</button></td></tr>`;
}

function openIssueForm() {
  const heads = [tr("col.product"), tr("col.spec"), tr("col.unit"), tr("issue.have", { place: tr("place.1") }),
                 tr("issue.take", { place: tr("place.1") }), tr("issue.have", { place: tr("place.2") }),
                 tr("issue.take", { place: tr("place.2") }), tr("issue.price"), tr("issue.amount"), tr("col.note"), ""];
  const body = openDialog(tr("issue.title"),
    `<p class="hint">${esc(tr("issue.hint"))}</p>
     <div class="form2">
       <label>${esc(tr("issue.date"))}</label><input id="ix-date" type="date" value="${esc(todayLocal())}">
       <label>${esc(tr("col.customer"))}</label><input id="ix-customer" list="customers-dl" autocomplete="off" placeholder="${esc(tr("issue.customer_ph"))}">
       <label>${esc(tr("col.phone"))}</label><input id="ix-phone" autocomplete="off">
       <label>${esc(tr("col.contact"))}</label><input id="ix-contact" autocomplete="off">
       <label>${esc(tr("col.address"))}</label><input id="ix-address" autocomplete="off">
     </div>
     <div class="scroll tall"><table class="edit"><thead><tr>${heads.map((h, i) =>
       `<th class="${i === 4 || i === 6 ? "yellow" : i === 3 || i === 5 || i === 8 ? "num" : ""}">${esc(h)}</th>`).join("")}</tr></thead>
       <tbody id="ix-lines">${issueRowHtml()}${issueRowHtml()}${issueRowHtml()}</tbody></table></div>
     <div class="row"><button id="ix-add" class="flat">${esc(tr("issue.add_row"))}</button><span class="spacer"></span>
       <span id="ix-total" class="hint"></span></div>`,
    [{ label: tr("issue.save"), primary: true, run: saveIssue }], null,
    { dirty: () => [...$("ix-lines").querySelectorAll(".ix-product, .ix-qty")].some((i) => i.value.trim()) || !!$("ix-customer").value.trim(),
      question: tr("issue.discard") });

  const rowProduct = (tr_) => productFromLabel(tr_.querySelector(".ix-product").value);
  const fillPrice = (tr_) => {
    const price = tr_.querySelector(".ix-price");
    if (price.dataset.typed) return;  // the user's own price is kept
    const p = rowProduct(tr_);
    const v = p ? lastPrice($("ix-customer").value, p.id) : null;
    price.value = v === null ? "" : fmtQty(v);
  };
  const refresh = () => {
    let total = 0, priced = false;
    for (const tr_ of $("ix-lines").querySelectorAll("tr")) {
      const p = rowProduct(tr_);
      tr_.querySelector(".ix-spec").textContent = p ? [p.spec, p.variant].filter(Boolean).join(" · ") : "";
      tr_.querySelector(".ix-unit").textContent = p ? p.unit || "" : "";
      let qty = 0;
      for (const place of [1, 2]) {
        const have = tr_.querySelector(`.ix-have[data-place="${place}"]`);
        const box = tr_.querySelector(`.ix-qty[data-place="${place}"]`);
        const asked = parseQty(box.value);
        have.textContent = p ? fmtQty(stockOf(p.id)[place] || 0) : "";
        const over = p && asked > 0 && asked > (stockOf(p.id)[place] || 0);
        have.classList.toggle("over", !!over);
        box.closest("td").classList.toggle("bad", Number.isNaN(asked));
        if (asked > 0) qty += asked;
      }
      const price = parseQty(tr_.querySelector(".ix-price").value);
      const amount = p && qty > 0 && price !== null && !Number.isNaN(price) ? Math.round(qty * price * 100) / 100 : null;
      tr_.querySelector(".ix-amount").textContent = amount === null ? "" : fmtVnd(amount);
      if (amount !== null) { total += amount; priced = true; }
    }
    $("ix-total").textContent = priced ? tr("issue.total", { money: fmtVnd(total) }) : "";
  };

  body.addEventListener("input", (e) => {
    const tr_ = e.target.closest("tr.ix-row");
    if (e.target.id === "ix-customer") {
      const c = data.customers.find((x) => x.name === e.target.value.replace(/\s+/g, " ").trim());
      if (c) for (const [id, v] of [["ix-phone", c.phone], ["ix-contact", c.contact], ["ix-address", c.address]]) if (!$(id).value.trim()) $(id).value = v || "";
      for (const row of $("ix-lines").querySelectorAll("tr")) fillPrice(row);
    }
    if (tr_ && e.target.classList.contains("ix-price")) e.target.dataset.typed = e.target.value.trim() ? "1" : "";
    if (tr_ && e.target.classList.contains("ix-product")) {
      fillPrice(tr_);
      const rows = $("ix-lines").querySelectorAll("tr");
      if (rowProduct(tr_) && tr_ === rows[rows.length - 1]) $("ix-lines").insertAdjacentHTML("beforeend", issueRowHtml());
    }
    refresh();
  });
  body.addEventListener("click", (e) => {
    if (!e.target.classList.contains("ix-remove")) return;
    const rows = $("ix-lines").querySelectorAll("tr");
    if (rows.length > 1) e.target.closest("tr").remove();
    else for (const i of e.target.closest("tr").querySelectorAll("input")) { i.value = ""; delete i.dataset.typed; }
    refresh();
  });
  body.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") e.preventDefault(); });  // Enter never saves
  $("ix-add").addEventListener("click", () => { $("ix-lines").insertAdjacentHTML("beforeend", issueRowHtml()); });
}

/** The window's content checked like core/issues.problems; throws the first problem. */
function readIssueForm() {
  const customer = $("ix-customer").value.replace(/\s+/g, " ").trim();
  if (!customer) fail(tr("issue.need_customer"));
  const date = $("ix-date").value;
  if (!date) fail(tr("issue.need_date"));
  const lines = [], seen = new Set();
  for (const tr_ of $("ix-lines").querySelectorAll("tr")) {
    const label = tr_.querySelector(".ix-product").value.trim();
    const [main, office, price] = [".ix-qty[data-place='1']", ".ix-qty[data-place='2']", ".ix-price"]
      .map((s) => parseQty(tr_.querySelector(s).value));
    if (!label && main === null && office === null) continue;
    const p = productFromLabel(label);
    if (!p) fail(tr("issue.unknown_product", { text: label || "?" }));
    if ([main, office, price].some((v) => Number.isNaN(v))) fail(tr("issue.not_number", { product: productName(p) }));
    if ([main, office, price].some((v) => v !== null && v < 0)) fail(tr("issue.negative", { product: productName(p) }));
    if (!((main || 0) + (office || 0) > 0)) continue;
    if (seen.has(p.id)) fail(tr("issue.same_product_twice", { product: productName(p) }));
    seen.add(p.id);
    lines.push({ product: p, product_id: p.id, qty_main: main || 0, qty_office: office || 0, unit_price: price,
                 note: tr_.querySelector(".ix-note").value });
  }
  if (!lines.length) fail(tr("issue.need_lines"));
  return { date, customer, phone: $("ix-phone").value.replace(/\s+/g, " ").trim(),
           contact: $("ix-contact").value.replace(/\s+/g, " ").trim(), address: $("ix-address").value.replace(/\s+/g, " ").trim(), lines };
}

async function saveIssue() {
  const f = readIssueForm();
  const short = [];
  for (const ln of f.lines) {
    for (const [place, qty] of [[1, ln.qty_main], [2, ln.qty_office]]) {
      const have = stockOf(ln.product.id)[place] || 0;
      if (qty > have) short.push(tr("issue.short_line", { product: productName(ln.product), place: tr(`place.${place}`), qty: fmtQty(qty), have: fmtQty(have) }));
    }
  }
  if (short.length && !confirm(`${tr("issue.short_ask")}\n\n${short.join("\n")}`)) return false;
  if (f.date > todayLocal() && !confirm(tr("issue.future_ask"))) return false;
  const rows = DBK_XLSX.noteRows(productById, f.lines);
  const total = rows.reduce((a, r) => a + (r.amount || 0), 0);
  const summary = rows.map((r) => `• ${r.code} ${r.name_vi}: ${fmtQty(r.qty)} ${r.unit} · ${tr(`place.${r.location_id}`)}` +
    (r.amount !== null ? ` · ${fmtVnd(r.amount)}` : "")).join("\n");
  if (!confirm(`${tr("issue.confirm", { customer: f.customer })}\n\n${summary}\n\n${tr("issue.total", { money: fmtVnd(total) })}`)) return false;
  const code = DBK_XLSX.newCode(new Date());
  const bytes = DBK_XLSX.issueNote(fflate, { code, doc_date: f.date, customer: f.customer, phone: f.phone, contact: f.contact, address: f.address }, rows);
  const name = `PhieuXuat_${code}.xlsx`;
  saveFile(name, bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  alert(tr("issue.done", { name }));
  return true;
}

$("issue-new").addEventListener("click", () => { if (canMakeIssue()) openIssueForm(); });
