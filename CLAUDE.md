# Brief dự án: DiBeKho — app theo dõi tồn kho chạy trên máy (Windows + macOS, Python + PySide6)

> File này là nguồn sự thật của dự án, đọc đầu tiên ở mọi session.
> Ngôn ngữ trao đổi: tiếng Việt. Giao diện app: **tiếng Việt (mặc định) + tiếng Anh + tiếng Trung giản thể**. Ngôn ngữ code, tên biến, commit: tiếng Anh.
> **Quy tắc bắt buộc:** sau mỗi lần trả lời người dùng, cập nhật những điểm quan trọng (quyết định, phát hiện, câu hỏi mới/đã trả lời) vào file này, và ghi một dòng vào **Nhật ký quyết định** (mục 15).

## 1. Bối cảnh

- **Khách hàng:** một công ty vật liệu chống thấm (tên và thông tin khách không ghi trong repo). Bán vật liệu chống thấm: sơn, màng SBS, màng PPE/PPP, vải polyester, keo, bột…
- **Tên app: DiBeKho** (thư mục làm việc `Documents/DiBeKho`, gói dữ liệu `.dibekho`, package Python `dibekho`).
- Khoảng **30 sản phẩm**, khoảng **2 phiếu giao hàng/ngày**, hàng về **1–2 lần/quý**.
- Hiện khách theo dõi tồn bằng Excel và đối chiếu thủ công với kho, dựa trên các file phiếu giao hàng.
- **Yêu cầu đã đổi (10/10/2026, sau khi thảo luận với khách):** không còn hệ thống nhiều máy dùng chung trên internet. Thay vào đó là **một app desktop chạy riêng trên từng máy**, dữ liệu nằm ngay trên máy đó, **chi phí 0₫**.
- Máy cần chạy: **Windows** và **macOS chip Apple M3** (của khách).
- Dự án độc lập với luận án tốt nghiệp (nghiên cứu WMS làm sau trong `02-nghien-cuu-huong-phat-trien-wms.md`).
- Người phát triển (người dùng) đồng hành lâu dài, tự bảo trì và mở rộng; **đã làm app desktop Java/JavaFX (mục 17) và đã từng build app bằng Python**; có Windows (máy chính) và **Mac M2** (thử và build bản Mac), chưa làm app loại này bao giờ → ưu tiên đơn giản, dễ sửa.

## 2. Thuật ngữ

| Người dùng/khách gọi | Thực chất | Tên trong app | Tên trong code |
|---|---|---|---|
| "Phiếu nhập" (các file phiếu `.xlsx` của khách) | **销售单 PHIẾU GIAO HÀNG**: hàng giao cho khách, làm **giảm** tồn | Phiếu giao hàng | `delivery` |
| Hàng về / nhập số lượng hàng về | Hàng về kho, làm **tăng** tồn (1–2 lần/quý) | Phiếu hàng về | `receipt` |
| Dữ liệu xuất từ máy khác | Gói toàn bộ dữ liệu của app để máy khác làm tiếp | Gói dữ liệu | `data package` |
| Đối chiếu với kho | Đếm thực tế, ghi chênh lệch | Kiểm kê | `stock count` |

## 3. Yêu cầu (phạm vi giai đoạn 1)

1. **Đọc thư mục phiếu giao hàng:** app đọc **tất cả file Excel** phiếu giao hàng trong một thư mục (kể cả thư mục con), mỗi phiếu làm giảm tồn. Phiếu đã đọc không bị tính lại.
2. **Hiển thị tồn kho hiện tại** của từng mặt hàng.
3. **Thư mục `input`** có 2 chức năng:
   - **Nhập hàng về** (1–2 lần/quý): bỏ file Excel hàng về (theo mẫu do app tạo) vào → tồn tăng.
   - **Nhận dữ liệu từ máy khác:** bỏ gói dữ liệu xuất từ máy khác vào → máy này **làm tiếp** từ dữ liệu đó.
4. **Database tự tạo trên máy** khi mở app lần đầu, không cần cài gì thêm.
5. **Xuất dữ liệu** thành một file để máy khác tiếp tục sử dụng.
6. **Tra cứu:** tìm mặt hàng, khách, mã phiếu, ghi chú; xem lịch sử vào/ra.
7. **Đơn hàng (phiếu giao hàng):** danh sách tất cả phiếu, lọc theo thời gian/khách/mặt hàng; **xem chi tiết từng đơn** (khách, ngày, các dòng hàng, ghi chú, file gốc). **Chi tiết khách hàng:** các đơn của khách, **những mặt hàng khách hay mua** (tổng số lượng, số lần mua, lần mua gần nhất).
8. **Thống kê theo kỳ: ngày / tháng / quý / khoảng tự chọn**, phạm vi **tất cả hoặc chọn cụ thể** (mặt hàng, nhóm hàng, khách): tồn đầu – nhập – xuất – tồn cuối; mặt hàng xuất nhiều nhất.
9. **Xuất thống kê ra Excel** theo đúng kỳ và phạm vi người dùng chọn (mục 11.1).
10. **Các chức năng hỗ trợ (đã duyệt 10/10/2026):** ghép tên hàng lạ, xử lý phiếu bị sửa, huỷ phiếu, kiểm kê, sao lưu tự động. **Không có mật khẩu** khi mở app.
11. **Không lưu và không hiển thị giá tiền.**
12. **Ba ngôn ngữ giao diện:** tiếng Việt (mặc định), tiếng Anh, tiếng Trung giản thể (thêm 11/10/2026 cho người dùng Trung Quốc); đổi trong phần Cài đặt. Chỉ đổi giao diện; database, tên thư mục, dữ liệu (tên mặt hàng, đơn vị…) giữ nguyên.

### Ngoài phạm vi (không làm, nhưng không thiết kế chặn đường)

- Nhiều máy dùng chung cùng lúc, đồng bộ qua internet.
- Giá, doanh số, công nợ, hoá đơn.
- Tách tồn theo kho/văn phòng, vị trí, lô, hạn dùng.
- Quét mã vạch, app điện thoại.

## 4. Phát hiện từ dữ liệu mẫu (10/10/2026)

**3 file phiếu giao hàng mẫu** (`samples/phieu-mau-1..3.xlsx`):
- Mẫu song ngữ. Đầu phiếu có: tên khách, điện thoại, người liên hệ, mã đơn, ngày giao, địa chỉ.
- Dòng hàng: STT, tên hàng (dòng 1 tiếng Trung, dòng 2 tiếng Việt), quy cách (`20KG/thùng`, `1m*20m/ cuộn`, `Gói`…), số lượng, đơn giá, thành tiền, ghi chú. **App chỉ đọc tên, quy cách, số lượng, ghi chú; bỏ qua giá.**
- **Vị trí ô không cố định** (phiếu 1 lệch xuống 1 dòng) → đọc theo nhãn, không theo toạ độ.
- Định dạng không thống nhất: ngày `01-10-2026` / `10/09/2026`; mã đơn `74` / `076`; dấu `：` full-width; khoảng trắng thừa.
- Có dòng không phải hàng ("Phí vận chuyển") → bỏ qua.
- Ghi chú cho thấy **giao nhiều đợt**: "gửi đi 2 thùng còn lại", "mua thêm 5 cuộn" → cần hỏi khách số lượng nào là số thực xuất (mục 5).
- "Tổng số lượng" cộng lẫn thùng + cuộn + gói → vô nghĩa; thống kê theo từng mã.
- Tên hàng trên phiếu **khác** tên trong bảng tồn (`缝织聚酯标记65g` và `缝织聚酯布65g`) → cần bảng ánh xạ tên.

**File thống kê tháng 7** (`samples/danh-muc-mau.xlsx`):
- Có nhóm hàng và biến thể theo màu, loại (nguyên sinh/tái chế), thương hiệu → mỗi biến thể là một mã hàng. Dùng làm **danh mục ban đầu**.
- Cột "Tồn còn lại" **gõ tay**, không khớp với tồn đầu + nhập − xuất; cột "Tình trạng kho" **sai** (so số với chữ). Đây là lý do khách cần app.
- Bố cục tồn đầu – nhập – xuất – tồn cuối theo tháng là mẫu cho màn hình Thống kê tháng.

## 5. Câu hỏi mở

**Đã trả lời:**
- [x] Các file "phiếu nhập" là gì? → Phiếu giao hàng (hàng ra).
- [x] Hàng về bao lâu một lần? → 1–2 lần/quý, nhập qua file Excel trong thư mục `input`.
- [x] Nhiều máy? → **Không dùng chung.** Mỗi máy chạy riêng, chuyển dữ liệu bằng gói dữ liệu.
- [x] Giá tiền? → **Không cần.**
- [x] Ngôn ngữ? → Tiếng Việt (ưu tiên) + tiếng Anh.
- [x] Hệ điều hành? → Windows + macOS (Apple M3).
- [x] Có máy Mac để thử/build? → **Có, Mac M2 của người dùng** (arm64, cùng kiến trúc với M3).
- [x] Thống kê "cụ thể hoặc tất cả"? → Đúng: chọn tất cả hoặc một/nhiều mặt hàng, nhóm hàng, khách (mục 11.1).
- [x] Mật khẩu khi mở app? → **Không.**
- [x] Xuất thống kê ra Excel? → **Có**, theo ngày/tháng/quý, tất cả hoặc chọn cụ thể.
- [x] Ghép tên hàng lạ, phiếu bị sửa, huỷ phiếu, kiểm kê, sao lưu tự động? → **Làm.**
- [x] Công nghệ? → **Python + PySide6** (người dùng đã làm Python; gọn, dễ sửa, dễ gỡ trên cả 2 hệ điều hành).

**Cần hỏi (đánh dấu ⛔ là chặn việc):**
- [x] Ghi chú trên phiếu ("gửi đi 2 thùng còn lại"…)? → **Không diễn giải.** Ghi chú chỉ hiển thị; tồn luôn trừ theo cột Số lượng (10/10/2026).
- [ ] Hai máy chuyển dữ liệu cho nhau bằng cách nào (USB, Zalo, email, Google Drive)? Có chắc **chỉ một máy làm việc tại một thời điểm** không? (Xem mục 9.4.)
- [ ] Thư mục phiếu giao hàng nằm ở đâu, có chia thư mục con theo tháng không? Có nằm trong Google Drive/OneDrive/iCloud không?
- [ ] Có file `.xls` (Excel đời cũ) không, hay toàn bộ là `.xlsx`?
- [ ] Hàng về: nhà cung cấp có gửi file danh sách hàng không, hay khách dùng file mẫu của app?
- [ ] Ngày bắt đầu dùng app → kiểm kê ngày đó làm tồn đầu. Có cần nhập lại phiếu cũ (tháng 8–9) để xem thống kê quá khứ không?
- [x] Danh mục mặt hàng? → **File thống kê tháng 7 của khách (`samples/danh-muc-mau.xlsx`) chứa toàn bộ mặt hàng** (41 dòng, tính cả biến thể). Người dùng sẽ bổ sung sau nếu cần.
- [x] Phiên bản macOS? → Máy khách: **Mac M3, macOS Tahoe 26.6.2**. PySide6 6.10 (Qt 6.10 hỗ trợ macOS 26) cần macOS 13+ → đủ. Vẫn nên thử bản build trên máy khách.
- [ ] Máy Windows của khách là Windows 10 hay 11? (bản build là x64)

## 6. Người dùng

Một máy, một người dùng tại một thời điểm. **Không có đăng nhập/phân quyền** ở giai đoạn 1 (có thể thêm mã PIN nếu khách muốn).

## 7. Kiến trúc (chốt 10/10/2026)

**App desktop Python + PySide6 (Qt)**, đóng gói bằng PyInstaller thành:
- Windows: bộ cài `.exe` (Inno Setup) có trình gỡ cài đặt trong "Apps & features".
- macOS: file `.dmg`, kéo app vào Applications. Build trực tiếp trên **Mac M2 của người dùng** (arm64, chạy được trên M3 của khách).

```
Máy của khách
├── App "DiBeKho" (một tiến trình Python duy nhất)
│   ├── ui/        giao diện PySide6: tồn kho, tra cứu, thống kê, cài đặt
│   ├── core/      nghiệp vụ: tồn kho, quét thư mục, chuyển dữ liệu, sao lưu
│   ├── excel/     đọc phiếu giao hàng, đọc file hàng về (openpyxl)
│   └── db/        SQLite (sqlite3 có sẵn trong Python)
│
├── Thư mục làm việc — MẶC ĐỊNH Documents/DiBeKho (đổi được trong Cài đặt)
│   ├── phieu-giao-hang/     ← bỏ các file phiếu giao hàng .xlsx vào đây (được chia thư mục con)
│   │   └── da-xu-ly/        ← app chuyển phiếu đã ghi xong vào đây (từ 11/10/2026)
│   ├── input/               ← bỏ file hàng về HOẶC gói dữ liệu từ máy khác vào đây
│   │   └── da-xu-ly/        ← app tự chuyển file đã xử lý vào đây
│   ├── output/              ← gói dữ liệu để chuyển máy, file mẫu hàng về, báo cáo
│   ├── sao-luu/             ← bản sao lưu tự động (giữ 14 bản)
│   └── data/                ← kho.sqlite + app.log (KHÔNG sửa tay)
│
└── File cấu hình rất nhỏ (chỉ ghi đường dẫn thư mục làm việc + ngôn ngữ)
      Windows: %APPDATA%\DiBeKho\config.json
      macOS:   ~/Library/Application Support/DiBeKho/config.json
```

**Nguyên tắc "gọn và dễ dọn":** mọi dữ liệu nằm trong **một thư mục làm việc** người dùng nhìn thấy được. Ngoài thư mục đó app chỉ để lại chính nó và một file `config.json` vài chục byte.
- **Gỡ trên Windows:** "Apps & features" → Gỡ. Trình gỡ xoá app + `config.json`, rồi hỏi "Xoá luôn thư mục dữ liệu?" (mặc định: không).
- **Gỡ trên macOS:** Cài đặt → "Gỡ app…" (xoá `config.json`, tuỳ chọn xoá thư mục dữ liệu) → app **tự xoá `DiBeKho.app`** sau khi đóng (`core/uninstall.py`: tiến trình `/bin/sh` tách riêng chờ PID thoát rồi `rm -rf`). Không tự xoá khi chạy từ `.dmg` (`/Volumes/`) hoặc thư mục không ghi được → nhắc kéo vào Thùng rác.
- **Không dùng PyInstaller `--onefile`**: chế độ này giải nén vào thư mục tạm mỗi lần chạy và có thể để lại rác khi app bị tắt đột ngột. Dùng `--onedir` (Windows) và `.app` bundle (macOS).
- **Thư mục làm việc nằm trong OneDrive/iCloud/Google Drive:** app phát hiện và cảnh báo (đồng bộ đám mây có thể làm hỏng file SQLite đang mở); khuyên để `data/` ở thư mục không đồng bộ.

**Chi phí: 0₫.** Không server, không tài khoản trả phí.

**Phát hành cho khách — máy khách không cần công cụ gì:**
- **Không build trên máy khách.** Người dùng build trên Mac M2 của mình (vài phút) → ra file `.dmg` → gửi khách (Zalo/USB/Drive).
- PyInstaller đóng gói sẵn Python, PySide6, openpyxl vào trong app → máy khách **không cần cài Python** hay bất kỳ thứ gì.
- Khách: mở `.dmg` → kéo app vào Applications → mở lần đầu bấm "Vẫn mở" (~2 phút, chỉ lần đầu). Cập nhật bản mới: kéo đè app cũ, dữ liệu trong `Documents/DiBeKho` giữ nguyên.
- **Ràng buộc phiên bản macOS:** app build trên máy có macOS mới có thể không chạy trên macOS cũ hơn, và PySide6 (Qt 6) chỉ hỗ trợ macOS từ một phiên bản nhất định trở lên. → Cần biết **phiên bản macOS trên máy khách** (mục 5); nếu cần, đặt `MACOSX_DEPLOYMENT_TARGET` và chọn phiên bản PySide6 phù hợp, và thử trên máy khách ngay ở bước B1.

**Lưu ý khi cài đặt (vì không mua chứng chỉ ký số):**
- **macOS:** PyInstaller tự ký ad-hoc (bắt buộc với chip Apple Silicon), nhưng app chưa được Apple công chứng → lần đầu mở bị chặn. Cách mở: *Cài đặt hệ thống → Quyền riêng tư & Bảo mật → "Vẫn mở"* (một lần). macOS cũng hỏi quyền truy cập thư mục Documents (bấm Cho phép). Bỏ được bước này nếu đăng ký Apple Developer Program (99$/năm), để sau nếu cần.
- **Windows:** SmartScreen có thể cảnh báo → *"Thông tin thêm" → "Vẫn chạy"*.
- Ghi các bước này vào hướng dẫn cài đặt kèm ảnh.

## 8. Công nghệ và công cụ

### Công nghệ

| Thành phần | Công nghệ | Lý do |
|---|---|---|
| Ngôn ngữ | **Python 3.13** + SQL | Người dùng đã làm Python; một ngôn ngữ cho cả app |
| Giao diện | **PySide6** (Qt for Python, giấy phép LGPL) | Giao diện native trên Windows và macOS; có sẵn bảng, form, chọn ngày; không dùng PyQt6 vì giấy phép GPL |
| Biểu đồ | `QtCharts` (đi kèm PySide6) | Không thêm thư viện |
| Database | **SQLite** qua `sqlite3` (có sẵn trong Python) | Không cài thêm gì; SQL thuần |
| Migration | File `migrations/NNN_*.sql`, chạy khi mở app, ghi phiên bản vào `PRAGMA user_version` | Không cần ORM |
| Đọc/ghi Excel | **openpyxl** (`.xlsx`) | Đã thử đọc đúng 4 file mẫu của khách; đọc được giá trị công thức đã tính (`data_only=True`) |
| Tìm không dấu | Hàm `unaccent()` viết bằng Python, đăng ký vào SQLite bằng `conn.create_function` | Không cần extension |
| Đa ngôn ngữ | File `i18n/vi.json`, `i18n/en.json`, `i18n/zh.json` + hàm `t("key")`; đổi ngôn ngữ → mở lại cửa sổ | Đơn giản hơn Qt Linguist |
| Quản lý môi trường | **uv** (`pyproject.toml` + `uv.lock`, môi trường trong `.venv/` của dự án) | Cùng lệnh trên Win/Mac; xoá `.venv/` là sạch, không cài gì vào Python hệ thống |
| Đóng gói | **PyInstaller** (`--onedir`, file `.spec` lưu trong git) | Hỗ trợ PySide6 sẵn; không build chéo được → build Windows trên máy Windows, build Mac trên Mac M2 |
| Bộ cài Windows | **Inno Setup** (miễn phí) | Có trình gỡ cài đặt chuẩn |
| Bộ cài macOS | `hdiutil` (có sẵn trên macOS) tạo `.dmg` | Không cài thêm |
| Kiểm thử | **pytest** (bộ đọc Excel, logic tồn với SQLite `:memory:`, xuất/nhập gói) + `pytest-qt` cho vài màn hình chính (làm sau) | |
| CI (tuỳ chọn) | GitHub Actions chạy pytest trên `windows-latest` và `macos-14` | Phát hiện lỗi chỉ xảy ra trên một hệ điều hành |

**Kích thước thực tế (build 10/10/2026, Windows):** thư mục app 91MB, file zip 35MB, build ~1 phút. Đã loại opengl32sw, Qt Quick/Qml/Pdf trong `.spec`. Bản Mac chưa build.

**Đã cân nhắc và không chọn:**

| Phương án | Lý do không chọn |
|---|---|
| Electron + React | Nặng (~150MB), hai tiến trình + IPC, `node_modules` lớn; người dùng phải học TypeScript |
| Tauri + React | Nhẹ nhất (~10MB) nhưng phải học Rust + TypeScript |
| JavaFX | Người dùng quen, nhưng đóng gói Mac bằng `jpackage` + module system hay vướng |
| Python + Tkinter | Nhẹ hơn (~25MB) nhưng bảng dữ liệu và giao diện kém, khó làm đẹp |
| Python + Flet | Giao diện hiện đại nhưng còn mới, build cần thêm Flutter SDK |

### Công cụ phát triển

| Việc | Windows (máy chính) | Mac M2 (thử + build bản Mac) |
|---|---|---|
| Soạn code | VS Code (extension Python, Ruff) + Claude Code | VS Code (tuỳ chọn) |
| Python + môi trường | `uv` (tự tải Python 3.13 vào thư mục của uv) | `uv` |
| Mã nguồn | Git + GitHub (private) | Git (Xcode Command Line Tools) |
| Xem database | DB Browser for SQLite | DB Browser for SQLite |
| Bộ cài | Inno Setup | `hdiutil` (có sẵn) |
| Thiết kế màn hình (tuỳ chọn) | Qt Designer (`pyside6-designer`, có sẵn trong PySide6) | |

Quy trình: viết code trên Windows → push GitHub → trên Mac `git pull` → `uv run pytest` → `uv run pyinstaller dibekho.spec` → thử app.

### Cấu trúc repo

```
dibekho/
├── CLAUDE.md
├── README.md                  # giới thiệu cho GitHub, TIẾNG ANH (mặc định, ảnh docs/images/en/)
├── README.vi.md               # bản tiếng Việt (ảnh docs/images/)
├── README.zh.md               # bản tiếng Trung (ảnh docs/images/zh/); sửa README thì sửa cả ba
├── pyproject.toml / uv.lock
├── packaging/
│   ├── dibekho.spec           # cấu hình PyInstaller (chung Win/Mac)
│   ├── launcher.py
│   ├── build_windows.ps1      # test → PyInstaller → --self-test → Inno Setup (hoặc zip portable)
│   ├── build_mac.sh           # test → PyInstaller → --self-test → .dmg
│   └── windows.iss            # Inno Setup (cài theo user, không cần quyền admin)
├── docs/chay-thu-va-build.md  # chạy, build, cài trên máy khách
├── .github/workflows/build.yml  # GitHub Actions: build .dmg (macos-15, arm64) + bộ cài Windows, tải ở mục Artifacts
├── src/dibekho/
│   ├── app.py                 # điểm khởi động
│   ├── db/                    # kết nối, migrations/*.sql, truy vấn
│   ├── excel/                 # đọc phiếu giao hàng, file hàng về, tạo mẫu, xuất báo cáo
│   ├── core/                  # tồn kho, quét thư mục, chuyển dữ liệu, sao lưu, đường dẫn hệ điều hành
│   ├── ui/                    # main_window, *_page.py (mỗi màn hình một file), details.py (chi tiết đơn/khách/mặt hàng)
│   └── i18n/                  # vi.json, en.json
├── tests/
├── resources/                 # dibekho.svg (logo tự vẽ, gốc) → .png/.ico/.icns bằng scripts/make_icons.py
├── scripts/readme_screenshots.py  # tạo lại ảnh docs/images/ (vi) và docs/images/en/ (en) từ dữ liệu giả lập
├── scripts/make_reference_excel.py  # tạo DiBeKho-du-lieu-goc.xlsx (gitignored) để đối chiếu app
└── samples/                   # file Excel mẫu của khách (cho test, gitignored, KHÔNG commit)
```

**Tách lớp như dự án Java cũ:** `db/` ≈ DAO, `core/` ≈ service, `ui/` ≈ View. Giao diện không viết SQL trực tiếp; `core/` và `excel/` không import Qt → test được bằng pytest mà không cần mở cửa sổ.

## 9. Mô hình dữ liệu và cơ chế

### 9.1. Bảng (SQLite)

Nguyên tắc: **tồn kho không bao giờ được sửa trực tiếp.** Mọi thay đổi là một dòng trong `stock_movements`. **Tồn = tổng `stock_movements`** (tính trực tiếp bằng SQL; dữ liệu nhỏ nên không cần bảng cache).

- `products`: `id`, `code`, `name_vi`, `name_zh`, `spec` (quy cách), `variant` (loại/màu: Trắng, Xám nhạt, Nguyên sinh, Tái chế, Hiệu Thụy Đức… — migration 002), `unit` (thùng/cuộn/gói), `category`, `min_stock` (ngưỡng cảnh báo), `active`.
- `product_aliases`: `key` (tên + quy cách đã chuẩn hoá trên phiếu) → `product_id`. App "học" mỗi khi người dùng chọn mặt hàng cho một dòng lạ.
- `customers`: tên, người liên hệ, SĐT (chuẩn hoá), địa chỉ — lấy từ phiếu giao hàng, phục vụ tra cứu.
- `documents`: `id`, `kind` (`delivery` | `receipt` | `stock_count`), `code` (mã phiếu), `doc_date` (ngày nghiệp vụ), `customer_id`, `note`, `status` (`active` | `cancelled`), `source_file` (tên file), `source_hash`, `created_at`.
- `document_lines`: `document_id`, `product_id`, `qty`, `note`.
- `stock_movements`: `product_id`, `qty` (+/−), `document_id`, `occurred_on` (= `doc_date`), `kind`, `created_at`. Để sẵn `lot_id`, `location_id` nullable cho tương lai.
- `scanned_files`: `path`, `hash` (SHA-256 nội dung), `status` (`imported` | `error` | `needs_mapping` | `duplicate` | `changed` | `missing` | `missing_ignored`), `message`, `scanned_at`.
- `ignored_lines` (migration 003): `key` (cùng khoá với `product_aliases`) → dòng **không phải hàng hoá** (phí vận chuyển, phí dịch vụ…), `label`. Dòng này bị bỏ khi đọc mọi phiếu, không ảnh hưởng tồn.
- `meta`: `device_id`, `device_name`, `last_export_at`, `last_import_from`, `data_version`.
- `app_log`: nhật ký thao tác quan trọng (nhập, huỷ, kiểm kê, xuất/nhập gói).

Mỗi lần nhập một file = **một transaction**: lỗi giữa chừng thì không ghi gì.

### 9.2. Quét thư mục phiếu giao hàng

- Quét khi mở app và khi bấm **"Quét lại"** (có thể thêm tự theo dõi thư mục sau).
- Mỗi file `.xlsx`: tính hash →
  - hash đã có → bỏ qua;
  - mã phiếu mới → đọc, tạo `delivery`, trừ tồn;
  - **mã phiếu đã có nhưng nội dung khác** (file bị sửa) → đánh dấu `changed`, hỏi người dùng "Thay bằng bản mới?";
  - dòng hàng chưa nhận ra → `needs_mapping`, người dùng chọn mặt hàng, tạo mặt hàng mới, hoặc **"✕ Bỏ dòng" (không phải hàng hoá)**, rồi nhập tiếp. Dòng trông giống phí (`Phí…`, ship, vận chuyển, dịch vụ, 运费, 服务费…) được chọn sẵn "bỏ dòng". Dòng đã bỏ được nhớ trong `ignored_lines`; xem/bỏ khỏi danh sách ở Cài đặt → Danh mục mặt hàng.
- **Không sửa nội dung file phiếu.** ~~Không di chuyển file phiếu~~ → **từ 11/10/2026 (người dùng yêu cầu):** phiếu đã ghi xong (`imported`, hoặc `ignored` có `document_id` = giữ bản cũ) được chuyển vào `phieu-giao-hang/da-xu-ly/` (giữ thư mục con) để nhìn thư mục biết phiếu nào chưa xong; phiếu cần quyết định lại (vd. Quên và đọc lại) được chuyển ra ngoài. `deliveries.sort_files` chạy cuối mỗi lần quét; file đang mở (Windows) không chuyển được thì để lần quét sau. Quét vẫn đọc cả `da-xu-ly/` (theo hash, không đọc trùng).
- **Bản sao file gốc:** mỗi file đọc thành công được chép một bản vào `data/phieu-goc/<hash>.xlsx` (~15KB/file, ~10MB/năm). Nút "Mở file gốc" mở bản này nên vẫn hoạt động khi file trong thư mục bị xoá/đổi tên/di chuyển. Bản sao đi kèm trong gói dữ liệu chuyển máy.
- **Lỡ xoá file khỏi `phieu-giao-hang/`:**
  - Tồn, đơn hàng, thống kê **không thay đổi** (database là nguồn sự thật, file chỉ là đầu vào).
  - Lần quét sau, app phát hiện file biến mất → mục **Cần xử lý** hiện "N phiếu không còn file trong thư mục" với 3 lựa chọn: **Khôi phục file** (chép bản sao về đúng chỗ cũ) · **Huỷ phiếu** (trả lại tồn, giữ lịch sử) · **Bỏ qua** (giữ nguyên, không hỏi lại).
  - Bỏ lại đúng file đó vào thư mục → hash đã biết → không trừ lần hai.
  - **Đổi tên hoặc chuyển file sang thư mục con khác** → app nhận ra cùng hash, chỉ cập nhật đường dẫn, không coi là xoá.
- **Làm lại (chọn nhầm khi Áp dụng):**
  - **Đọc lại phiếu** (Chi tiết đơn): phiếu cũ → `replaced` (đảo biến động, giữ lịch sử), xoá dòng `scanned_files` của hash đó, quét lại → đọc với danh mục/ghép tên hiện tại. File đã bị xoá thì chép lại từ `data/phieu-goc/`.
  - **Quên và đọc lại** (Cài đặt → Danh mục mặt hàng → "Tên trên phiếu đã học"): xoá ghép tên (`product_aliases`) hoặc dòng bỏ qua (`ignored_lines`), đọc lại mọi phiếu đang hiệu lực có dòng đó → phiếu hiện lại trong Cần xử lý. Phiếu chứa dòng bị bỏ được tìm qua `document_skipped_lines` (migration 004); `product_aliases.label` lưu tên dễ đọc.
  - **Phiếu duyệt một phần (10/10/2026):** bấm **Áp dụng** (`scan(allow_partial=True)`) → phiếu có ít nhất một dòng đã biết được ghi vào kho với các dòng đó, khách được ghi; `scanned_files` giữ `needs_mapping` + `document_id`. Dòng "Để sau" khi được duyệt → lần quét sau thêm vào **đúng đơn đó** (`stock.add_lines`, nhận dòng theo `document_lines.line_no` = số dòng Excel). Mở app/Quét lại **không** tự ghi phiếu đang chờ (chỉ khi người dùng bấm Áp dụng). Thông tin khách chỉ vào database khi phiếu đã được duyệt (người dùng yêu cầu vì bảo mật). File phiếu một phần bị xoá → `missing` (lưu trạng thái cũ trong `message`), khôi phục → hỏi lại dòng còn thiếu.
  - Bấm "Quét lại" không đọc lại phiếu đã đọc (cùng hash). `input/da-xu-ly/` chứa file hàng về và gói dữ liệu đã nhập; phiếu giao hàng đã xong ở `phieu-giao-hang/da-xu-ly/`.
- Muốn bỏ một phiếu → bấm "Huỷ phiếu" trong app (ghi biến động đảo ngược, giữ lịch sử). Xoá file **không** phải cách huỷ phiếu.
- **Không chặn tồn âm**, vì phiếu mô tả việc đã xảy ra. Tồn âm được tô đỏ kèm gợi ý "thiếu phiếu hàng về hoặc chưa kiểm kê".

### 9.3. Thư mục `input`

App tự nhận loại file:
- **File hàng về** (`.xlsx` có tiêu đề "PHIẾU HÀNG VỀ / GOODS RECEIPT" theo mẫu): đọc ngày, các dòng mặt hàng + số lượng → hiện bản xem trước → xác nhận → tồn tăng. Mẫu được tạo bằng nút **"Tạo file mẫu hàng về"** (ghi vào `output/`); mẫu có sẵn danh sách mặt hàng, khách chỉ điền số lượng.
- **Gói dữ liệu** (`.dibekho`): xem 9.4.
- **File danh mục** (thống kê tháng) bỏ vào `input/` cũng được nhận ra (`inbox.read_item` thử `read_catalog`) → nút "Nhập danh mục từ Excel…" ngay trong Cần xử lý.
- Xử lý xong → chuyển file vào `input/da-xu-ly/` (thêm ngày giờ vào tên) để không xử lý lại và người dùng thấy rõ.
- **File không dùng được không bao giờ bị di chuyển:** chỉ có nút **Ẩn** (nhớ theo hash trong `hidden_inputs`, migration 005; nội dung đổi thì hiện lại). Nút **Bỏ** (chuyển vào `da-xu-ly`) chỉ còn cho file dùng được (hàng về, danh mục, gói dữ liệu).
- **Hàng về → "Chọn file để nhập…"**: chọn file hàng về hoặc file danh mục ở bất kỳ đâu (kể cả `da-xu-ly`); file ngoài `input/` không bị di chuyển (`inbox.done`). Chống nhập trùng hàng về theo hash vẫn giữ.

### 9.4. Chuyển dữ liệu sang máy khác

- **Xuất:** nút "Xuất dữ liệu cho máy khác" → tạo `output/DiBeKho_<tên máy>_<yyyy-MM-dd_HHmm>.dibekho` (file zip gồm bản sao SQLite + `manifest.json`: máy nguồn, thời điểm, phiên bản schema, số phiếu, số mặt hàng).
- **Nhập:** bỏ file vào `input/` của máy kia → app hiện tóm tắt (từ máy nào, lúc nào, bao nhiêu phiếu) → người dùng xác nhận → **sao lưu dữ liệu hiện tại** → thay bằng dữ liệu trong gói.
- **Quy tắc "trao tay":** tại một thời điểm chỉ một máy làm việc. Nếu máy nhận có thao tác **sau lần xuất/nhập gần nhất** mà chưa xuất đi → cảnh báo rõ "dữ liệu trên máy này sẽ bị thay thế", yêu cầu xác nhận lần hai.
- Gói chứa cả danh sách hash các file đã đọc → máy nhận quét thư mục phiếu của mình sẽ **không trừ trùng** những phiếu đã có.
- Gói có phiên bản schema cũ hơn → chạy migration sau khi nhập; mới hơn → báo "hãy cập nhật app".
- Phiếu **đang chờ** của máy cũ (`needs_mapping`/`error`/`changed`, chưa ghi vào kho) mà không có file trên máy này: lần quét đầu xoá khỏi `scanned_files` (không mất gì; chép file vào `phieu-giao-hang/` thì app hỏi lại). Trước đây chúng làm thanh bên báo "(3)" mà trang Cần xử lý trống.

### 9.4b. Dữ liệu gốc (Excel)

- **Cài đặt → Chuyển dữ liệu và sao lưu → Xuất dữ liệu gốc… / Nhập dữ liệu gốc…** (`excel/master_data.py`, `catalog.import_master`).
- File `output/DiBeKho_DuLieuGoc_<ngày giờ>.xlsx`, 3 trang (trang 3 thêm 11/10/2026), bố cục cố định (A1 bắt đầu bằng `DIBEKHO`, tiêu đề ở dòng 4, dữ liệu từ dòng 5; đọc theo **vị trí cột**, không theo tên cột → đọc được dù xuất bằng tiếng Việt hay Anh):
  - **Mặt hàng:** STT · Mã SP · Tên tiếng Việt · Tên Trung · Quy cách · Loại/màu · Đơn vị · Nhóm hàng · Ngày nhập (= `products.created_at`) · Báo sắp hết khi còn · Đang dùng.
  - **Khách hàng:** STT · Khách hàng · Điện thoại · Người liên hệ · Địa chỉ · Số đơn (đơn giao hàng đang hiệu lực; chỉ để xem, khi nhập bỏ qua). Theo yêu cầu: **không** có mã đơn, tổng SL, mặt hàng đã mua.
- Nhập: mã đã có → cập nhật theo file; mã mới → tạo đúng mã đó (giữ ngày nhập); không mã → mã kế tiếp; trùng tên+quy cách+loại với mặt hàng mang mã **không có trong file** → bỏ qua và báo (không tạo trùng). Khách khớp theo SĐT rồi theo tên, nhận giá trị trong file. Sao lưu trước khi nhập; một transaction.
  - **Tồn kho** (trang 3): giống bảng thống kê tồn kho của khách, 5 cột **Mã** (thêm 14/10/2026) · Mặt hàng (tên Việt + quy cách, dòng 2 tên Trung) · Nhóm hàng · Loại/màu · Tồn (hiện tại). Mặt hàng đang dùng, theo mã. **Từ 14/10/2026 được đọc khi nhập**: khách sửa số tồn trong trang này → Nhập dữ liệu gốc đặt tồn app đúng bằng số đó (một lần kiểm kê hôm nay, quét phiếu trước). Mỗi dòng tồn gắn với một dòng trang 1 (`MasterStock.product_row`): theo mã nếu mã không trùng; không thì theo **thứ tự dòng** (2 trang xuất cùng thứ tự, số dòng bằng nhau); không thì theo tên+nhóm+loại. File cũ chưa có cột Mã (4 cột) dùng cùng cách.
  - **Mã trùng trong trang 1** (người dùng chép dòng cho biến thể khác, giữ nguyên mã): dòng đầu giữ mã, các dòng sau là **mặt hàng mới với mã kế tiếp** (`_free_code`, tránh cả mã còn dùng phía dưới file) và được báo lại ("renumbered"). Trước đây các dòng này **ghi đè nhau** (file thật 14/10: 52 dòng → chỉ còn 45 mặt hàng). Kiểm tra trùng khi nhập dữ liệu gốc tính cả **nhóm hàng** (`find_same(..., category)`), vì người dùng phân biệt biến thể ở cột nhóm hàng.
  - **Kiểm tra trước khi nhập (14/10/2026, người dùng chọn):** dòng tồn không gắn được bằng mã duy nhất (file cũ không cột Mã, mã trùng) → hộp **Kiểm tra số tồn trước khi nhập** (`transfer_page.StockMatchDialog`): mỗi dòng tồn + mặt hàng được gán (đổi được); dòng tô vàng khi tên/nhóm/loại khác trang 1 (`master_data.stock_differs`); không cho gán một mặt hàng cho 2 dòng. Lý do: file thật của người dùng có trang 1 và trang 3 lệch thứ tự → ghép theo thứ tự dòng đổi chéo tồn của 4 mặt hàng mà tổng vẫn đúng.
  - File dữ liệu gốc bỏ vào `input/` được nhận ra (`inbox` kind `master`) → nút **Nhập dữ liệu gốc…** ở Cần xử lý; dùng chung `transfer_page.import_master_file`. Thử trên file thật của người dùng: 52/52 mặt hàng, tổng tồn 4.459 khớp, nhập lại lần 2 không tạo trùng.
- Không thay thế gói `.dibekho`: file Excel không có phiếu, lịch sử, tên đã học (chỉ có số tồn hiện tại).
- Đã thử trên dữ liệu thật: 44 mặt hàng + 3 khách khớp `DiBeKho-du-lieu-goc.xlsx` (khác biệt duy nhất: quy cách của 3 mặt hàng tạo từ phiếu giữ nguyên chữ trên phiếu, vd. `20KG/thùng`).

### 9.5. Sao lưu

- Tự sao lưu mỗi ngày khi mở app, và trước mọi thao tác nhập gói dữ liệu → `sao-luu/`, giữ 14 bản gần nhất. Dùng `conn.backup()` của `sqlite3` (an toàn khi DB đang mở).
- Nút "Khôi phục từ bản sao lưu" trong Cài đặt.

### 9.6. Tồn đầu kỳ và kiểm kê

- Lần đầu mở app: chọn ngôn ngữ + thư mục làm việc. **Danh mục tự hình thành từ phiếu giao hàng**: dòng lạ → "Tạo mặt hàng mới" (một cú bấm, lấy tên Việt/Trung/quy cách từ phiếu) hoặc ghép với mặt hàng có sẵn. Sửa tên/nhóm/ngưỡng trong Cài đặt.
- **Tồn đầu = lần kiểm kê đầu tiên** (không có loại phiếu `opening` riêng). Kiểm kê ghi theo ngày chọn: chênh lệch = số đếm − tồn tính đến hết ngày đó.
- Màn hình Kiểm kê tự quét phiếu trước khi hiện số, để phiếu đã có không bị tính hai lần.
- Màn hình **Kiểm kê**: hiện tồn theo app, người dùng nhập số đếm thực tế → app ghi phần chênh lệch (`stock_count`).
- **Tồn ban đầu của mặt hàng mới từ phiếu (14/10/2026):** Cần xử lý có cột **Tồn ban đầu** (chỉ bật khi chọn "Tạo mặt hàng mới"). Áp dụng → `create_product_for_line(opening=…)` ghi kiểm kê vào **ngày trước phiếu sớm nhất** có dòng đó (`UnknownLine.first_date`), rồi phiếu trừ tiếp. Để trống = 0.
- **Mẫu hàng về** xếp theo **mã sản phẩm** (14/10/2026).

### 9.7. Đặt lại dữ liệu (11/10/2026)

**Cài đặt → Chung → Đặt lại dữ liệu** (`core/reset.py`). Luôn sao lưu trước (`truoc-dat-lai-ton_*` / `truoc-xoa-toan-bo_*` trong `sao-luu/`), nên khôi phục được.
- **Đặt lại tồn kho (giữ mặt hàng):** giữ `products`, `product_aliases`, `ignored_lines`, `hidden_inputs`, `meta`, `app_log`; xoá `stock_movements`, `document_skipped_lines`, `document_lines`, `scanned_files`, `documents`, `customers` → tồn về 0. Chuyển mọi file trong `phieu-giao-hang/da-xu-ly/` ra `phieu-giao-hang/` rồi quét lại ngay (tên đã học → phiếu vào lại kho; còn lại chờ ở Cần xử lý). Giữ `data/phieu-goc/` (khôi phục bản sao lưu vẫn mở được file gốc).
- **Xoá toàn bộ dữ liệu:** đóng kết nối, xoá `kho.sqlite` (+ wal/shm) và `data/phieu-goc/`, mở lại → database trống như vừa cài; chỉ giữ `config.json` (ngôn ngữ, cỡ chữ, thư mục). Hỏi xác nhận 2 lần.
- Không bao giờ xoá file của người dùng (phiếu, `input/`, `output/`, `sao-luu/`). File hàng về trong `input/da-xu-ly/` không được chuyển lại; nhập lại bằng **Chọn file để nhập…** nếu cần.

## 10a. Đặc tả: Nhập danh mục từ bảng thống kê tháng

Nút **"Nhập danh mục từ Excel…"** (Cài đặt, và trên màn hình Tồn kho khi danh mục còn trống) → chọn file thống kê tháng của khách → **bảng xem trước sửa được** (tick chọn, nháy đúp sửa ô) → nhập. Mặt hàng trùng (cùng tên Việt + quy cách + loại, không phân biệt dấu) được bỏ qua → nhập lại file nhiều lần không tạo trùng. Bộ đọc: `excel/catalog_sheet.py` (hàm thuần).

Quy tắc đọc:
- Tìm dòng tiêu đề có `Tên sản phẩm` và `Phân loại`; mỗi dòng bên dưới là một mặt hàng; bỏ dòng chữ cái `A | B | C`.
- Cột tên: dòng 1 = tên Việt, các dòng sau = tên Trung.
- **Ô tên gộp nhiều dòng** (vd. A32:A33) = các biến thể của cùng mặt hàng; khi đó cột Phân loại là **biến thể** (纯原料 → Nguyên sinh, 再生料 → Tái chế, 瑞德牌 → Hiệu Thụy Đức, 纯白色 → Trắng tinh), nhóm hàng suy ra "Màng PPE/PPP (卷材)" nếu tên có PPE/PPP.
- Dòng đơn: cột Phân loại = **nhóm hàng** (涂料类 → Sơn, vữa, keo; 自粘膜 → Màng tự dính; SBS → Màng SBS; 聚酯布 → Vải polyester).
- Màu trong ngoặc cuối tên Trung (（白色）, （浅灰色）, （灰色）, （蓝色）) → biến thể (Trắng, Xám nhạt, Xám, Xanh dương), bỏ khỏi tên.
- Quy cách lấy từ tên: độ dày `1.5mm`, định lượng `65g`, khổ `1m*20m`, trọng lượng `20KG`; trọng lượng `(20KG)` được bỏ khỏi tên. Đơn vị đoán: KG → thùng, màng/vải/khổ → cuộn, 袋 → gói.
- ~~Số lượng tồn trong file không được dùng~~ → **từ 11/10/2026 (người dùng yêu cầu):** đọc **cột F "Lượng tồn kho còn lại" / 利余库存** (tìm theo nhãn) vào `CatalogItem.stock`; cột C, D, E và **G** bỏ qua. Bảng xem trước có cột "Tồn kho (cột F)" sửa được + ô tick "Ghi số tồn… tính đến ngày" (mặc định hôm nay). Nhập → `catalog.import_catalog(items, stock_date)` ghi **một lần kiểm kê** (`stock_count`) cho các dòng được tick có số tồn, kể cả mặt hàng đã có → tồn app = số trong file vào ngày đó; ô trống = không đổi. Quét phiếu trước khi ghi. Thử trên file thật tháng 7: 41 dòng, tổng 3.032 khớp cột F.
- **Không tìm thấy cột tồn theo nhãn** (file bố cục khác): trước bảng xem trước, app hiện hộp **Chọn cột số lượng tồn kho** (`excel.catalog_sheet.sheet_columns`: mỗi cột trừ cột tên/phân loại, kèm tiêu đề + 4 giá trị mẫu; mặc định "Không nhập số tồn") → `read_catalog(path, stock_col)`. Số tồn luôn lấy trên cùng dòng với mặt hàng.

**Gợi ý ghép tên phiếu → danh mục** (`catalog.suggest_product`): chỉ xét các mặt hàng có **tên Trung khớp nhiều chữ Hán nhất**, rồi chấm điểm theo mã model (FS-101 ≠ FS-102), trọng lượng (khác → nhân 0,4), khổ cuộn, độ giống tên. Không đủ điểm → đề nghị "Tạo mặt hàng mới". Kết quả trên 3 phiếu mẫu: 11/14 dòng tự ghép đúng; 3 dòng đề nghị tạo mới (冷底油 sơn lót lạnh, 背水涂 20KG, 1.5mmSBS自粘膜高分子 — người dùng tự chọn nếu đúng là SP017).

## 10. Đặc tả: Đọc file phiếu giao hàng

**Quy tắc đọc (theo nhãn, không theo toạ độ):**
- Tìm các nhãn: `Tên khách hàng`, `Điện thoại liên hệ`, `Mã đơn hàng`, `Người liên hệ`, `Ngày giao hàng`, `Địa chỉ`. Giá trị nằm sau `:`/`：` hoặc ở dòng bên dưới.
- Dòng tiêu đề bảng = dòng có `Tên hàng`; dòng hàng đọc đến dòng có `Tổng cộng`.
- Mỗi dòng hàng lấy: tên (cả 2 dòng Trung/Việt), quy cách, số lượng, ghi chú. **Bỏ qua đơn giá, thành tiền, STT.**
- Dòng không có số lượng (ví dụ "Phí vận chuyển") → bỏ qua.
- Ngày: `dd-mm-yyyy`, `dd/mm/yyyy` hoặc ô kiểu ngày. Mã đơn bỏ số 0 đầu khi so trùng (`076` = `76`).
- Ô công thức: đọc giá trị đã tính (`result`); số lượng phải là số dương, nếu không → lỗi rõ ràng kèm số dòng.
- Chuẩn hoá trước khi so khớp: bỏ khoảng trắng thừa/xuống dòng, đổi `（）` thành `()`, chữ thường. Khoá = tên + quy cách.
- Bộ đọc là **hàm thuần** (workbook → dữ liệu có cấu trúc + danh sách cảnh báo), không đụng database; có unit test trên các file trong `samples/`.
- File không phải phiếu giao hàng (không tìm thấy nhãn) → bỏ qua, ghi `error` với lý do.

## 11. Màn hình

**Thanh điều hướng (rút gọn 10/10/2026):** Tồn kho · Cần xử lý · Tra cứu · Hàng về · Kiểm kê · Cài đặt.
- **Đơn hàng, Khách hàng, Thống kê** không nằm trên thanh điều hướng mà là **nút nhỏ trong Tra cứu**, mở cửa sổ riêng (ít dùng).
- **Chuyển dữ liệu + sao lưu** là một tab của **Cài đặt** (tab: Chung · Danh mục mặt hàng · Chuyển dữ liệu và sao lưu).
- **Cần xử lý → Tên hàng chưa có trong danh mục:** mỗi dòng có cột "Có trong đơn" (mã đơn · khách · SL), ô "Là mặt hàng" gõ để tìm (tiếng Việt hoặc tiếng Trung), nút **✕ Bỏ dòng / ↺ Giữ lại**; dòng bị bỏ hiện gạch ngang.

| Màn hình | Nội dung |
|---|---|
| **Tồn kho** (màn hình đầu) | Bảng ~30 mặt hàng: tên, quy cách, tồn hiện tại; tô vàng dưới `min_stock`, đỏ khi âm; ô lọc nhanh; nút **Quét lại**; dòng trạng thái "Đã đọc N phiếu mới · M cần xử lý" |
| **Cần xử lý** | Các file lỗi, dòng hàng chưa nhận ra (chọn mặt hàng), phiếu bị sửa (thay/giữ), **phiếu không còn file trong thư mục (khôi phục/huỷ/bỏ qua)**, file hàng về chờ xác nhận, gói dữ liệu chờ nhập |
| **Tra cứu** | Một ô tìm: mặt hàng (Việt/Trung/mã/quy cách), khách (tên/SĐT/địa chỉ), mã phiếu, ghi chú; gõ không dấu vẫn ra. Bấm kết quả → mở màn hình chi tiết tương ứng |
| **Đơn hàng** | Danh sách mọi phiếu giao hàng (mới nhất trước): mã, ngày, khách, số dòng hàng, trạng thái. Lọc: khoảng ngày, khách, mặt hàng có trong đơn, trạng thái |
| **Chi tiết đơn** | Đầu phiếu: mã, ngày giao, khách, người liên hệ, SĐT, địa chỉ. Bảng dòng hàng: tên (Việt + Trung), quy cách, số lượng, ghi chú. Tên file gốc + nút **"Mở file gốc"** (mở bằng Excel/Numbers). Trạng thái, thời điểm app đọc. Nút **Huỷ phiếu**. Bấm tên khách → Chi tiết khách; bấm mặt hàng → Chi tiết mặt hàng |
| **Chi tiết khách** | Thông tin liên hệ; tổng số đơn, đơn đầu tiên, đơn gần nhất. Bảng **mặt hàng hay mua**: mặt hàng, tổng số lượng, số lần mua, lần mua gần nhất (sắp xếp theo tổng số lượng). Danh sách đơn của khách (bấm → Chi tiết đơn). Lọc theo khoảng thời gian. Nút xuất Excel |
| **Chi tiết mặt hàng** | Tồn hiện tại; lịch sử vào/ra theo ngày (phiếu nào, khách nào); khách lấy nhiều nhất |
| **Thống kê** | Chọn kỳ (mục 11.1) + phạm vi → bảng tồn đầu, nhập, xuất, tồn cuối; top mặt hàng xuất nhiều; biểu đồ xuất theo ngày/tháng; nút **"Xuất Excel"** |
| **Kiểm kê** | Nhập số đếm thực tế, xem chênh lệch, xác nhận |
| **Chuyển dữ liệu** | Xuất gói dữ liệu; hướng dẫn nhập ở máy kia; lịch sử xuất/nhập |
| **Cài đặt** | Thư mục làm việc, ngôn ngữ (VI/EN), **cỡ chữ và nút** (100–150%, mặc định 120%), danh mục mặt hàng (**Thêm / Sửa mặt hàng… / Xoá mặt hàng**, ngừng dùng, `min_stock`), tạo file mẫu hàng về, sao lưu/khôi phục, phiên bản app |

### 11.1. Thống kê và xuất Excel

**Chọn kỳ:** Ngày (một ngày) · Tháng · Quý · Năm · Khoảng tự chọn (từ ngày – đến ngày). Khi xem nhiều kỳ (ví dụ cả quý), chọn **chia theo**: ngày / tháng / không chia.

**Chọn phạm vi** (mỗi mục: Tất cả hoặc chọn một/nhiều):
- Mặt hàng · Nhóm hàng · Khách hàng (chỉ áp dụng cho số xuất, vì nhập/kiểm kê không gắn khách).

**Nội dung file Excel** (người dùng tick chọn sheet nào cần, mặc định tất cả):
1. **Tổng hợp nhập–xuất–tồn:** mỗi mặt hàng một dòng: tồn đầu kỳ, nhập, xuất, điều chỉnh kiểm kê, tồn cuối kỳ (+ cột theo từng ngày/tháng nếu chọn "chia theo"). Bố cục giống bảng tháng khách đang dùng.
2. **Chi tiết phiếu:** mỗi dòng hàng của mỗi phiếu trong kỳ: ngày, loại (giao/hàng về/kiểm kê/huỷ), mã phiếu, khách, mặt hàng, quy cách, số lượng, ghi chú.
3. **Theo khách:** khách × mặt hàng: tổng số lượng, số lần mua.
4. **Top mặt hàng xuất nhiều.**

- Tên file: `ThongKe_<kỳ>_<phạm vi>_<ngày giờ xuất>.xlsx`, lưu vào `output/`, sau đó app hỏi "Mở file?" / "Mở thư mục?".
- Dòng đầu mỗi sheet ghi rõ kỳ, phạm vi, thời điểm xuất. Tiêu đề cột theo ngôn ngữ đang chọn (VI/EN). **Không có cột giá.**
- Ngày tính theo **ngày nghiệp vụ** (ngày giao trên phiếu, ngày hàng về), không theo ngày app đọc file.
- Xuất từ màn hình Chi tiết khách / Chi tiết mặt hàng = xuất thống kê với phạm vi đã chọn sẵn khách/mặt hàng đó.

**Tìm không dấu:** đăng ký hàm Python `unaccent()` (bỏ dấu, `đ`→`d`, chữ thường, chuẩn hoá NFC) vào SQLite bằng `conn.create_function`, rồi tìm `WHERE unaccent(name_vi) LIKE unaccent(?)`. Dữ liệu nhỏ nên không cần cột/chỉ mục riêng.

## 12. Yêu cầu phi chức năng

- **Đúng số liệu:** không đọc trùng phiếu; mỗi lần nhập là một transaction; mọi thay đổi tồn có dấu vết.
- **Tin cậy:** sao lưu tự động hằng ngày + trước khi nhập gói; đã thử khôi phục.
- **Đa nền tảng:** chạy trên Windows 10/11 x64 và macOS (Apple Silicon M3); đường dẫn file dùng `path.join`, không viết cứng `\` hay `/`; tên file tiếng Việt có dấu đọc được trên cả hai hệ điều hành (chuẩn hoá Unicode NFC khi so sánh, vì macOS lưu tên file dạng NFD); `rel_path` lưu dạng NFC, mở lại file luôn qua `deliveries.note_path` vì **Windows coi tên NFD và NFC là hai file khác nhau** (file phiếu đi qua Mac/Zalo có tên NFD).
- **Hiệu năng:** quét 1.000 file phiếu dưới 1 phút; màn hình mở dưới 1 giây.
- **Nhập tiếng Trung:** mọi ô nhập nhận bộ gõ tiếng Trung (Qt hỗ trợ IME sẵn); tra cứu theo tên Trung; số gõ dạng toàn độ rộng (`１２，５`) được hiểu (`core.text.parse_number`, NFKC). Font giao diện có dự phòng chữ Hán (Windows: Microsoft YaHei; macOS tự dùng PingFang).
- **Dễ dùng:** ít bước, thông báo lỗi bằng tiếng Việt dễ hiểu, không cần kiến thức máy tính.

## 13. Lộ trình

Mỗi bước có "Xong khi". Thời gian là ước lượng cho người mới, làm bán thời gian cùng Claude Code.

### Giai đoạn A — Chuẩn bị (~1 tuần)

| Bước | Việc | Xong khi |
|---|---|---|
| A1 | Hỏi khách các câu ⛔ ở mục 5 | Có câu trả lời |
| A2 | Xin dữ liệu: danh sách ~30 mặt hàng, 20–50 phiếu giao hàng thật (nhiều tháng), một file mẫu hàng về nếu có | File nằm trong `samples/` |
| A3 | Cài công cụ trên **cả Windows và Mac M2**: VS Code, Git, `uv`, DB Browser for SQLite; Windows thêm Inno Setup; tạo GitHub repo private | `uv --version`, `git --version` chạy được trên cả 2 máy |

### Tổng kết giai đoạn 1 (đóng 10/10/2026)

**Kết quả:** DiBeKho **0.1.0** phát hành trên GitHub Releases (tag `v0.1.0`, bản Mac `.dmg` + bộ cài Windows, build bằng GitHub Actions). Người dùng đã chạy thử trên Windows và Mac M2: hoạt động bình thường.
- Chức năng: toàn bộ mục 3, 10, 10a, 11, 11.1 + bỏ dòng phí, làm lại khi chọn nhầm (đọc lại phiếu, quên tên đã học), nhập tiếng Trung, giao diện sáng/tối, icon riêng, tự gỡ trên Mac. 51 test.
- Repo sạch thông tin cá nhân/khách (lịch sử gộp lại); README tiếng Anh (mặc định) + tiếng Việt, có hướng dẫn sử dụng.
- File đối chiếu `DiBeKho-du-lieu-goc.xlsx` (gitignored) để so kết quả app với dữ liệu gốc.

### Tổng kết giai đoạn 2 (đóng 11/10/2026)

**Kết quả:** DiBeKho **0.2.0** (tag `v0.2.0`, GitHub Releases; Release `v0.1.0` vẫn giữ để quay lại nếu cần). Khách đã dùng ổn định; giai đoạn này làm theo phản hồi dùng thật. 65 test qua (+2 bỏ qua khi thiếu `samples/`).
- **Dữ liệu gốc (Excel)**: xuất/nhập mặt hàng + khách hàng trong Cài đặt, nhập ở máy khác giữ nguyên mã (mục 9.4b).
- **Thư mục `input/`**: nhận ra file danh mục; file không dùng được chỉ **Ẩn**, không bị chuyển đi; nút **Chọn file để nhập…** (chọn được cả file trong `da-xu-ly`) (mục 9.3).
- **Sau khi nhập gói từ máy cũ**: hết lỗi "Cần xử lý (3)" mà trang trống (mục 9.4).
- **Phiếu duyệt một phần**: Áp dụng → ghi các dòng đã duyệt + khách; dòng "Để sau" thêm vào đúng đơn khi duyệt. Dữ liệu phiếu/khách chỉ vào app khi phiếu đã được duyệt (bảo mật) (mục 9.2).
- **Yêu cầu của khách (đợt 1)**: cột bảng kéo rộng được + rê chuột xem đủ tên, ô chọn mặt hàng ở Cần xử lý hiện đủ tên; nút **Sửa mặt hàng… / Xoá mặt hàng** trong Cài đặt (chỉ xoá mặt hàng chưa có trong phiếu, đã dùng → Ngừng dùng); giao diện **120%** cho Mac 14" (`Config.ui_scale` → `QT_SCALE_FACTOR`, đổi ở Cài đặt → Chung → Cỡ chữ và nút).
- **Mở app trên Mac**: README có lệnh `xattr -dr com.apple.quarantine /Applications/DiBeKho.app` khi macOS cứ báo "Chuyển vào Thùng rác / Xong". File bấm đúp (`.command`) **không** giúp được (cũng bị chặn).
- **Đợt cuối (11/10/2026, phát hành trong 0.2.0 — người dùng chọn chuyển tag `v0.2.0`, không lên số mới):** phiếu đã ghi xong chuyển vào `phieu-giao-hang/da-xu-ly/` (mục 9.2); **Đặt lại dữ liệu** 2 chế độ (mục 9.7); **giao diện tiếng Trung giản thể** (`zh.json`, README.zh.md, ảnh `docs/images/zh/`, mẫu hàng về thêm nhãn tiếng Trung, phông dự phòng PingFang SC / Hiragino Sans GB trên Mac). 71 test qua (+2 bỏ qua). Còn tiếng Việt khi giao diện Trung/Anh: thông báo lỗi chi tiết do `core/`/`excel/` tạo (vd. lý do file phiếu không đọc được), tên thư mục, dữ liệu.

**Chưa xác nhận khi đóng giai đoạn:** build `v0.2.0` trên GitHub Actions có thành công không; bản 0.2.0 chạy trên Mac thật (giao diện 120%, cửa sổ vừa màn hình 14"); cách chép `.dmg` qua USB từ máy Windows có tránh được hộp chặn của macOS không.

**Giai đoạn 3 (khi có phản hồi mới):** thu phản hồi của khách → ghi vào file này trước → sửa/thêm tính năng. Quyết định đang chờ người dùng:
- Cách để khách lớn tuổi mở/cập nhật app trên Mac không cần Terminal: (1) chép `.dmg` qua USB từ máy Windows (miễn phí, cần thử); (2) người dùng chạy lệnh `xattr` một lần trên máy khách + thêm **tự cập nhật** trong app (cần chuyển repo sang public hoặc nơi đặt file khác); (3) Apple Developer 99$/năm (ký số + công chứng trong workflow).

- Dọn bản Mac (nhỏ, không gấp): `.spec` loại QtQuick/Qml/Pdf/VirtualKeyboard nhưng trong `DiBeKho.app/Contents/Frameworks` còn **symlink trỏ tới file đã loại** → lệnh `xattr -dr` in nhiều dòng "No such file" (vô hại, app vẫn chạy). Sửa: xoá symlink hỏng sau PyInstaller (trước khi ký) rồi thử lại trên Mac.

**Việc còn treo từ các giai đoạn trước:**
- Cài lên máy khách (Windows + Mac M3), **kiểm kê đầu kỳ** cùng khách (C1–C2), chạy song song với Excel 2–4 tuần (C3).
- Câu hỏi còn mở ở mục 5: Windows 10 hay 11; cách chuyển file giữa các máy; thư mục phiếu có nằm trong Google Drive/OneDrive/iCloud không; có file `.xls` cũ không; nhà cung cấp có gửi file hàng về không; có cần nhập lại phiếu tháng 8–9 không.
- Chưa thử thực tế: bộ cài Windows (Inno Setup) và trình gỡ trên máy sạch; tự gỡ trên Mac; số liệu với nhiều tháng phiếu thật.
- Bảo trì CI (không gấp): build `v0.1.0` thành công nhưng GitHub cảnh báo các action đang dùng (checkout@v4, upload-artifact@v4, download-artifact@v4, setup-uv@v6, action-gh-release@v2) viết cho Node.js 20, đang bị ép chạy Node.js 24, hiện vẫn chạy đúng. Khi sửa workflow lần tới, nâng lên bản mới (10/2026: checkout v7, upload-artifact v7, download-artifact v8, setup-uv v7, action-gh-release v3) rồi chạy thử bằng Run workflow trước khi gắn tag.
- Gợi ý nếu khách cần: tự cập nhật bản mới, ký số app (Apple Developer 99$/năm) để bỏ bước "Vẫn mở", chuyển repo sang public để khách tải không cần tài khoản GitHub.

### Trạng thái chi tiết (10/10/2026)

- **Phiên bản hiện tại: 0.2.0** (11/10/2026, giai đoạn 2 đợt 1). Trước đó: **0.1.0** (phát hành đầu tiên, người dùng xác nhận app chạy hoàn toàn bình thường, 10/10/2026). Lịch sử git được gộp lại thành một commit `DiBeKho 0.1.0` khi làm sạch thông tin cá nhân.
- **Đã xong:** toàn bộ chức năng mục 3 + 10a + 11 + 11.1; 37 test (bộ đọc phiếu, quét/chống trùng, phiếu sửa/xoá, hàng về, kiểm kê, chuyển dữ liệu, thống kê, xuất Excel, đủ bản dịch, mở mọi màn hình); build Windows chạy được (`--self-test` OK).
- **Bổ sung 10/10/2026:** bỏ dòng phí trong Cần xử lý, thanh điều hướng 6 mục, chuyển dữ liệu vào Cài đặt, nhập tiếng Trung, workflow GitHub Actions build Mac + Windows (`.github/workflows/build.yml`). 42 test.
- **Dọn dẹp 10/10/2026:** xoá `build/`, `dist/` cũ, cache, file Excel trùng ở thư mục gốc (bản giống hệt vẫn ở `samples/`), `config.json` thử nghiệm. Thêm README.md.
- **File dữ liệu gốc để đối chiếu:** `DiBeKho-du-lieu-goc.xlsx` ở thư mục gốc repo (gitignored, có dữ liệu khách). Sheet **Mặt hàng**: 41 dòng danh mục → SP001–SP041 theo thứ tự dòng (đúng mã app gán khi nhập danh mục vào database trống; script tự kiểm tra) + 3 mặt hàng chỉ có trên phiếu (SP042–044 dự kiến). Sheet **Khách hàng**: 3 khách từ 3 phiếu mẫu, kèm mã đơn, ngày, tên hàng và số lượng như trên phiếu. "Ngày nhập" = lúc mặt hàng có trong dữ liệu (T7 không có ngày theo từng ngày; công thức T7 trỏ tới cột I–BP không tồn tại).
- **Làm lại khi chọn nhầm (10/10/2026):** nút "Đọc lại phiếu" (Chi tiết đơn) và "Tên trên phiếu đã học → Quên và đọc lại" (Cài đặt → Danh mục mặt hàng); xác nhận tóm tắt trước khi Áp dụng. 47 test.
- **GitHub:** repo private của người dùng (nhánh `main`). Git của repo này đặt riêng `user.name`/`user.email` của người dùng (tài khoản git chung trên máy là người khác, không dùng).
- **Còn lại:** xem "Giai đoạn 2" ở trên.

### Giai đoạn B — Xây dựng (~5–7 tuần)

| Bước | Việc | Xong khi |
|---|---|---|
| B1 | Khởi tạo dự án `uv` + PySide6: cửa sổ trống, i18n VI/EN, pytest; **đóng gói thử ngay** (PyInstaller + Inno Setup trên Windows, PyInstaller + `hdiutil` trên Mac M2) | Cài, mở, gỡ sạch được trên cả 2 máy; ghi lại kích thước app |
| B2 | SQLite + migration + nạp danh mục mẫu | Mở app → file `kho.sqlite` tự tạo; xem được bằng DB Browser |
| B3 | **Bộ đọc phiếu giao hàng** + test | Đọc đúng 3 file mẫu và các phiếu thật ở A2 |
| B4 | Quét thư mục, chống trùng, màn hình **Cần xử lý** (ánh xạ tên hàng, phiếu bị sửa) | Quét 2 lần không trừ trùng; sửa file → app hỏi |
| B5 | Màn hình **Tồn kho**, trình hướng dẫn lần đầu, tồn đầu kỳ | Tồn = tồn đầu − tổng phiếu, khớp tính tay |
| B6 | File mẫu hàng về + đọc thư mục `input` | Bỏ file hàng về → tồn tăng; file chuyển sang `da-xu-ly/` |
| B7 | Kiểm kê, huỷ phiếu | Chênh lệch và huỷ đều có dấu vết, tồn đúng |
| B8 | **Tra cứu** (không dấu) | Tìm "son chong tham" ra "Sơn chống thấm" |
| B9 | Màn hình **Đơn hàng, Chi tiết đơn, Chi tiết khách, Chi tiết mặt hàng** | Từ một khách xem được mọi đơn và mặt hàng hay mua, khớp với phiếu gốc |
| B9b | **Thống kê theo kỳ + xuất Excel** (mục 11.1) | Xuất ngày/tháng/quý, tất cả và chọn cụ thể; số liệu khớp tính tay |
| B10 | **Xuất/nhập gói dữ liệu** + sao lưu tự động + khôi phục | Xuất ở máy A, nhập ở máy B, tồn giống hệt; quét lại thư mục ở B không trừ trùng |
| B11 | Hoàn thiện tiếng Anh, icon, bộ cài, hướng dẫn cài đặt (Win/Mac, có ảnh) | Người khác tự cài được theo hướng dẫn |

### Giai đoạn C — Đưa vào sử dụng (~2 tuần)

| Bước | Việc | Xong khi |
|---|---|---|
| C1 | Cài lên máy Windows và Mac M3 của khách | App mở được trên cả hai máy |
| C2 | **Kiểm kê đầu kỳ** cùng khách → tồn đầu | Số trên app = số đếm thực tế |
| C3 | Chạy song song với Excel 2–4 tuần | Hai bên khớp → bỏ Excel |

### Giai đoạn D — Vận hành lâu dài

- Phát hành bản mới: sửa code → test → build trên Windows và Mac M2 → gửi bộ cài mới cho khách (có thể thêm tự cập nhật sau). Dữ liệu trong thư mục làm việc giữ nguyên khi cài đè.
- Hằng quý: hỗ trợ khách nhập file hàng về, kiểm tra sao lưu.
- Tính năng mới: ghi vào file này trước, rồi làm.

## 14. Tiêu chí nghiệm thu

- [ ] Cài và chạy được trên Windows 10/11 và macOS M3; database tự tạo khi mở lần đầu.
- [ ] Đặt các phiếu mẫu vào thư mục → tồn giảm đúng; quét lại không trừ trùng; sửa một phiếu → app hỏi thay hay giữ.
- [ ] Xoá một file phiếu → tồn không đổi, app báo trong Cần xử lý, khôi phục được file; đổi tên/di chuyển file → không bị coi là phiếu mới.
- [ ] Dòng hàng có tên lạ → chọn mặt hàng một lần, lần sau tự nhận ra.
- [ ] Bỏ file hàng về vào `input/` → tồn tăng đúng, file chuyển sang `da-xu-ly/`.
- [ ] Xuất gói ở máy Windows, nhập ở máy Mac (và ngược lại) → dữ liệu giống hệt.
- [ ] Tra cứu không dấu ra đúng.
- [ ] Mở chi tiết một đơn: đúng khách, đúng dòng hàng như file gốc; mở được file gốc.
- [ ] Chi tiết một khách: đúng danh sách đơn và mặt hàng hay mua.
- [ ] Thống kê và file Excel xuất ra (ngày, tháng, quý; tất cả và chọn cụ thể) khớp tính tay.
- [ ] Đổi VI/EN toàn bộ giao diện; không chỗ nào hiện giá tiền.
- [ ] Khôi phục được từ bản sao lưu.
- [ ] Chi phí vận hành 0₫.

## 15. Nhật ký quyết định

| Ngày | Quyết định / phát hiện |
|---|---|
| 2026-10-10 | Các file "phiếu nhập" của khách là phiếu giao hàng (hàng ra). Đọc theo nhãn, ánh xạ tên hàng qua `product_aliases`. |
| 2026-10-10 | Tách dự án khỏi luận án; nghiên cứu WMS làm sau trong file 02. |
| 2026-10-10 | ~~VPS + NestJS~~ → ~~Supabase + PWA, nhiều máy dùng chung~~ → **thay thế hoàn toàn** bởi dòng dưới. |
| 2026-10-10 | **Yêu cầu mới của khách:** app desktop chạy riêng trên từng máy (Windows + Mac M3), SQLite trên máy, đọc thư mục phiếu giao hàng, thư mục `input` cho hàng về và gói dữ liệu từ máy khác, xuất gói dữ liệu, tra cứu, thống kê tháng, **không giá**, VI (mặc định) + EN. Chi phí 0₫. |
| 2026-10-10 | ~~Electron + React~~ (đề xuất trước, chưa chốt) → **Python 3.13 + PySide6 + sqlite3 + openpyxl + PyInstaller**, môi trường bằng `uv`; bộ cài Inno Setup (Win) và `.dmg` (Mac). Lý do: người dùng đã làm Python, một ngôn ngữ một tiến trình, nhẹ hơn Electron, dễ gỡ. Build Mac trên Mac M2 của người dùng. |
| 2026-10-10 | Chuyển dữ liệu giữa máy theo kiểu "trao tay" (thay toàn bộ, có sao lưu và cảnh báo), không đồng bộ hai chiều. |
| 2026-10-10 | ~~Database ở thư mục dữ liệu app~~ → **mọi dữ liệu trong một thư mục làm việc** (`Documents/DiBeKho/data/`) để dễ thấy, dễ dọn; ngoài đó chỉ có `config.json`. Cảnh báo nếu thư mục nằm trong OneDrive/iCloud/Google Drive. Dùng `--onedir`, không `--onefile` (tránh rác thư mục tạm). Tồn = tổng `stock_movements`, không cache. Không chặn tồn âm, chỉ cảnh báo. |
| 2026-10-10 | Người dùng đồng ý phương án Python + PySide6. Không build trên máy khách: build trên Mac M2 → gửi `.dmg`; máy khách không cần cài công cụ. Cần biết phiên bản macOS của khách. |
| 2026-10-10 | Thêm màn hình **Đơn hàng / Chi tiết đơn / Chi tiết khách** (mặt hàng khách hay mua). Thống kê theo **ngày/tháng/quý/năm/khoảng tự chọn**, phạm vi tất cả hoặc chọn cụ thể, **xuất Excel** (mục 11.1). Duyệt: ghép tên lạ, phiếu bị sửa, huỷ phiếu, kiểm kê, sao lưu. **Bỏ mật khẩu.** |
| 2026-10-10 | **Đổi tên app thành DiBeKho.** Lỡ xoá file phiếu: tồn không đổi; app lưu bản sao file gốc trong `data/phieu-goc/`, báo trong Cần xử lý (khôi phục/huỷ/bỏ qua); đổi tên/di chuyển file nhận ra theo hash. |
| 2026-10-10 | Ghi chú trên phiếu **không diễn giải**, chỉ hiển thị; tồn trừ theo cột Số lượng. |
| 2026-10-10 | Bỏ loại phiếu `opening`: lần kiểm kê đầu tiên là tồn đầu. Danh mục tự hình thành từ phiếu (tạo mặt hàng mới một cú bấm). Bảng giữ thứ tự truy vấn cho tới khi người dùng bấm tiêu đề cột. |
| 2026-10-10 | Bản 0.1.0 xây xong; build Windows 91MB (zip 35MB); `DiBeKho --self-test` kiểm tra bản đóng gói. PySide6 6.10 → macOS tối thiểu 13. Inno Setup: bỏ ngôn ngữ Vietnamese.isl (không đi kèm bản chuẩn). |
| 2026-10-10 | Danh mục chuẩn = file thống kê tháng 7 của khách (`samples/danh-muc-mau.xlsx`). Thêm **nhập danh mục từ Excel** có xem trước, cột **Loại/màu** (`variant`, migration 002), gợi ý ghép tên dựa trên chữ Hán + mã model + quy cách. |
| 2026-10-10 | Cần xử lý: thêm **"✕ Bỏ dòng" cho dòng không phải hàng hoá** (phí ship, phí dịch vụ), nhớ trong `ignored_lines` (migration 003); cột "Có trong đơn"; ô chọn gõ để tìm. Đổi "Ngưỡng cảnh báo" → **"Báo sắp hết khi còn"** (tô vàng khi tồn ≤ số này; 0 = tắt). Rút thanh điều hướng còn 6 mục: Đơn hàng/Khách hàng/Thống kê thành nút trong Tra cứu; Chuyển dữ liệu vào tab Cài đặt. Hỗ trợ nhập tiếng Trung. Máy khách: macOS Tahoe 26.6.2. Không build được bản Mac trên Windows → thêm workflow GitHub Actions (macos-15 arm64). |
| 2026-10-10 | Dọn bản build/dữ liệu thử cũ; thêm README.md (ảnh từ dữ liệu giả lập, không dùng dữ liệu khách); tra cứu phiếu theo tên khách; trục biểu đồ thống kê dùng `QCategoryAxis` (nhãn ngày không còn bị "..."). Khi đổi giao diện: chạy lại `scripts/readme_screenshots.py`. |
| 2026-10-10 | Đẩy code lên GitHub private của người dùng; đặt `user.name/email` cục bộ cho repo. Giải thích cho người dùng: `phieu-giao-hang/` = hàng ra, đọc tự động, file giữ nguyên tại chỗ; `input/` = hàng về + gói dữ liệu, cần xác nhận, file chuyển sang `da-xu-ly/`. |
| 2026-10-10 | Tương thích Mac: bản build arm64, tối thiểu macOS 13 → M3 (Tahoe 26.6.2) đạt yêu cầu; M2 của người dùng chạy được nếu macOS ≥ 13 (chưa biết phiên bản, cần kiểm tra). **Chưa xác minh thực tế:** workflow build Mac chưa chạy lần nào. |
| 2026-10-10 | Thêm **làm lại khi chọn nhầm**: "Đọc lại phiếu", "Quên và đọc lại" tên đã học, hộp xác nhận trước Áp dụng (migration 004). **Phiên bản:** người dùng yêu cầu bỏ lịch sử phiên bản khỏi README; bản hiện tại là `0.1.0.dev0`, chỉ thành **0.1.0 khi người dùng xác nhận app chạy bình thường**. macOS bundle dùng số `0.1.0` (bỏ `.dev0`). |
| 2026-10-10 | Lỗi "Quên và đọc lại" báo 0 phiếu: phiếu được đọc bằng bản build cũ (trước migration 004) nên không có `document_skipped_lines` → thêm `backfill_skipped_lines` (đọc bản sao `data/phieu-goc` một lần, cờ meta `skipped_lines_backfilled`). Tắt sắp xếp bảng Cần xử lý (hàng r phải khớp `_unknown[r]`). Xoá dữ liệu thử và `config.json`. Tạo file đối chiếu `DiBeKho-du-lieu-goc.xlsx`. |
| 2026-10-10 | **Phát hành 0.1.0.** Làm sạch thông tin cá nhân/khách khỏi repo (tên file mẫu đổi thành tên chung, bỏ SĐT thật trong chú thích code, tên công ty trong phiếu giả lập, email, link repo cũ, cảnh báo mật khẩu); gộp lịch sử git thành một commit; build Mac qua GitHub Actions (tag `v0.1.0`). Giữ nhãn thương hiệu 瑞德牌 → "Hiệu Thụy Đức" vì là dữ liệu phân loại hàng. |
| 2026-10-10 | README: 2 nút **Tải cho Windows / Tải cho macOS** trỏ tới `releases/latest/download/DiBeKho-windows-setup.exe` và `DiBeKho-mac-arm64.dmg`; các huy hiệu Python/PySide6/SQLite trỏ về trang chủ. Workflow có job `release` (chỉ khi đẩy tag `v*`) tạo GitHub Release với tên file cố định. Repo private → người tải phải đăng nhập GitHub có quyền xem. |
| 2026-10-10 | README mặc định **tiếng Anh** (`README.md`, ảnh giao diện tiếng Anh `docs/images/en/`), bản tiếng Việt `README.vi.md`; link chuyển ngôn ngữ ở đầu mỗi file. Hai nút Windows/macOS thu nhỏ (cỡ như các huy hiệu khác), bỏ chữ "Tải cho". |
| 2026-10-10 | **Bản Mac 0.1.0 chạy được trên Mac M2** (người dùng xác nhận). Lỗi: macOS Dark Mode → nền hồng nhạt + chữ trắng, không đọc được. Sửa: màu theo giao diện sáng/tối (`ui.common`: `is_dark`, `sync_theme_colors`, `theme_color`; tối: đỏ `#6e2a2a`, vàng `#5e4c14`); không dùng màu cố định cho nền/chữ nữa. Chưa phát hành bản mới: hỏi người dùng trước khi đổi số phiên bản. |
| 2026-10-10 | **Icon app**: tự vẽ logo kho hàng (`resources/dibekho.svg`, không vướng bản quyền) → `.ico` (nhiều cỡ), `.icns`, icon cửa sổ `src/dibekho/ui/icon.png`; gắn vào PyInstaller và bộ cài Inno Setup. **Gỡ app trên Mac tự xoá khỏi Applications.** Không đổi số phiên bản (người dùng yêu cầu giữ 0.1.0). |
| 2026-10-10 | Workflow phát hành: sau khi build Mac + Windows thành công, job `release` xoá Release cũ cùng tag và **mọi lần chạy cũ** của workflow (kèm Artifacts) bằng `gh` + `GITHUB_TOKEN` (`actions: write`), rồi đăng Release mới. Chuyển tag `v0.1.0` sang commit có icon + màu chế độ tối + tự gỡ trên Mac (vẫn 0.1.0 theo yêu cầu). |
| 2026-10-10 | README (EN + VI) thêm mục **Hướng dẫn sử dụng** sau phần Cài đặt: mở lần đầu, nạp danh mục, tồn đầu, phiếu hằng ngày, hàng về, tra cứu, thống kê, sửa khi nhầm, chuyển máy, sao lưu. Tên nút lấy đúng từ `i18n/*.json`; đổi chữ trên nút thì sửa cả README. Màn hình chào lần đầu dùng `theme_color('hint')` (chế độ tối). |
| 2026-10-10 | **Đóng giai đoạn 1.** Workflow thêm `concurrency` (tag chuyển sang commit mới huỷ lần build cũ đang chạy); chuyển tag `v0.1.0` sang commit cuối. Giai đoạn 2 bắt đầu sau khi khách dùng thử (xem "Tổng kết giai đoạn 1"). |
| 2026-10-10 | Dọn máy phát triển để người dùng thử cài từ GitHub Releases: xoá `dist/`, `.venv/`, cache, thư mục làm việc thử. Giữ `samples/` và `DiBeKho-du-lieu-goc.xlsx` (không có trên GitHub). Làm tiếp: `uv sync` tạo lại môi trường. |
| 2026-10-10 | Thêm **Xuất/Nhập dữ liệu gốc (Excel)** trong Cài đặt (mục 9.4b): mặt hàng + khách hàng (khách chỉ đến cột Số đơn); nhập ở máy khác giữ nguyên mã. 56 test. Không đổi số phiên bản. |
| 2026-10-10 | Chuyển tag `v0.1.0` sang commit có Xuất/Nhập dữ liệu gốc (người dùng chọn cập nhật bản phát hành, giữ số 0.1.0). |
| 2026-10-10 | **Lỗi nghiêm trọng (người dùng báo):** file danh mục bỏ nhầm vào `input/` bị báo "không dùng được", nút Bỏ chuyển nó vào `da-xu-ly` và không còn cách nhập lại trong app. Sửa: nhận ra file danh mục trong `input/`; file không dùng được chỉ **Ẩn** (không di chuyển, migration 005); nút **Chọn file để nhập…** ở Hàng về (chọn từ bất kỳ đâu, kể cả `da-xu-ly`). 58 test. |
| 2026-10-10 | Chuyển tag `v0.1.0` sang commit sửa lỗi thư mục `input/` (vẫn 0.1.0). Giải thích cho người dùng: `input/da-xu-ly/` = nơi cất file đã dùng xong để không nhập lại và để còn bản lưu; không phải nơi nhập. |
| 2026-10-10 | Lỗi (người dùng báo, Mac): sau khi nhập gói dữ liệu từ máy cũ, thanh bên báo "Cần xử lý (3)" nhưng trang trống — 3 phiếu chờ chọn mặt hàng của máy cũ không có file ở máy mới. Sửa trong `deliveries.scan` (xoá dòng chờ không còn file); trang Cần xử lý không còn khoảng trống khi rỗng. 59 test. Chuyển tag `v0.1.0` sang bản sửa. |
| 2026-10-10 | **Hoàn tác** việc ghi khách ngay khi đọc phiếu: người dùng không muốn dữ liệu từ phiếu **chưa duyệt** đi vào app (lý do bảo mật). Quy tắc: thông tin khách/phiếu chỉ vào database khi người dùng đã duyệt phiếu. Chờ người dùng chọn cách xử lý phiếu duyệt một phần. |
| 2026-10-10 | Người dùng chọn **ghi phần đã duyệt** của phiếu (cách 1): Áp dụng → phiếu vào kho với các dòng đã duyệt + khách; dòng Để sau thêm vào đúng đơn khi duyệt. Phiếu sửa "Dùng bản mới" cũng cho phép một phần. 62 test. Chuyển tag `v0.1.0`. |
| 2026-10-14 | Thêm hộp **Kiểm tra số tồn trước khi nhập** dữ liệu gốc khi trang Tồn kho không gắn được theo mã (mục 9.4b). Thử với file thật: 13 dòng tô vàng, gồm đủ 4 dòng bị đổi chéo. 85 test. Giữ 0.2.0, chuyển tag. |
| 2026-10-14 | **Lỗi (người dùng báo, Windows):** phiếu có tên file tiếng Việt dạng NFD → thanh bên báo "Cần xử lý (1)" nhưng trang trống: `unknown_lines` mở `phieu-giao-hang/<rel_path NFC>` không thấy file và bỏ qua im lặng. Sửa: `deliveries.note_path` (tìm theo tên đã chuẩn hoá) cho mọi chỗ mở lại file phiếu. 83 test. Giữ 0.2.0, chuyển tag. |
| 2026-10-14 | Đối chiếu bảng thống kê tồn kho tháng 9 của khách (không có mã) với file dữ liệu gốc người dùng đã sửa: tổng cột F = 4.459 khớp, từng dòng khớp. File khách: cột C+D−E ≠ F ở gần hết dòng (F gõ tay), cột H sai, 2 dòng PPE ghi 16.5/18.5KG ngược giữa tên Việt và Trung, 1 dòng có 2 loại trong một ô. **Lỗi ghép theo thứ tự dòng:** trong file dữ liệu gốc đã sửa (trang Tồn kho kiểu cũ, không cột Mã), thứ tự trang 1 và trang 3 lệch ở 2 cặp dòng (PPE 18.5KG, PPP 30KG) → nhập sẽ đổi chéo tồn của 4 mặt hàng mà tổng vẫn đúng. Người dùng chọn làm bảng xem trước (mục 9.4b). |
| 2026-10-14 | Phản hồi dùng thật (người dùng): (1) mặt hàng mới từ phiếu chưa có tồn đầu → thêm cột **Tồn ban đầu** ở Cần xử lý (kiểm kê ngày trước phiếu); (2) nhập lại dữ liệu gốc phải ra **đúng số tồn** của trang Tồn kho → trang Tồn kho thêm cột **Mã**, được đọc khi nhập; file bỏ vào `input/` cũng nhập được; sửa lỗi **dòng trùng mã bị gộp** (mất 7 biến thể PPE/PPP trên máy thử); (3) mẫu hàng về theo thứ tự mã. 82 test qua. Giữ **0.2.0**, chuyển tag. Máy thử của người dùng đang có 45 mặt hàng (đã bị gộp) → nhập lại file sẽ thêm 7 mặt hàng mã mới SP046–SP052. |
| 2026-10-11 | Người dùng chạy lại build Mac thành công (lỗi lần trước không lặp lại). Thêm theo yêu cầu, vẫn **0.2.0** (chuyển tag): trang Tồn kho của dữ liệu gốc tách **Nhóm hàng** và **Loại/màu** thành 2 cột; nhập danh mục mà không nhận ra cột tồn → hỏi người dùng chọn cột (có giá trị mẫu). 75 test qua. |
| 2026-10-11 | Sửa hiểu nhầm từ đầu (người dùng yêu cầu, để kết thúc 0.2.0): (1) nhập danh mục từ bảng thống kê tồn kho **đọc số tồn ở cột F** (bỏ cột G) và ghi thành tồn kho của app (kiểm kê theo ngày chọn); (2) Xuất dữ liệu gốc có thêm trang **Tồn kho**: tên, phân loại, số lượng tồn. 73 test qua. Chuyển tag `v0.2.0`. |
| 2026-10-11 | Người dùng chọn (a): giữ số **0.2.0**, chuyển tag `v0.2.0` sang commit có thư mục `da-xu-ly` cho phiếu, Đặt lại dữ liệu, tiếng Trung. |
| 2026-10-11 | Người dùng bổ sung 3 yêu cầu để đóng giai đoạn 2: (1) phiếu giao hàng đã xử lý xong chuyển vào `phieu-giao-hang/da-xu-ly/` như `input/` (thay quy tắc cũ "không di chuyển file phiếu"); (2) **Đặt lại dữ liệu**: giữ mặt hàng/tồn về 0/đọc lại phiếu, hoặc xoá toàn bộ; (3) **giao diện tiếng Trung** + README.zh.md, database giữ nguyên. Đã làm, 71 test qua; chưa gắn tag (hỏi người dùng: chuyển `v0.2.0` hay số mới). |
| 2026-10-11 | Người dùng chạy `xattr -dr` trên Mac: nhiều dòng "No such file" do symlink hỏng của các thư viện Qt đã loại (vô hại); ghi việc dọn vào Giai đoạn 3. |
| 2026-10-11 | **Đóng giai đoạn 2** (người dùng xác nhận). Bản hiện tại 0.2.0. Thêm "Tổng kết giai đoạn 2" và "Giai đoạn 3" vào mục 13. |
| 2026-10-11 | Người dùng muốn thay lệnh Terminal bằng một file bấm đúp. **Không làm**: file `.command`/script nằm trong `.dmg` tải về cũng bị gắn quarantine và macOS 15+ chặn y như app (cùng hộp "Thùng rác / Xong"), nên không bớt được bước nào. Đề xuất thay thế: chép `.dmg` qua USB từ máy Windows (không mang dấu quarantine, chưa thử thực tế), người dùng tự chạy lệnh một lần trên máy khách + app tự cập nhật về sau, hoặc Apple Developer 99$/năm. Chờ người dùng chọn. |
| 2026-10-11 | Người dùng hỏi: (1) chuyển máy bằng gói `.dibekho` = **thay toàn bộ** dữ liệu máy nhận (có sao lưu trước, cảnh báo nếu máy nhận có thao tác chưa xuất); Excel dữ liệu gốc = **gộp** (cập nhật theo mã/SĐT, thêm mới, không xoá). (2) Mac vẫn hiện "Chuyển vào Thùng rác / Xong": không sửa được bằng code khi chưa ký Developer ID + công chứng Apple (99$/năm); cách miễn phí: `xattr -dr com.apple.quarantine /Applications/DiBeKho.app` một lần mỗi lần cài (thêm vào README). Chờ người dùng quyết định có mua Apple Developer không. |
| 2026-10-11 | **Phát hành 0.2.0** (người dùng chọn số mới cho giai đoạn 2, thay vì chuyển tag `v0.1.0`). Tag `v0.2.0`; Release `v0.1.0` vẫn giữ trên GitHub, nút tải trong README trỏ `releases/latest` → 0.2.0. Cài đè lên 0.1.0: dữ liệu giữ nguyên, `config.json` cũ không có `ui_scale` → tự nhận 120%. |
| 2026-10-11 | **Bắt đầu giai đoạn 2.** (1) Bảng: mọi cột kéo rộng được (`ui.common.Table`: cột `stretch` nhận phần trống, không còn `QHeaderView.Stretch` khoá cột), tối đa 520px khi tự co, ô dài có tooltip; ô "Là mặt hàng" có danh sách thả xuống rộng bằng tên dài nhất. (2) Cài đặt → Danh mục: nút **Sửa mặt hàng…** và **Xoá mặt hàng**; chỉ xoá được mặt hàng chưa có trong phiếu nào (`catalog.product_documents`, kể cả phiếu đã huỷ), xoá kèm tên đã học; đã dùng → đề nghị Ngừng dùng. (3) **Cỡ giao diện** `Config.ui_scale` (mặc định 1.2) đặt `QT_SCALE_FACTOR` trước khi tạo `QApplication`; cửa sổ mở bằng `fit_window` để không vượt màn hình. 65 test qua (2 bỏ qua vì thiếu `samples/`). Không đổi số phiên bản, chưa gắn tag (chờ người dùng). |
| 2026-10-11 | Hướng dẫn người dùng mở app trên Mac khi bị chặn: macOS 15+ không còn mở được bằng chuột phải → Mở; dùng *Quyền riêng tư & Bảo mật → Vẫn mở*, hoặc `xattr -cr /Applications/DiBeKho.app` khi báo "bị hỏng". |
| 2026-10-10 | Không mua chứng chỉ ký số: hướng dẫn khách "Vẫn mở" trên Mac và "Vẫn chạy" trên Windows một lần. |

## 16. Cách làm việc (dành cho trợ lý AI)

- **Sau mỗi câu trả lời, cập nhật file này** và thêm dòng vào mục 15.
- Làm từng bước nhỏ theo mục 13; mỗi bước có test và commit riêng.
- Bộ đọc Excel, logic tồn, xuất/nhập gói dữ liệu bắt buộc có test: phiếu lệch dòng, tên chưa ánh xạ, quét trùng, phiếu bị sửa, huỷ phiếu, gói phiên bản cũ.
- Luôn nghĩ tới **cả Windows và macOS**: đường dẫn, tên file có dấu (NFC/NFD), quyền truy cập thư mục trên macOS.
- Trước khi làm phần có câu hỏi ⛔ (mục 5), hỏi lại người dùng.
- Người dùng đã làm Python, Java/JavaFX, JDBC, SQL: khi giải thích Qt/PySide6, so sánh với JavaFX nếu giúp dễ hiểu (signal/slot ≈ event handler, `QTableView` + model ≈ `TableView` + `ObservableList`).
- `core/`, `excel/`, `db/` không được import Qt (để test bằng pytest không cần giao diện).
- Chuỗi giao diện luôn qua `t("key")`; thêm key vào **cả** `vi.json`, `en.json` và `zh.json` (test `test_every_translation_key_exists` kiểm tra khoá và `{biến}`).
- Thay đổi schema = thêm file `db/migrations/00N_*.sql` mới, không sửa file cũ.
- Trước khi commit: `uv run ruff check src tests --select F,E9` và `uv run pytest -q`.
- Giữ code đơn giản; không thêm tính năng ngoài phạm vi khi chưa được yêu cầu.
- **Phiên bản:** không tự tăng số phiên bản; hỏi người dùng trước khi đổi số. Không thêm lịch sử phiên bản vào README.
- **Không đưa thông tin thật lên git:** tên/SĐT/địa chỉ khách, tên file của khách, email, đường dẫn máy người dùng. File mẫu thật nằm trong `samples/` (gitignored) với tên chung: `danh-muc-mau.xlsx`, `phieu-mau-1..3.xlsx`. Trước khi push: `git grep` các chuỗi nhạy cảm.
- **README:** có hướng dẫn sử dụng dùng đúng tên nút trong giao diện; đổi tên nút/màn hình thì cập nhật cả `README.md`, `README.vi.md` và `README.zh.md`.
- **Kích thước:** mở cửa sổ bằng `fit_window(widget, w, h)` (không dùng `resize` cố định: giao diện có thể phóng 120–150%); bảng tạo bằng `make_table` (cột kéo được).
- **Màu sắc:** luôn lấy qua `theme_color()` / `RED` / `YELLOW` trong `ui.common` (tự đổi theo sáng/tối); không viết mã màu cố định trong màn hình.
- Đổi giao diện → chạy lại `PYTHONPATH=. uv run python scripts/readme_screenshots.py` để cập nhật ảnh README.

## 17. Bài học từ dự án cũ của người dùng

Dự án Java 11, JavaFX, JDBC, PostgreSQL/SQL Server (repo riêng của người dùng).

**Kế thừa:** mô hình sản phẩm – khách – phiếu – dòng phiếu; cảnh báo tồn thấp; app desktop chạy trên máy.

**Sửa trong app mới:**

| # | Dự án cũ | App mới |
|---|---|---|
| 1 | Sửa tồn trực tiếp (`UPDATE ... SET stock_qty = ?` với số tính ở giao diện) | Tồn = tổng `stock_movements`, không bao giờ ghi đè |
| 2 | Tạo đơn = nhiều lệnh rời rạc, lỗi giữa chừng để lại dữ liệu dở dang | Mỗi lần nhập là một transaction |
| 3 | Xoá cứng đơn hàng | Huỷ bằng biến động đảo ngược, giữ lịch sử |
| 4 | Lỗi bị nuốt (`printStackTrace`) | Thông báo lỗi rõ ràng bằng tiếng Việt; ghi `app_log` |
| 5 | Mật khẩu database trong file cấu hình đưa lên git | SQLite cục bộ, không có mật khẩu nào trong repo |
| 6 | Cần cài Java/Eclipse, cấu hình JDBC thủ công | Bộ cài một cú bấm, database tự tạo |

