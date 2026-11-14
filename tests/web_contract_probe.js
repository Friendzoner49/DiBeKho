/* Driven by tests/test_web_contract.py inside headless Chrome, on the shared data of a real shop
   (window.__FIXTURE__ = the cloud's rows). The web only looks (customer's request 14/11/2026): every call the page
   makes is captured (sb.rpc, sb.from, fetch), the Phiếu xuất kho file it hands to the browser is kept, and the
   test checks that nothing but the account tab's own calls ever leaves the page. No network: sb and fetch are stubbed. */

(async () => {
  const out = { calls: [], froms: [], accountCalls: [], fetches: [], files: [], checks: {}, error: null };
  try {
    const F = window.__FIXTURE__;
    const reload = async () => { setData(JSON.parse(JSON.stringify(F))); renderAll(); };
    loadAll = reload;
    sb.rpc = async (fn, args) => {
      if (fn.startsWith("web_account")) {  // the account tab's own calls are kept apart
        out.accountCalls.push({ rpc: fn, args });
        return { data: fn === "web_accounts_list" ? [
          { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", email: "maychinh@dibekho.local", display_name: "May chinh", role: "desktop" },
          { id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", email: "nhanvien1@dibekho.local", display_name: "Lan", role: "editor" },
          { id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd", email: "moi@dibekho.local", display_name: "", role: "" }] : {}, error: null };
      }
      out.calls.push({ fn, args });
      return { data: null, error: { message: "not in this test" } };
    };
    sb.functions = { invoke: async (name, opts) => { out.accountCalls.push({ fn: name, body: opts.body }); return { data: { ok: true }, error: null }; } };
    sb.from = (table) => { out.froms.push(table); return {}; };
    const FX = { result: "success", base_code: "CNY", time_last_update_unix: 1794614551, rates: { VND: 3846.153846 } };
    window.fetch = async (url) => { out.fetches.push(String(url)); return { ok: true, status: 200, json: async () => FX }; };
    const toB64 = (bytes) => { let s = ""; for (const b of bytes) s += String.fromCharCode(b); return btoa(s); };
    saveFile = (name, bytes) => out.files.push({ name, b64: toB64(bytes) });
    window.confirm = () => true;
    window.alert = () => {};

    const wait = () => new Promise((r) => setTimeout(r, 30));
    const prod = (code) => data.products.find((p) => p.code === code);
    const press = async (label) => {
      const btn = [...document.querySelectorAll("#dlg-buttons button")].find((b) => b.textContent === label);
      if (!btn) throw new Error(`no button “${label}” in: ${$("dlg-title").textContent}`);
      btn.click(); await wait(); await wait();
      if ($("dlg-error").textContent) throw new Error(`${label}: ${$("dlg-error").textContent}`);
    };
    const typeIn = (el, value) => { el.value = value; el.dispatchEvent(new Event("input", { bubbles: true })); };
    const shown = (el) => !!el && getComputedStyle(el).display !== "none";
    const navShown = (pageName) => shown(document.querySelector(`.nav[data-page="${pageName}"]`));
    const GONE = ["receipt-new", "receipt-edit", "count-save", "count-clear", "count-transfer", "count-trial", "catalog-add",
                  "catalog-edit", "catalog-merge", "customers-merge", "send-delivery", "pkg-import", "pkg-file", "pending-inbox"];
    out.checks.lang = document.documentElement.lang;
    out.checks.loginButton = $("login-btn").textContent;

    // staff: no overview, may make a Phiếu xuất kho, no account tab
    setRole("editor", "NV");
    await reload();
    showPage("dashboard");
    out.checks.staff = { dashboard: navShown("dashboard"), openedOn: page, issue: shown($("issue-new")),
                         accounts: shown(document.querySelector('[data-stab="accounts"]')),
                         backup: shown(document.querySelector('[data-stab="transfer"]')) };
    setRole("viewer", "Xem");
    out.checks.viewer = { issue: shown($("issue-new")), dashboard: navShown("dashboard") };

    // the main machine's role: the overview, drawn from the shop's data
    setRole("desktop", "Chủ", true);
    await reload();
    showPage("dashboard");
    out.checks.owner = { dashboard: navShown("dashboard"), openedOn: page, backup: shown(document.querySelector('[data-stab="transfer"]')),
                         kpis: $("dash-kpis").querySelectorAll(".kpi").length, months: $("dash-months").querySelectorAll("rect.bar").length,
                         products: $("dash-products").querySelectorAll("li").length, customers: $("dash-customers").querySelectorAll("li").length,
                         recent: $("dash-recent").querySelectorAll("li").length, title: document.querySelector("#page-dashboard h1").textContent,
                         revenue: $("dash-kpis").querySelector(".kpi-value").getAttribute("title") };
    out.checks.gone = GONE.filter((id) => document.getElementById(id));

    // Phiếu xuất kho: customer picked from the list fills its phone; the price comes from the latest order; 2 from
    // Kho tổng and 1 from Văn phòng of SP001, 1 of SP002 at a typed price
    $("issue-new").click(); await wait();
    out.checks.issueTitle = $("dlg-title").textContent;
    typeIn($("ix-customer"), "Cong ty A");
    out.checks.issuePhone = $("ix-phone").value;
    const rows = () => $("ix-lines").querySelectorAll("tr");
    typeIn(rows()[0].querySelector(".ix-product"), productLabel(prod("SP001")));
    out.checks.issuePrice = rows()[0].querySelector(".ix-price").value;
    out.checks.issueHave = [...rows()[0].querySelectorAll(".ix-have")].map((td) => td.textContent);
    typeIn(rows()[0].querySelector('.ix-qty[data-place="1"]'), "2");
    typeIn(rows()[0].querySelector('.ix-qty[data-place="2"]'), "1,5");
    typeIn(rows()[1].querySelector(".ix-product"), productLabel(prod("SP002")));
    typeIn(rows()[1].querySelector('.ix-qty[data-place="1"]'), "1");
    typeIn(rows()[1].querySelector(".ix-price"), "50");
    out.checks.issueTotal = $("ix-total").textContent;
    await press(tr("issue.save"));
    out.checks.issueClosed = !$("dlg").open;

    // a mistake stays on the page: the same product on two rows
    $("issue-new").click(); await wait();
    typeIn($("ix-customer"), "Cong ty A");
    for (const i of [0, 1]) {
      typeIn(rows()[i].querySelector(".ix-product"), productLabel(prod("SP001")));
      typeIn(rows()[i].querySelector('.ix-qty[data-place="1"]'), "1");
    }
    try { await press(tr("issue.save")); out.checks.twice = ""; } catch (e) { out.checks.twice = String(e.message); }
    dlg.close();

    // ₫ / ¥: the rate is fetched once and kept; every amount on screen turns into yuan, the issue window stays in dong
    try { localStorage.removeItem("dibekho_fx"); localStorage.removeItem("dibekho_currency"); } catch (e) { /* none */ }
    const priced = data.documents.find((d) => d.code === "7");
    out.checks.fxBefore = fmtMoney(500);
    document.querySelector('[data-cur="cny"]').click(); await wait(); await wait();
    out.checks.fxOn = document.querySelector('[data-cur="cny"]').classList.contains("on");
    out.checks.fxInfo = $("fx-info").textContent;
    out.checks.fxMoney = fmtMoney(3846153.846);
    showCustomer(priced.customer_id);
    out.checks.fxCustomer = [...document.querySelectorAll("#page-detail .stat b")][1].textContent;
    out.checks.fxKpi = $("dash-kpis").querySelector(".kpi-value").textContent;
    $("issue-new").click(); await wait();
    typeIn(rows()[0].querySelector(".ix-product"), productLabel(prod("SP001")));
    typeIn(rows()[0].querySelector('.ix-qty[data-place="1"]'), "2");
    typeIn(rows()[0].querySelector(".ix-price"), "100");
    out.checks.fxIssueAmount = rows()[0].querySelector(".ix-amount").textContent;
    $("dlg").close();
    document.querySelector('[data-cur="vnd"]').click(); await wait();
    document.querySelector('[data-cur="cny"]').click(); await wait();   // fresh: not asked again
    out.checks.fxFetches = out.fetches.length;
    document.querySelector('[data-cur="vnd"]').click(); await wait();
    out.checks.fxAfter = fmtMoney(500);
    showPage("stock");

    // stock list: opens sorted by code, Tồn stays in view; names in the page's language
    renderStock();
    const codes = [...$("stock-table").querySelectorAll("tbody tr td:first-child")].map((td) => td.textContent);
    out.checks.stockSorted = codes.join() === codes.slice().sort((a, b) => a.localeCompare(b, "vi", { numeric: true })).join() && codes.length > 1;
    out.checks.stockHeads = [...$("stock-table").querySelectorAll("thead th")].map((th) => th.textContent.trim()).slice(0, 8).join();
    out.checks.stockFirst = [...$("stock-table").querySelectorAll("tbody tr:first-child td")].slice(0, 3).map((td) => td.textContent);
    out.checks.zoom = document.documentElement.style.zoom;
    out.checks.scaleOwner = shown($("ui-scale").parentElement);
    setRole("desktop", "Quan ly", false);
    out.checks.scaleOther = shown($("ui-scale").parentElement);
    out.checks.accountsTabOtherOwner = shown(document.querySelector('[data-stab="accounts"]'));
    setRole("desktop", "Chủ", true);
    out.checks.accountsTabOwner = shown(document.querySelector('[data-stab="accounts"]'));

    // Cài đặt → Tài khoản: the buttons send what the Edge Function / SQL 011 expect
    const OWN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", LAN = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
    currentUserId = OWN;
    await loadAccounts();
    out.checks.accountRows = accounts.length;
    const tryPress = async (label) => { try { await press(label); return ""; } catch (e) { return String(e.message || e); } };
    $("acc-btn-add").click(); await wait();
    typeIn($("acc-user"), " Quan.Ly2 ");
    $("acc-name").value = "Chi Hoa"; $("acc-role").value = "viewer";
    $("acc-pw").value = "MatKhau-12345"; $("acc-pw2").value = "khac-hoan-toan";
    out.checks.pwMismatch = await tryPress(tr("acc.create_do"));
    $("acc-pw").value = "ngan"; $("acc-pw2").value = "ngan";
    out.checks.pwShort = await tryPress(tr("acc.create_do"));
    $("acc-pw").value = "MatKhau-12345"; $("acc-pw2").value = "MatKhau-12345";
    $("acc-user").value = "co@dau"; out.checks.userAt = await tryPress(tr("acc.create_do"));
    $("acc-user").value = "Quan.Ly2";
    await press(tr("acc.create_do"));
    out.checks.pwAfterCreate = ($("acc-pw") || { value: "" }).value;
    let asked = 0; const realConfirm = window.confirm; window.confirm = (t) => { asked += 1; return realConfirm(t); };
    $("acc-btn-add").click(); await wait();
    $("acc-user").value = "chu2"; $("acc-role").value = "desktop"; $("acc-pw").value = "MatKhau-12345"; $("acc-pw2").value = "MatKhau-12345";
    await press(tr("acc.create_do"));
    out.checks.ownerCreateAsked = asked; window.confirm = realConfirm;
    const pick = (id) => $("acc-table").querySelector(`tr[data-k="${id}"]`).click();
    pick(LAN); $("acc-btn-role").click(); await wait();
    $("acc-role").value = "viewer"; await press(tr("btn.save"));
    pick(LAN); $("acc-btn-pass").click(); await wait();
    $("acc-pw").value = "Moi-MatKhau-9"; $("acc-pw2").value = "Moi-MatKhau-9"; await press(tr("acc.pass_do"));
    pick(OWN); $("acc-btn-revoke").click(); await wait(); await wait();   // refused on the page: not a single call
    pick(LAN); $("acc-btn-revoke").click(); await wait(); await wait();
    pick(OWN); $("acc-btn-delete").click(); await wait(); await wait();   // refused on the page too
    pick(LAN); $("acc-btn-delete").click(); await wait(); await wait();
  } catch (e) {
    out.error = String(e && e.stack || e);
  }
  document.body.setAttribute("data-probe", JSON.stringify(out));
})();
