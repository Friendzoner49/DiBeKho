from datetime import date
from pathlib import Path

import openpyxl
import pytest

from dibekho import db
from dibekho.core.workspace import Workspace

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def ws(tmp_path) -> Workspace:
    w = Workspace(tmp_path / "DiBeKho")
    w.ensure()
    return w


def make_note(path: Path, code="101", day="05-10-2026", customer="Công ty A", phone="0901 234 567",
              lines=(("背水涂\nvữa chống thấm (BACKWATER COATING)", "10KG/thùng", 3, ""),),
              extra_top_row=False, extra_rows=()) -> Path:
    """Build a workbook shaped like the customer's PHIẾU GIAO HÀNG."""
    wb = openpyxl.Workbook()
    ws = wb.active
    rows = [
        ["CÔNG TY TNHH VẬT LIỆU CHỐNG THẤM MẪU"],
        ["Hà Nội"],
    ]
    if extra_top_row:
        rows.append([None])
    rows += [
        ["销售单 PHIẾU GIAO HÀNG"],
        [f"客户名称 ( Tên khách hàng ): \n{customer}", None, f"联系电话 ( Điện thoại liên hệ ): {phone}",
         None, None, f"订货单号 ( Mã đơn hàng )：{code}"],
        [None, None, "联系人( Người liên hệ )：Anh B", None, None, f"送货日期 ( Ngày giao hàng )：{day}"],
        ["地址( Địa chỉ): 1 Đường X, Hà Nội"],
        ["编 号\nSTT", "商 品 全 名\nTên hàng", "规格\nQUY CÁCH ", "数 量\nSố lượng", "单 价\nVND",
         "金 额\nVND", "备 注\nGhi chú"],
    ]
    for i, (name, spec, qty, note) in enumerate(lines, start=1):
        rows.append([i, name, spec, qty, 100000, None, note])
    rows += [list(r) for r in extra_rows]
    rows.append(["总计大写\n (Tổng cộng viết bằng chữ)", "MỘT TRIỆU"])
    rows.append(["送货单位及经手人（盖章）：Người giao hàng"])
    for r in rows:
        ws.append(r)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


@pytest.fixture
def today():
    return date(2026, 10, 10)
