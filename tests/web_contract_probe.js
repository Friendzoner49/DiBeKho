/* Driven by tests/test_web_contract.py inside headless Chrome. Fills in and presses the owner's windows of the web
   page on the shared data of a real shop (window.__FIXTURE__ = the cloud's rows), captures every function call the page
   would make (sb.rpc) and every staff request (web_inbox insert), and hands them back; the test then runs those calls on
   a real Postgres and lets the app pull the result. No network here: sb is stubbed. */

(async () => {
  const out = { calls: [], requests: [], accountCalls: [], checks: {}, error: null };
  try {
    const F = window.__FIXTURE__;
    const reload = async () => { setData(JSON.parse(JSON.stringify(F))); renderAll(); };
    loadAll = reload;           // after a write the page reloads: give it the same rows back
    loadInbox = async () => {};
    sb.rpc = async (fn, args) => {
      if (fn === "web_api_version") return { data: 10, error: null };  // a read: the SQL the page needs is there
      if (fn.startsWith("web_account")) {  // the account tab's own calls are kept apart from the documents' calls
        out.accountCalls.push({ rpc: fn, args });
        return { data: fn === "web_accounts_list" ? [
          { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", email: "maychinh@dibekho.local", display_name: "May chinh", role: "desktop" },
          { id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", email: "nhanvien1@dibekho.local", display_name: "Lan", role: "editor" },
          { id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd", email: "moi@dibekho.local", display_name: "", role: "" }] : {}, error: null };
      }
      out.calls.push({ fn, args });
      return { data: { code: "X", dropped: "Y" }, error: null };
    };
    sb.functions = { invoke: async (name, opts) => { out.accountCalls.push({ fn: name, body: opts.body }); return { data: { ok: true }, error: null }; } };
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

    // 13. Cài đặt → Tài khoản: only the owner has the tab; the buttons send what the Edge Function / SQL 011 expect
    const OWN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", LAN = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
    const accTab = () => getComputedStyle(document.querySelector('[data-stab="accounts"]')).display !== "none";
    setRole("editor", "NV");
    out.checks.accountsTabStaff = accTab();
    setRole("desktop", "Quan ly", false);
    out.checks.accountsTabOtherOwner = accTab();
    setRole("desktop", "Chủ", true);
    out.checks.accountsTabOwner = accTab();
    currentUserId = OWN;
    await loadAccounts();
    out.checks.accountRows = accounts.length;
    const tryPress = async (label) => { try { await press(label); return ""; } catch (e) { return String(e.message || e); } };
    $("acc-btn-add").click(); await wait();
    typeIn($("acc-user"), " Quan.Ly2 ");
    $("acc-name").value = "Chi Hoa"; $("acc-role").value = "viewer";
    $("acc-pw").value = "MatKhau-12345"; $("acc-pw2").value = "khac-hoan-toan";
    out.checks.pwMismatch = await tryPress("Tạo tài khoản");        // refused on the page, nothing sent
    $("acc-pw").value = "ngan"; $("acc-pw2").value = "ngan";
    out.checks.pwShort = await tryPress("Tạo tài khoản");
    $("acc-pw").value = "MatKhau-12345"; $("acc-pw2").value = "MatKhau-12345";
    $("acc-user").value = "co@dau"; out.checks.userAt = await tryPress("Tạo tài khoản");
    $("acc-user").value = "Quan.Ly2";
    await press("Tạo tài khoản");
    out.checks.pwAfterCreate = ($("acc-pw") || { value: "" }).value;  // dialog closed, nothing left in the fields
    // an owner account asks for a second confirmation (the stub's confirm answers yes; count the questions)
    let asked = 0; const realConfirm = window.confirm; window.confirm = (t) => { asked += 1; return realConfirm(t); };
    $("acc-btn-add").click(); await wait();
    $("acc-user").value = "chu2"; $("acc-role").value = "desktop"; $("acc-pw").value = "MatKhau-12345"; $("acc-pw2").value = "MatKhau-12345";
    await press("Tạo tài khoản");
    out.checks.ownerCreateAsked = asked; window.confirm = realConfirm;
    const pick = (id) => $("acc-table").querySelector(`tr[data-k="${id}"]`).click();
    pick(LAN); $("acc-btn-role").click(); await wait();
    $("acc-role").value = "viewer"; await press("Lưu");
    pick(LAN); $("acc-btn-pass").click(); await wait();
    $("acc-pw").value = "Moi-MatKhau-9"; $("acc-pw2").value = "Moi-MatKhau-9"; await press("Đổi mật khẩu");
    pick(OWN); $("acc-btn-revoke").click(); await wait(); await wait();   // refused on the page: not a single call
    pick(LAN); $("acc-btn-revoke").click(); await wait(); await wait();
    pick(OWN); $("acc-btn-delete").click(); await wait(); await wait();   // refused on the page too
    pick(LAN); $("acc-btn-delete").click(); await wait(); await wait();
  } catch (e) {
    out.error = String(e && e.stack || e);
  }
  document.body.setAttribute("data-probe", JSON.stringify(out));
})();
