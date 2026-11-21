# Chạy thử và build DiBeKho

## Chạy từ mã nguồn (khi đang phát triển)

```bash
uv sync              # cài thư viện vào .venv/ (lần đầu)
uv run dibekho       # mở app
uv run pytest -q     # chạy test
```

Muốn thử lại từ đầu như máy mới: xoá file cấu hình rồi mở lại app.
- Windows: `%APPDATA%\DiBeKho\config.json`
- macOS: `~/Library/Application Support/DiBeKho/config.json`

## Build bản Windows

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

- Có Inno Setup 6 → ra `dist\DiBeKho-<phiên bản>-windows-setup.exe` (bộ cài có trình gỡ).
- Chưa có Inno Setup → ra `dist\DiBeKho-<phiên bản>-windows-portable.zip` (giải nén, chạy `DiBeKho.exe`).

## Bản Mac

Từ 21/11/2026 bản cho Mac là **DiBeKho Swift** (repo riêng, bản chụp công khai ở nhánh `Mac_swift`). Bản Python không còn được dựng cho Mac; file `.dmg` Python cũ vẫn ở Release v0.6.2 trở về trước.

## Build trên máy của GitHub

File `.github/workflows/build.yml` build bản Windows có bộ cài (từ `main`) và bản Mac Swift (từ nhánh `Mac_swift`, máy Apple Silicon của GitHub).

1. Đẩy code lên một repo GitHub **private**.
2. **Phát hành:** đẩy tag phiên bản, ví dụ `git tag -a v0.1.1 -m "DiBeKho 0.1.1" && git push origin v0.1.1`.
   Khoảng 10 phút sau, bản Mac và bộ cài Windows tự xuất hiện ở mục **Releases** với tên cố định
   `DiBeKho-Swift-mac-arm64.dmg`, `DiBeKho-windows-setup.exe` và `DiBeKho-windows-setup.zip` (bộ cài nén zip, để Edge không chặn file .exe chưa ký) → hai nút tải ở đầu README (Windows: bộ cài .exe; bản .zip nằm trong bảng "Các bản tải về") luôn trỏ tới bản mới nhất.
3. **Chỉ build thử** (không phát hành): tab **Actions** → **build** → **Run workflow** → tải ở mục **Artifacts** của lần chạy đó.

Địa chỉ Cloud nhúng vào bản build lấy từ 2 secret của repo: **`DIBEKHO_CLOUD_URL`**, **`DIBEKHO_CLOUD_KEY`** (Settings → Secrets and variables → Actions). Thiếu thì app vẫn chạy, cửa sổ đăng nhập hỏi thêm địa chỉ và mã kết nối. Build trên máy: `scripts/make_cloud_builtin.py` đọc `webapp/config.js`.

File tải từ trình duyệt bị macOS đánh dấu "từ internet": mở lần đầu cần "Vẫn mở" như dưới, hoặc chạy
`xattr -cr "/Applications/DiBeKho Swift.app"` trong Terminal.

## Cài trên máy khách

**macOS:** mở file `.dmg` → kéo DiBeKho Swift vào Applications → mở app. Lần đầu macOS báo chặn:
*Cài đặt hệ thống → Quyền riêng tư & Bảo mật → "Vẫn mở"*. Khi được hỏi quyền truy cập Documents → Cho phép.

**Windows:** chạy bộ cài (hoặc giải nén bản portable). Nếu SmartScreen cảnh báo: *"Thông tin thêm" → "Vẫn chạy"*.

## Kiểm tra bản đã build

```
DiBeKho --self-test
```
Mở mọi màn hình ở chế độ ẩn với dữ liệu tạm, trả mã thoát 0 nếu ổn. Script build tự chạy bước này.
