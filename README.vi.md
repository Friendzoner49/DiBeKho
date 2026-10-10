<div align="center">

# 📦 DiBeKho

[English](README.md) · **Tiếng Việt**

**Theo dõi tồn kho tự động từ các file phiếu giao hàng Excel: chạy ngay trên máy, không cần internet, chi phí 0₫.**

[![Windows 10 | 11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)](https://github.com/Friendzoner49/DiBeKho/releases/latest/download/DiBeKho-windows-setup.exe)
[![macOS 13+](https://img.shields.io/badge/macOS-13%2B%20Apple%20Silicon-000000?logo=apple&logoColor=white)](https://github.com/Friendzoner49/DiBeKho/releases/latest/download/DiBeKho-mac-arm64.dmg)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-Qt%206.10-41CD52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![SQLite](https://img.shields.io/badge/SQLite-local-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)

<img src="docs/images/ton-kho.png" alt="Màn hình Tồn kho" width="860">

</div>

---

## Giới thiệu

DiBeKho là app desktop dành cho doanh nghiệp nhỏ bán vật liệu chống thấm. Ngày nào doanh nghiệp cũng tạo **phiếu giao hàng bằng Excel**, và trước đây họ phải tự trừ tồn kho bằng tay.

Với DiBeKho, bạn chỉ cần bỏ file phiếu vào một thư mục. App tự đọc phiếu, trừ tồn, ghi lại đơn hàng và khách hàng, rồi lập thống kê. Không cần nhập lại dữ liệu và không cần máy chủ.

> **Không lưu giá tiền.** App chỉ quan tâm đến *số lượng*: hàng nào còn bao nhiêu, ai mua gì, bán chạy mặt hàng nào.

## Tính năng

| | |
|---|---|
| 📂 **Đọc phiếu giao hàng tự động** | Đọc mọi file `.xlsx` trong thư mục, kể cả thư mục con. Nhận ra nhãn trên phiếu dù vị trí ô bị lệch. Mỗi phiếu chỉ được tính một lần, dù đổi tên hay chuyển chỗ file. |
| 🧠 **Tự học tên hàng** | Tên trên phiếu khác tên trong danh mục? App gợi ý mặt hàng khớp nhất (dựa vào tên tiếng Trung, mã model, quy cách) và nhớ lựa chọn của bạn cho các phiếu sau. |
| ✂️ **Bỏ dòng phí** | Phí ship, phí dịch vụ… được nhận ra và bỏ qua chỉ với một cú bấm, không làm sai tồn kho. |
| ↩️ **Sửa được khi chọn nhầm** | Đọc lại một phiếu, hoặc "quên" một lựa chọn ghép tên rồi chọn lại. Lịch sử cũ vẫn được giữ. |
| 🛡️ **An toàn với file** | Lỡ xoá file phiếu thì tồn kho không đổi, và app cho chọn *khôi phục*, *huỷ phiếu* hoặc *bỏ qua*. Sửa phiếu thì app hỏi dùng bản mới hay giữ bản cũ. |
| 📥 **Nhập hàng về** | App tạo sẵn file Excel mẫu, bạn chỉ điền số lượng rồi bỏ vào thư mục `input/`. |
| 🔢 **Kiểm kê** | Nhập số đếm thực tế, app ghi phần chênh lệch. Lần kiểm kê đầu tiên chính là tồn đầu kỳ. |
| 🔎 **Tra cứu mọi thứ** | Tìm mặt hàng, khách, số điện thoại, mã phiếu, ghi chú. Gõ không dấu hoặc tiếng Trung đều được. |
| 📊 **Thống kê và xuất Excel** | Theo ngày, tháng, quý, năm hoặc khoảng tự chọn; tất cả hoặc chọn riêng mặt hàng, nhóm hàng, khách. Có tồn đầu, nhập, xuất, tồn cuối, top bán chạy và biểu đồ. |
| 👥 **Đơn hàng và khách hàng** | Xem chi tiết từng đơn và mở được file gốc. Với mỗi khách, xem họ hay mua những mặt hàng nào. |
| 🔁 **Chuyển máy** | Xuất toàn bộ dữ liệu thành một file `.dibekho` để máy khác làm tiếp. |
| 💾 **Sao lưu tự động** | Mỗi ngày một bản, giữ 14 bản gần nhất; khôi phục bằng một cú bấm. |
| 🌐 **Tiếng Việt và tiếng Anh** | Đổi trong Cài đặt. Gõ được tiếng Trung ở mọi ô nhập. |

## Ảnh màn hình

<table>
  <tr>
    <td width="50%"><img src="docs/images/can-xu-ly.png" alt="Cần xử lý"><br><b>Cần xử lý:</b> ghép tên hàng lạ, bỏ dòng phí ship</td>
    <td width="50%"><img src="docs/images/tra-cuu.png" alt="Tra cứu"><br><b>Tra cứu:</b> tìm không dấu trong mọi thông tin</td>
  </tr>
  <tr>
    <td><img src="docs/images/thong-ke.png" alt="Thống kê"><br><b>Thống kê:</b> nhập, xuất, tồn theo kỳ, xuất ra Excel</td>
    <td><img src="docs/images/chi-tiet-khach.png" alt="Chi tiết khách"><br><b>Chi tiết khách:</b> mặt hàng hay mua, các đơn đã đặt</td>
  </tr>
</table>

<sub>Ảnh dùng dữ liệu giả lập (<code>scripts/readme_screenshots.py</code>), không phải dữ liệu khách hàng thật.</sub>

## Cách hoạt động

```mermaid
flowchart LR
    A["📄 Phiếu giao hàng .xlsx<br/>phieu-giao-hang/"] -->|quét, đọc theo nhãn| C{DiBeKho}
    B["📥 File hàng về / gói dữ liệu<br/>input/"] --> C
    C -->|mỗi thay đổi = 1 dòng biến động| D[("SQLite<br/>data/kho.sqlite")]
    D --> E["📊 Tồn kho · Tra cứu · Thống kê"]
    E -->|xuất| F["📁 output/<br/>báo cáo Excel, gói .dibekho"]
```

Toàn bộ dữ liệu nằm trong **một thư mục làm việc**, mặc định là `Documents/DiBeKho`:

```
DiBeKho/
├── phieu-giao-hang/   ← bỏ file phiếu giao hàng vào đây (chia thư mục con tuỳ ý)
├── input/             ← file hàng về, hoặc gói dữ liệu từ máy khác
│   └── da-xu-ly/      ← app tự chuyển file đã xử lý vào đây
├── output/            ← báo cáo Excel, file mẫu hàng về, gói dữ liệu
├── sao-luu/           ← bản sao lưu tự động
└── data/              ← database và bản sao file phiếu gốc (không sửa tay)
```

**Nguyên tắc sổ cái:** app không bao giờ sửa trực tiếp con số tồn kho. Mọi thay đổi (giao hàng, hàng về, kiểm kê, huỷ phiếu) là một dòng *biến động*, và **tồn = tổng các biến động**. Nhờ vậy mọi con số đều truy được nguồn gốc. Huỷ phiếu là ghi thêm biến động ngược, không xoá lịch sử.

## Cài đặt (người dùng)

Bấm nút **Windows** hoặc **macOS** ở đầu trang để tải (luôn là bản mới nhất), hoặc xem mọi bản ở mục [**Releases**](https://github.com/Friendzoner49/DiBeKho/releases). Repo đang để private nên cần đăng nhập GitHub có quyền xem repo mới tải được.

| | Cách cài | Lần đầu mở |
|---|---|---|
| **macOS** (Apple Silicon, macOS 13+) | Mở `DiBeKho-x.y.z-mac-arm64.dmg`, kéo **DiBeKho** vào **Applications** | Bị chặn vì app chưa ký số: *Cài đặt hệ thống → Quyền riêng tư & Bảo mật → **Vẫn mở***. Cho phép truy cập Documents. |
| **Windows** 10/11 | Chạy `DiBeKho-x.y.z-windows-setup.exe` (hoặc giải nén bản portable) | Nếu SmartScreen cảnh báo: *Thông tin thêm → **Vẫn chạy*** |

Cập nhật bản mới: cài đè lên bản cũ. Dữ liệu trong `Documents/DiBeKho` được giữ nguyên.

**Gỡ cài đặt:**
- **Windows:** *Settings → Apps → DiBeKho → Uninstall*. Trình gỡ sẽ hỏi có xoá thư mục dữ liệu không.
- **macOS:** trong app vào *Cài đặt → Gỡ app khỏi máy này*, sau đó kéo app vào Thùng rác.

## Phát triển

Cần [**uv**](https://docs.astral.sh/uv/). uv tự tải Python 3.13 và mọi thư viện vào `.venv/` của dự án, không đụng tới Python của hệ thống.

```bash
uv sync                 # cài môi trường
uv run dibekho          # chạy app từ mã nguồn
uv run pytest -q        # chạy test
uv run ruff check src tests --select F,E9
```

### Build

| Nền tảng | Lệnh | Kết quả |
|---|---|---|
| Windows | `powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1` | `dist/DiBeKho-x.y.z-windows-setup.exe` (cần [Inno Setup 6](https://jrsoftware.org/isinfo.php)), nếu không có thì ra bản `-portable.zip` |
| macOS | `bash packaging/build_mac.sh` | `dist/DiBeKho-x.y.z-mac-arm64.dmg` |
| GitHub | Đẩy tag `v*` (vd. `git tag v0.1.1 && git push origin v0.1.1`) | Cả hai bản trên, tự đăng lên **Releases** (nút tải ở đầu README trỏ vào đây) |

PyInstaller không build chéo được: bản Mac phải build trên Mac (hoặc trên máy Mac của GitHub Actions). Mỗi script build đều chạy test trước, sau đó chạy `DiBeKho --self-test` trên bản đã đóng gói. Chi tiết xem [docs/chay-thu-va-build.md](docs/chay-thu-va-build.md).

### Cấu trúc mã nguồn

```
src/dibekho/
├── app.py          # điểm khởi động, màn hình chào lần đầu, --self-test
├── db/             # kết nối SQLite, migrations/NNN_*.sql
├── core/           # nghiệp vụ: tồn kho, quét thư mục, danh mục, thống kê, chuyển dữ liệu, sao lưu
├── excel/          # đọc phiếu giao hàng, danh mục, file hàng về; xuất báo cáo
├── ui/             # giao diện PySide6, mỗi màn hình một file
└── i18n/           # vi.json, en.json
tests/              # pytest: bộ đọc Excel, logic tồn, chuyển dữ liệu, mở mọi màn hình
packaging/          # PyInstaller spec, script build Windows/macOS, Inno Setup
scripts/            # công cụ phụ (tạo ảnh cho README)
```

`core/`, `excel/` và `db/` **không import Qt**, nên toàn bộ nghiệp vụ được test bằng pytest mà không cần mở cửa sổ. Quy ước làm việc và mọi quyết định thiết kế nằm trong [CLAUDE.md](CLAUDE.md).

## Dữ liệu và quyền riêng tư

- Dữ liệu chỉ nằm trên máy người dùng. App không gửi gì lên internet.
- File Excel thật của khách hàng (có tên, số điện thoại) **không bao giờ được commit**: `samples/` và các file `*.xlsx` ở thư mục gốc đã nằm trong `.gitignore`. Test dùng phiếu giả lập; các test cần file thật sẽ tự bỏ qua khi không có file.

---

<div align="center">
<sub>Làm bằng Python + PySide6 · dữ liệu nằm trên máy của bạn</sub>
</div>
