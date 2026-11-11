/* Driven by tests/test_web_contract.py inside headless Chrome. It fills in and presses the web forms of the owner on
   the data of a real database (window.__FIXTURE__ = the mirror payload), captures every row the page would insert
   into web_inbox, and hands them back for the desktop to carry out. No network: sb.from(...).insert is a stub. */

(async () => {
  const out = { captured: [], checks: {}, error: null };
  try {
    const F = window.__FIXTURE__;
    Object.assign(data, F);
    productById = {}; customerById = {}; linesByDoc = {}; stockByProduct = {};
    for (const p of data.products) productById[p.id] = p;
    for (const c of data.customers) customerById[c.id] = c;
    for (const l of data.lines) (linesByDoc[l.document_id] ||= []).push(l);
    sb.from = () => ({ insert: async (row) => { out.captured.push(row); return { error: null }; } });
    loadSent = async () => {};
    window.confirm = () => true;
    window.alert = () => {};

    const wait = () => new Promise((r) => setTimeout(r, 25));
    const code = (c) => data.products.find((p) => p.code === c);
    const label = (c) => productLabel(code(c));
    const docBy = (kind, c) => data.documents.find((d) => d.kind === kind && d.code === c);
    const fire = (el, type) => el.dispatchEvent(new Event(type, { bubbles: true }));
    const press = async (id) => { $(id).click(); await wait(); };
    const setRow = (prefix, i, c, qty) => {
      while ($(`${prefix}-lines`).children.length <= i) addLineRow(prefix, true);
      const row = $(`${prefix}-lines`).children[i];
      row.querySelector(`.${prefix}-product`).value = label(c);
      row.querySelector(`.${prefix}-qty`).value = String(qty);
    };

    // staff see none of the owner's tools
    userRole = "editor";
    initSendForm(); initOwnerMode();
    out.checks.staffChipsHidden = Array.from(document.querySelectorAll(".chip.owner")).every((c) => c.classList.contains("hidden"));
    out.checks.staffActions = ownerActionsHtml(docBy("delivery", "7"));

    userRole = "desktop";
    initOwnerMode();
    out.checks.ownerChipsShown = Array.from(document.querySelectorAll(".chip.owner")).every((c) => !c.classList.contains("hidden"));
    out.checks.ownerTabLabel = $("send-tab").textContent;

    // 1. transfer
    $("tr-date").value = "2026-11-05"; $("tr-from").value = "1"; $("tr-to").value = "2";
    setRow("tr", 0, "SP001", 12); $("tr-note").value = "ban tai van phong";
    await press("tr-send");
    // 2. trial use
    $("tu-date").value = "2026-11-06"; $("tu-loc").value = "2"; setRow("tu", 0, "SP001", 2);
    await press("tu-send");
    // 3. add a product
    $("pd-action").value = "add"; syncProductForm(); fillProductForm(null);
    $("pd-name-vi").value = "Keo D"; $("pd-spec").value = "25kg"; $("pd-unit").value = "thung"; $("pd-category").value = "Keo";
    await press("pd-send");
    // 4. edit / stop a product
    $("pd-action").value = "edit"; syncProductForm();
    $("pd-pick").value = label("SP001"); fire($("pd-pick"), "change");
    $("pd-name-vi").value = "Keo A moi"; $("pd-note").value = "2 thung mop"; $("pd-active").checked = false;
    await press("pd-send");
    // 5. merge two products
    $("pd-action").value = "merge"; syncProductForm();
    $("pd-a").value = label("SP003"); $("pd-b").value = label("SP002");
    await press("pd-send");
    // 6. merge customers
    renderCustomerPicker();
    for (const box of $("cm-list").querySelectorAll("input")) {
      const c = customerById[Number(box.value)];
      if (c.name === "Khach X" || c.name === "Khach Y") box.checked = true;
    }
    $("cm-name").value = "Khach XY";
    await press("cm-send");
    // 7. cancel a delivery, 8. set the place of another
    const shelf = document.createElement("div");
    document.body.append(shelf);
    const d7 = docBy("delivery", "7"), d8 = docBy("delivery", "8");
    const box7 = document.createElement("div"); box7.innerHTML = ownerActionsHtml(d7); shelf.append(box7); bindOrderActions(box7, d7);
    box7.querySelector('[data-act="cancel"]').click(); await wait();
    const box8 = document.createElement("div"); box8.innerHTML = ownerActionsHtml(d8); shelf.append(box8); bindOrderActions(box8, d8);
    box8.querySelector("[data-act-place]").value = "2";
    box8.querySelector('[data-act="place"]').click(); await wait();
    // 9. edit the goods-in receipt
    startReceiptEdit(docBy("receipt", "HV001"));
    out.checks.editTitle = $("rc-title").textContent;
    $("rc-lines").children[0].querySelector(".rc-qty").value = "60";
    await press("rc-send");
    out.checks.editLeftAfterSend = receiptEdit === null;
    // 10. a new goods-in slip (supplier), 11. one for returned goods
    $("rc-date").value = "2026-11-07"; $("rc-kind").value = "supplier"; syncReceiptKind(); $("rc-source").value = "Cua khau";
    $("rc-lines").innerHTML = ""; addLine();
    $("rc-lines").children[0].querySelector(".rc-product").value = label("SP002");
    $("rc-lines").children[0].querySelector(".rc-qty").value = "5";
    await press("rc-send");
    $("rc-kind").value = "return"; syncReceiptKind();
    out.checks.returnFieldsShown = !$("rc-l-customer").classList.contains("hidden") && !$("rc-l-ref").classList.contains("hidden");
    const cust = data.customers.find((c) => c.name === "Cong ty A");
    $("rc-customer").value = String(cust.id); $("rc-ref").value = "7";
    $("rc-lines").innerHTML = ""; addLine();
    $("rc-lines").children[0].querySelector(".rc-product").value = label("SP002");
    $("rc-lines").children[0].querySelector(".rc-qty").value = "1";
    await press("rc-send");
    // 12. a stock count
    $("ct-date").value = todayLocal(); $("ct-loc").value = "1";
    $("ct-lines").innerHTML = ""; addCountLine();
    $("ct-lines").children[0].querySelector(".ct-product").value = label("SP002");
    $("ct-lines").children[0].querySelector(".ct-qty").value = "18";
    await press("ct-send");
  } catch (e) {
    out.error = String((e && e.stack) || e);
  }
  document.body.setAttribute("data-probe", JSON.stringify(out));
})();
