/* Driven by tests/test_web_contract.py inside headless Chrome. Fills in and presses the owner's windows of the web
   page on the shared data of a real shop (window.__FIXTURE__ = the cloud's rows), captures every function call the page
   would make (sb.rpc) and every staff request (web_inbox insert), and hands them back; the test then runs those calls on
   a real Postgres and lets the app pull the result. No network here: sb is stubbed. */

(async () => {
  const out = { calls: [], requests: [], checks: {}, error: null };
  try {
    const F = window.__FIXTURE__;
    const reload = async () => { setData(JSON.parse(JSON.stringify(F))); renderAll(); };
    loadAll = reload;           // after a write the page reloads: give it the same rows back
    loadInbox = async () => {};
    sb.rpc = async (fn, args) => {
      if (fn === "web_api_version") return { data: 10, error: null };  // a read: the SQL the page needs is there
      out.calls.push({ fn, args });
      return { data: { code: "X", dropped: "Y" }, error: null };
    };
    sb.from = () => ({ insert: async (row) => { out.requests.push(row); return { error: null }; } });
    window.confirm = () => true;
    window.alert = () => {};

    const wait = () => new Promise((r) => setTimeout(r, 30));
    const prod = (code) => data.products.find((p) => p.code === code);
    const docBy = (kind, code) => data.documents.find((d) => d.kind === kind && d.code === code && d.status === "active");
    const press = async (label) => {
      const btn = [...document.querySelectorAll("#dlg-buttons button")].find((b) => b.textContent === label);
      if (!btn) throw new Error(`no button “${label}” in: ${$("dlg-title").textContent}`);
      btn.click(); await wait(); await wait();
      if ($("dlg-error").textContent) throw new Error(`${label}: ${$("dlg-error").textContent}`);
    };
    const typeIn = (el, value) => { el.value = value; el.dispatchEvent(new Event("input", { bubbles: true })); };
    const qtyRow = (tbody, code) => $(tbody).querySelector(`tr[data-pid="${prod(code).id}"] input`);
    const shown = (id) => getComputedStyle($(id)).display !== "none";

    // staff: no owner buttons, the goods-in and count buttons are there
    setRole("editor", "NV");
    await reload();
    out.checks.staff = { transfer: shown("count-transfer"), receipt: shown("receipt-new"), save: shown("count-save"),
                         editReceipt: shown("receipt-edit") };
    // staff send a goods-in request
    receiptForm(null);
    out.checks.staffStar = !!$("rf-lines").querySelector(".rf-star");  // only the owner makes new products
    typeIn($("rf-lines").querySelector(".rf-product"), productLabel(prod("SP002")));
    typeIn($("rf-lines").querySelector(".rf-qty"), "4,5");
    $("rf-supplier").value = "Cua khau";
    await press("Lưu phiếu hàng về");
    // ...and a count of the office
    typeIn($("count-table").querySelector(`input[data-count="${prod("SP001").id}"][data-place="2"]`), "3");
    $("count-save").click(); await wait(); await wait();

    setRole("desktop", "Chủ");
    await reload();
    out.checks.owner = { transfer: shown("count-transfer"), merge: shown("catalog-merge") };

    // 1. transfer
    transferForm(null);
    $("tf-date").value = "2026-11-05"; $("tf-from").value = "1"; $("tf-to").value = "2";
    $("tf-note").value = "ban tai van phong";
    qtyRow("tf-lines", "SP001").value = "12";
    await press("Lưu phiếu chuyển");
    // 2. trial use
    trialForm();
    $("tu-date").value = "2026-11-06"; $("tu-loc").value = "2";
    qtyRow("tu-lines", "SP001").value = "2";
    await press("Lưu phiếu dùng thử");
    // 3. add a product
    productForm(null);
    $("pf-name_vi").value = "Keo D"; $("pf-spec").value = "25kg"; $("pf-unit").value = "thung"; $("pf-category").value = "Keo";
    await press("Thêm mặt hàng");
    // 4. edit / stop a product
    productForm(prod("SP001"));
    $("pf-name_vi").value = "Keo A moi"; $("pf-stock_note").value = "2 thung mop"; $("pf-active").checked = false;
    await press("Lưu");
    // 5. merge two products (SP003 into SP002)
    mergeProductsWindow(prod("SP003"));
    $("mg-table").querySelector(`tr[data-k="${prod("SP002").id}"]`).click();
    await press("Gộp");
    // 6. merge customers: pick the rows in the Khách hàng list, then the button
    for (const c of data.customers.filter((x) => x.name === "Khach X" || x.name === "Khach Y")) {
      $("customers-table").querySelector(`tr[data-k="${c.id}"]`).click();
    }
    $("customers-merge").click(); await wait();
    $("cm-name").value = "Khach XY";
    await press("Gộp khách hàng");
    // 7. cancel a delivery
    showOrder(docBy("delivery", "7").id);
    await press("Huỷ phiếu");
    // 8. where delivery 8 was taken from
    showOrder(docBy("delivery", "8").id);
    $("od-place").value = "2";
    $("od-place-save").click(); await wait(); await wait();
    dlg.close();
    // 9. edit the goods-in receipt HV001 (from the Hàng về page: select it, Sửa phiếu đã chọn…)
    $("receipts-table").querySelector(`tr[data-k="${docBy("receipt", "HV001").id}"]`).click();
    $("receipt-edit").click(); await wait();
    out.checks.editTitle = $("dlg-title").textContent;
    typeIn($("rf-lines").querySelector(".rf-qty"), "60");
    await press("Lưu phiếu đã sửa");
    // 10. a new receipt, returned by a customer
    receiptForm(null);
    document.querySelector('input[name="rf-src"][value="return"]').click();
    out.checks.returnFields = shown("rf-customer") && !shown("rf-supplier");
    $("rf-customer").value = data.customers.find((c) => c.name === "Cong ty A").id;
    $("rf-ref").value = "7";
    typeIn($("rf-lines").querySelector(".rf-product"), productLabel(prod("SP001")));
    typeIn($("rf-lines").querySelector(".rf-qty"), "1");
    await press("Lưu phiếu hàng về");
    // 11. a stock count of Kho tổng, typed into the yellow column of the Kiểm kê page
    $("count-date").value = "2026-11-07";
    typeIn($("count-table").querySelector(`input[data-count="${prod("SP002").id}"][data-place="1"]`), "18");
    $("count-save").click(); await wait(); await wait();
    out.checks.countMsg = $("count-msg").textContent;
    // 12. a receipt with "★ Mặt hàng mới": one really new, one that is already in the catalog (the page asks, the
    // owner says yes: the existing product is used instead of a duplicate)
    receiptForm(null);
    $("rf-supplier").value = "Cong ty me";
    const rows = $("rf-lines").querySelectorAll("tr");
    rows[0].querySelector(".rf-star").click();
    typeIn(rows[0].querySelector(".rf-n-name_vi"), "Son lot");
    typeIn(rows[0].querySelector(".rf-n-name_zh"), "底漆");
    typeIn(rows[0].querySelector(".rf-n-spec"), "18L/Thung");
    typeIn(rows[0].querySelector(".rf-n-category"), "Son");
    typeIn(rows[0].querySelector(".rf-qty"), "10");
    out.checks.starSpec = rows[0].querySelector(".rf-spec").textContent;
    rows[1].querySelector(".rf-star").click();
    typeIn(rows[1].querySelector(".rf-n-name_vi"), "mang  b");
    typeIn(rows[1].querySelector(".rf-n-spec"), "3MM");
    typeIn(rows[1].querySelector(".rf-qty"), "2");
    await press("Lưu phiếu hàng về");
  } catch (e) {
    out.error = String(e && e.stack || e);
  }
  document.body.setAttribute("data-probe", JSON.stringify(out));
})();
