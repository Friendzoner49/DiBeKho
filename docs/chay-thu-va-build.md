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

## Build bản Mac (trên Mac M2/M3)

```bash
# lần đầu: cài uv và Git
curl -LsSf https://astral.sh/uv/install.sh | sh
xcode-select --install

git pull
bash packaging/build_mac.sh
```

Ra `dist/DiBeKho-<phiên bản>-mac-arm64.dmg`. Cần macOS 13 trở lên (đã tính cho máy khách: macOS Tahoe 26).

Không có code trên Mac? Tải mã nguồn dạng zip, giải nén, mở Terminal trong thư mục đó rồi chạy `bash packaging/build_mac.sh`
(chỉ cần cài `uv`, không cần Git).

## Build trên máy của GitHub (không cần tự build trên Mac)

File `.github/workflows/build.yml` build cả bản Mac (máy Apple Silicon của GitHub) và bản Windows có bộ cài.

1. Đẩy code lên một repo GitHub **private**.
2. **Phát hành:** đẩy tag phiên bản, ví dụ `git tag -a v0.1.1 -m "DiBeKho 0.1.1" && git push origin v0.1.1`.
   Khoảng 10 phút sau, bản Mac và bộ cài Windows tự xuất hiện ở mục **Releases** với tên cố định
   `DiBeKho-mac-arm64.dmg`, `DiBeKho-windows-setup.exe` và `DiBeKho-windows-setup.zip` (bộ cài nén zip, để Edge không chặn file .exe chưa ký) → hai nút tải ở đầu README (Windows: bộ cài .exe; bản .zip nằm trong bảng "Các bản tải về") luôn trỏ tới bản mới nhất.
3. **Chỉ build thử** (không phát hành): tab **Actions** → **build** → **Run workflow** → tải ở mục **Artifacts** của lần chạy đó.

Chi phí: repo private có 2.000 phút miễn phí/tháng, phút trên máy Mac tính gấp 10 → khoảng 20–40 lần build Mac/tháng, đủ dùng.
File tải từ trình duyệt bị macOS đánh dấu "từ internet": mở lần đầu cần "Vẫn mở" như dưới, hoặc chạy
`xattr -cr /Applications/DiBeKho.app` trong Terminal.

## Cài trên máy khách

**macOS:** mở file `.dmg` → kéo DiBeKho vào Applications → mở app. Lần đầu macOS báo chặn:
*Cài đặt hệ thống → Quyền riêng tư & Bảo mật → "Vẫn mở"*. Khi được hỏi quyền truy cập Documents → Cho phép.

**Windows:** chạy bộ cài (hoặc giải nén bản portable). Nếu SmartScreen cảnh báo: *"Thông tin thêm" → "Vẫn chạy"*.

## Kiểm tra bản đã build

```
DiBeKho --self-test
```
Mở mọi màn hình ở chế độ ẩn với dữ liệu tạm, trả mã thoát 0 nếu ổn. Script build tự chạy bước này.
