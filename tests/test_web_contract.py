"""The contract between the web page and the shared data, end to end.

A real Chrome (headless) opens the page on a shop's shared rows (read from a real Postgres with the project's SQL,
PGlite) and goes through it as staff, as a viewer and as the main machine's role. The web only looks (customer's
request 14/11/2026): every call the page makes is captured, and nothing but the account tab's own calls may leave it.
The Phiếu xuất kho file the page hands to the browser is read back by the app and dropped into its notes folder:
the stock of each place goes down once. The same page in 中文 shows Chinese words and Chinese product names.
Skipped without Chrome or PGlite."""

import base64
import functools
import html
import http.server
import json
import re
import shutil
import subprocess
import threading
from datetime import date
from pathlib import Path

import pytest

from dibekho import db
from dibekho.core import catalog, deliveries, receipts, stock
from dibekho.core.cloud import replica, twoway
from dibekho.core.workspace import Workspace
from dibekho.excel.delivery_note import read_delivery_note
from tests.pgdb import WEB_FILES, FakeCloud, Session, needs_pg

ROOT = Path(__file__).resolve().parent.parent
OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
# what the owner's windows of the past called (cloud/supabase/009_web_rpc.sql, 010); the SQL stays on the server,
# tests/test_cloud_web_rpc.py keeps it right, but the page itself never calls it any more
WRITE_CALLS = ("web_transfer", "web_trial", "web_product_add", "web_product_edit", "web_product_merge",
               "web_customer_merge", "web_cancel", "web_set_location", "web_receipt", "web_stock_count", "sync_push",
               "web_inbox", "sb.storage", ".upload(")


def find_chrome():
    for name in ("chrome", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    for path in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                 "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if Path(path).exists():
            return path
    return None


CHROME = find_chrome()
needs_chrome = pytest.mark.skipif(CHROME is None, reason="Chrome is not installed")
TABLES = ("products", "customers", "suppliers", "documents", "document_lines", "stock_movements", "meta")


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def test_the_page_has_no_code_that_writes():
    """The windows that wrote (009/010), the staff requests (web_inbox), the file upload and the package import are
    gone from the page: only the account tab (SQL 011 + Edge Function) and the interface size (web_settings) remain."""
    found = []
    for path in sorted((ROOT / "webapp").glob("*.js")):
        if path.name in ("config.js", "config.example.js"):
            continue
        text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        found += [f"{path.name}: {w}" for w in WRITE_CALLS if w in text]
        writes = re.findall(r"\.(?:insert|update|delete|upsert)\(", text.replace(".sel.delete(", ""))  # a Set's delete is fine
        found += [f"{path.name}: {m}" for m in writes]
    assert not found, found
    rpcs = set()
    for path in (ROOT / "webapp").glob("*.js"):
        rpcs |= set(re.findall(r"""sb\.rpc\(\s*["'](\w+)["']""", path.read_text(encoding="utf-8")))
    assert rpcs <= {"sync_pull", "web_setting_set", "web_accounts_list", "web_account_set_role", "web_account_revoke"} | {""}, rpcs


def _shop(conn):
    with db.transaction(conn):
        a = catalog.create_product(conn, "Keo A", "胶A", spec="15kg", unit="thung", category="Keo")
        b = catalog.create_product(conn, "Mang B", spec="3mm", unit="cuon", category="Mang")
        catalog.create_product(conn, "Keo C", spec="15kg", unit="thung", category="Keo")
        cust = catalog.upsert_customer(conn, "Cong ty A", phone="0900 000 001")
        catalog.upsert_customer(conn, "Khach X", phone="0900 000 002")
        stock.insert_document(conn, "delivery", date(2026, 11, 2), [stock.Line(a, 5, unit_price=100, amount=500)],
                              code="7", code_norm="7", customer_id=cust)
        stock.insert_document(conn, "delivery", date(2026, 11, 3), [stock.Line(a, 3)], code="8", code_norm="8",
                              customer_id=cust, location_set=False)
        stock.transfer(conn, date(2026, 11, 2), stock.MAIN, stock.OFFICE, [stock.Line(a, 10)])
    receipts.save(conn, receipts.ReceiptInput(date(2026, 11, 1), receipts.SUPPLIER, supplier_name="Cua khau",
                                              lines=[receipts.ReceiptLineInput(50, a),
                                                     receipts.ReceiptLineInput(20, b)]))
    return {"a": a, "b": b, "cust": cust}


@pytest.fixture
def cloud_shop(tmp_path):
    pg = Session(WEB_FILES)
    pg.add_account(OWNER)
    conn = db.connect(tmp_path / "shop.sqlite")
    replica.set_enabled(conn, True)
    ids = _shop(conn)
    replica.queue_all(conn)
    cloud = FakeCloud(pg)
    assert twoway.sync_round(conn, cloud, OWNER, "Shop").pushed > 0
    yield pg, conn, cloud, ids
    pg.close()


def _run_page(pg, tmp_path, probe="web_contract_probe.js", extra="", head=""):
    fixture = {t: [r["r"] for r in pg.query(f"select to_jsonb(x) as r from public.{t} x where not deleted")]
               for t in TABLES}
    fixture = {"products": fixture["products"], "customers": fixture["customers"], "suppliers": fixture["suppliers"],
               "documents": fixture["documents"], "lines": fixture["document_lines"],
               "movements": fixture["stock_movements"], "meta": fixture["meta"]}
    site = tmp_path / "site"
    shutil.rmtree(site, ignore_errors=True)
    shutil.copytree(ROOT / "webapp", site, ignore=shutil.ignore_patterns("config.js"))
    (site / "config.js").write_text('const DIBEKHO_CLOUD = {url: "https://example.supabase.co", key: "k"};'
                                    "window.__DIBEKHO_TEST__ = true;", encoding="utf-8")
    (site / "fixture.js").write_text("window.__FIXTURE__ = " + json.dumps(fixture) + ";" + extra, encoding="utf-8")
    (site / "head.js").write_text(head, encoding="utf-8")
    shutil.copy(ROOT / "tests" / probe, site / "probe.js")
    page = (site / "index.html").read_text(encoding="utf-8")
    page = page.replace("</body>", '<script src="fixture.js"></script><script src="probe.js"></script></body>')
    page = page.replace("<title>", '<script src="head.js"></script><title>')  # runs before any script of the page
    # the supabase library from the CDN is not needed (sb is stubbed): a tiny local stand-in keeps the test offline
    page = re.sub(r'<script src="https://cdn\.jsdelivr\.net[^>]*></script>', '<script src="sb_stub.js"></script>', page)
    (site / "sb_stub.js").write_text("window.supabase = { createClient: () => ({ auth: {}, from: () => ({}), rpc: () => ({}) }) };",
                                     encoding="utf-8")
    (site / "index.html").write_text(page, encoding="utf-8")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        done = subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={tmp_path / 'chrome'}",
             "--virtual-time-budget=20000", "--dump-dom", f"http://127.0.0.1:{server.server_port}/"],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
    finally:
        server.shutdown()
    found = re.search(r'data-probe="([^"]*)"', done.stdout)
    assert found, "the page never finished its scenario:\n" + done.stdout[-800:] + done.stderr[-400:]
    out = json.loads(html.unescape(found.group(1)))
    assert out["error"] is None, out["error"]
    return out


@needs_chrome
@needs_pg
def test_the_page_only_looks_and_makes_a_stock_issue_note_the_app_takes(cloud_shop, tmp_path):
    pg, conn, cloud, ids = cloud_shop
    out = _run_page(pg, tmp_path)
    checks = out["checks"]
    assert (checks["lang"], checks["loginButton"]) == ("vi", "Đăng nhập")

    # nothing but the account tab's calls left the page; the rate is the only thing fetched, once
    assert out["calls"] == [] and out["froms"] == []
    assert out["fetches"] == ["https://open.er-api.com/v6/latest/CNY"] and checks["fxFetches"] == 1
    assert checks["gone"] == []

    # who sees what: the overview only for the main machine's role, the issue note for it and staff
    assert checks["staff"] == {"dashboard": False, "openedOn": "stock", "issue": True, "accounts": False, "backup": False}
    assert checks["viewer"] == {"issue": False, "dashboard": False}
    owner = checks["owner"]
    assert (owner["dashboard"], owner["openedOn"], owner["backup"], owner["title"]) == (True, "dashboard", True, "Tổng quan")
    assert (owner["kpis"], owner["months"]) == (4, 12)
    assert owner["products"] >= 1 and owner["customers"] >= 1 and owner["recent"] == 2

    # the issue window: phone of the customer filled in, price from the latest order (100), stock per place shown
    assert checks["issueTitle"] == "Phiếu xuất kho" and checks["issuePhone"] == "0900 000 001"
    assert checks["issuePrice"] == "100" and checks["issueHave"] == ["32", "10"]  # 50 - 5 - 3 - 10 at Kho tổng
    assert checks["issueTotal"] == "Tiền hàng: 400" and checks["issueClosed"]
    assert "2 dòng" in checks["twice"]
    (made,) = out["files"]
    assert re.fullmatch(r"PhieuXuat_PX\d{6}-\d{6}\.xlsx", made["name"]), made["name"]

    # the file reads like the app's own, and dropped into the notes folder takes each place once
    ws = Workspace(tmp_path / "ws")
    ws.ensure()
    path = ws.deliveries / made["name"]
    path.write_bytes(base64.b64decode(made["b64"]))
    note = read_delivery_note(path)
    assert (note.customer_name, note.phone, note.code) == ("Cong ty A", "0900 000 001", made["name"][10:-5])
    assert [(ln.product_code, ln.location_id, ln.qty, ln.unit_price, ln.amount) for ln in note.lines] == [
        ("SP001", 1, 2, 100, 200), ("SP001", 2, 1.5, 100, 150), ("SP002", 1, 1, 50, 50)]
    before = stock.stock_levels(conn, by_location=True)
    deliveries.scan(conn, ws)
    after = stock.stock_levels(conn, by_location=True)
    a, b = ids["a"], ids["b"]
    assert (before[(a, stock.MAIN)] - after[(a, stock.MAIN)], before[(a, stock.OFFICE)] - after[(a, stock.OFFICE)],
            before[(b, stock.MAIN)] - after[(b, stock.MAIN)]) == (2, 1.5, 1)
    deliveries.scan(conn, ws)
    assert stock.stock_levels(conn, by_location=True) == after

    # ₫ / ¥: every amount on screen in yuan at the market rate, back to dong; the issue window stays in dong
    assert checks["fxBefore"] == checks["fxAfter"] == "500"
    assert checks["fxOn"] and "3.846" in checks["fxInfo"] and checks["fxMoney"] == "¥1.000"
    assert checks["fxCustomer"] == "¥0,13" and checks["fxKpi"].startswith("¥") and "đ" not in checks["fxKpi"]
    assert checks["fxIssueAmount"] == "200"

    # stock list and interface size, as before
    assert checks["stockSorted"] and checks["zoom"] == "1"
    assert checks["stockHeads"] == "Mã,Mặt hàng,Tên Trung,Quy cách,Loại / màu,Nhóm hàng,Đơn vị,Tồn"
    assert checks["stockFirst"] == ["SP001", "Keo A", "胶A"]
    assert checks["scaleOwner"] is True and checks["scaleOther"] is False

    # Cài đặt → Tài khoản: only the maychinh login has the tab; bad input never leaves the page; the buttons send
    # what the Edge Function (create, reset) and SQL 011 (role, revoke) take, and not one call touches oneself
    assert checks["accountsTabOtherOwner"] is False and checks["accountsTabOwner"] is True and checks["accountRows"] == 3
    assert "chưa giống nhau" in checks["pwMismatch"] and "ít nhất 8" in checks["pwShort"] and "@dibekho.local" in checks["userAt"]
    assert checks["pwAfterCreate"] == "" and checks["ownerCreateAsked"] == 1
    lan = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    acc = out["accountCalls"]
    assert [c["body"] for c in acc if "fn" in c] == [
        {"action": "create", "username": "quan.ly2", "password": "MatKhau-12345", "role": "viewer", "display_name": "Chi Hoa"},
        {"action": "create", "username": "chu2", "password": "MatKhau-12345", "role": "desktop", "display_name": ""},
        {"action": "reset_password", "user_id": lan, "password": "Moi-MatKhau-9"},
        {"action": "delete", "user_id": lan}]
    assert all(c["fn"] == "accounts" for c in acc if "fn" in c)
    assert [(c["rpc"], c["args"]) for c in acc if c.get("rpc") not in (None, "web_accounts_list")] == [
        ("web_account_set_role", {"p_user": lan, "p_role": "viewer", "p_name": "Lan"}),
        ("web_account_revoke", {"p_user": lan})]
    assert sum(1 for c in acc if c.get("rpc") == "web_accounts_list") >= 4  # the list reloads after every change


@needs_chrome
@needs_pg
def test_the_same_page_in_chinese(cloud_shop, tmp_path):
    pg, conn, cloud, ids = cloud_shop
    out = _run_page(pg, tmp_path, head='try { localStorage.setItem("dibekho_lang", "zh"); } catch (e) {}')
    checks = out["checks"]
    assert (checks["lang"], checks["loginButton"]) == ("zh-CN", "登录")
    assert checks["owner"]["title"] == "概览" and checks["issueTitle"] == "出库单"
    assert checks["stockHeads"] == "编码,商品,越南语名称,规格,类型/颜色,类别,单位,库存"
    assert checks["stockFirst"] == ["SP001", "胶A", "Keo A"]  # the Chinese name first, the Vietnamese one next to it
    assert "两次输入的密码不一致" in checks["pwMismatch"]
    assert checks["issueTotal"] == "货款：400"
    (made,) = out["files"]
    note = read_delivery_note(_save(tmp_path, made))
    assert [ln.location_id for ln in note.lines] == [1, 2, 1]  # the file is the same bilingual file in any language


def _save(tmp_path, made):
    path = tmp_path / made["name"]
    path.write_bytes(base64.b64decode(made["b64"]))
    return path
