# Thử DiBeKho Swift trên Mac (ghi, đọc phiếu, phiếu xuất kho, file Excel, dữ liệu gốc, Cloud; CI xanh 92 test, chưa ai thử trên Mac)

Bản Swift **mở thẳng dữ liệu đang dùng** của app DiBeKho (bản Python) trên máy này, cùng thư mục làm việc, cùng file
`data/kho.sqlite`, và **ghi thật** (đọc phiếu giao hàng, hàng về, kiểm kê, chuyển hàng, dùng thử, huỷ và sửa phiếu,
ghi chú tồn kho).

- **Hai app không mở cùng lúc được** (dùng chung khoá `data/dibekho.lock`): muốn dùng bản Python thì thoát bản Swift
  trước (⌘Q), và ngược lại. Mở bản Swift khi bản Python đang mở → app báo "DiBeKho đang mở rồi".
- **Mỗi ngày mở app có một bản sao lưu** trong `sao-luu/` (như bản Python).
- **Cloud luôn bật, như bản Python (từ 21/11/2026):** mở app là màn hình **Đăng nhập** (logo DiBeKho, tài khoản, mật
  khẩu, nút **Thoát**). Máy đã đăng nhập thì mở thẳng vào app, kể cả khi mất mạng (đồng bộ lại khi có mạng). Đăng nhập
  xong app nối với dữ liệu chung trên Cloud rồi mới mở cửa sổ. **Cài đặt → Cloud → Đăng xuất**: app hỏi lại, rồi tự đóng;
  lần mở sau hiện lại màn hình Đăng nhập. Tài khoản chỉ-xem bị từ chối (như bản Python).
- **Không còn bản thử, không còn «Chỉ xem» và «Đọc thử phiếu»** (21/11/2026). Các mục bên dưới có chữ «bản thử» là ghi
  chép của các lần thử trước. Thư mục bản thử cũ (`~/Library/Application Support/DiBeKhoSwift/BanThu`) app không xoá; anh/chị
  tự xoá nếu muốn. Bản Mac chưa có: Đặt lại dữ liệu, Khôi phục bản sao lưu, Nhập gói `.dibekho` (làm trên bản Windows).

Hai app có tên khác nhau ("DiBeKho" và "DiBeKho Swift") nên để cạnh nhau trong Applications được.

## Cách 1: tải bản đã dựng sẵn (không cần Xcode)

1. Vào repo trên GitHub → **Actions** → lần chạy **build** mới nhất có dấu ✓ → mục **Artifacts** → tải
   `DiBeKho-Swift-mac-arm64` (đăng nhập GitHub mới tải được, vì repo là riêng tư).
2. Mở file zip đã tải (bấm đúp) → ra hai file: **DiBeKho-Swift-mac-arm64.dmg** và `.zip`. Bấm đúp file **.dmg** → cửa sổ
   hiện **DiBeKho Swift** cạnh thư mục **Applications** → kéo app vào đó (thay bản cũ nếu có). (Dùng `.zip` cũng được: giải
   nén ra **DiBeKho Swift.app** rồi kéo vào Applications.)
3. Lần đầu macOS chặn vì app chưa ký bằng tài khoản Apple trả phí. Mở **Terminal** và chạy một lần:

   ```bash
   xattr -dr com.apple.quarantine "/Applications/DiBeKho Swift.app"
   ```

   (Hoặc: mở app, bị chặn → **Cài đặt hệ thống → Quyền riêng tư & Bảo mật** → kéo xuống → **Vẫn mở**.)
4. Mở **DiBeKho Swift**.

## Cách 2: dựng từ mã nguồn bằng Xcode

1. Cài **Xcode** (App Store, miễn phí; cần Xcode 15 trở lên). Mở Xcode một lần để nó cài thêm thành phần.
2. Trong Terminal:

   ```bash
   git clone https://github.com/Friendzoner49/DiBeKho-mac.git   # lần sau: cd DiBeKho-mac && git pull
   cd DiBeKho-mac
   swift test                # chạy các bài kiểm tra; phải thấy "0 failures"
   bash scripts/make_app.sh  # tạo build/DiBeKho Swift.app
   open "build/DiBeKho Swift.app"
   ```

## Lần đầu

Mở app: bản Swift tự mở thư mục làm việc mà bản Python đã chọn (thường là `Documents/DiBeKho`). Lần đầu macOS có thể
hỏi quyền vào thư mục **Tài liệu**: bấm **Cho phép**. Đường dẫn hiện ở dải xanh đầu cửa sổ.

Mở app xong (đã đăng nhập), app tự quét thư mục phiếu giao hàng như bản Python: đọc các phiếu MỚI, ghi vào kho và
chuyển phiếu đọc xong vào `da-xu-ly`. Không còn hộp hỏi «quét ngay hay để sau».

## Trong app: bố cục như bản Python

Thanh bên trái: **Tồn kho · Cần xử lý · Tra cứu · Hàng về · Kiểm kê · Cài đặt**. Trên cùng: **⟳ Quét lại phiếu**,
**Mở thư mục phiếu giao hàng**, **Phiếu xuất kho…**. Tên nút, tên cột, câu hỏi và thông báo lấy đúng từ bản Python. Màu
dòng: cam = sắp hết, đỏ = tồn âm; cột vàng = ô để gõ. Cỡ chữ theo cỡ đã chọn ở bản Python (mặc định 120%).

- **Tồn kho**: lọc, Nhóm hàng, **Chỉ hiện hàng sắp hết**, dải báo sắp hết; ô **Ghi chú tồn kho** gõ được (lưu ngay).
  Nháy đúp một dòng: chi tiết mặt hàng.
- **Tra cứu**: ô tìm không dấu; **Danh sách đơn hàng / Danh sách khách hàng / Thống kê và xuất Excel** mở cửa sổ riêng.
- **Hàng về**: **＋ Nhập hàng về…** (nguồn hàng, ngày, Nhập vào, nhà cung cấp hoặc khách trả lại + đơn, 3 mặt hàng gợi
  ý, **★ Mặt hàng mới**, đơn giá trả lại tự điền, các câu hỏi kiểm tra trước khi lưu, đóng giữa chừng thì giữ bản
  nháp). **Sửa phiếu đã chọn…**.
- **Kiểm kê**: gõ số đếm vào 2 cột vàng (Kho tổng, Văn phòng) → **Lưu kiểm kê**; **Chuyển hàng…**, **Xuất dùng thử…**;
  **Phiếu chuyển hàng… / Phiếu dùng thử… / Phiếu kiểm kê…** (trong cửa sổ chuyển hàng có **Sửa phiếu đã chọn…**).
- Cửa sổ chi tiết một phiếu: **Huỷ phiếu**; phiếu hàng về có **Sửa phiếu hàng về…**, phiếu chuyển có **Sửa phiếu…**.
- **Quét lại phiếu (F5)** và **Cần xử lý**: như bản Python. App quét thư mục `phieu-giao-hang` **khi mở và khi bấm
  nút** (làm nền, cửa sổ vẫn dùng được). Phiếu đọc xong được chuyển vào `phieu-giao-hang/da-xu-ly/`, phiếu cần quyết
  định ở lại ngoài. Trang **Cần xử lý** có: đơn chưa chọn nơi lấy hàng; tên hàng chưa biết (nhóm theo đơn, gợi ý mặt
  hàng, Tạo mặt hàng mới + Tồn ban đầu, Không phải hàng hoá, Chọn mặt hàng khác, Để sau, **Áp dụng và đọc lại phiếu**);
  đơn đọc sau lần kiểm kê (**Giữ số đã kiểm kê / Trừ thêm đơn này**); phiếu bị sửa (**Dùng bản mới / Giữ bản cũ /
  Nhập thành đơn riêng**), phiếu mất file (**Khôi phục file / Huỷ phiếu / Bỏ qua**), file không đọc được. Số trong
  ngoặc ở thanh bên là số việc đang chờ. **Kiểm kê** tự quét trước khi tính tồn, như bản Python.
- Cửa sổ chi tiết một phiếu giao hàng: **Lấy hàng từ** (đổi nơi), **Mở file gốc**, **Đọc lại cả phiếu**, **Huỷ phiếu**;
  phiếu hàng về có **Sửa phiếu hàng về…**, phiếu chuyển có **Sửa phiếu…**.
- **Cài đặt → Đọc thử phiếu (chỉ đọc)…**: bộ đọc phiếu của giai đoạn 2 (không ghi gì), để so một thư mục phiếu bất kỳ.

- **Phiếu xuất kho…** (nút trên cùng): chọn khách (hoặc gõ tên mới), ngày, rồi từng dòng hàng: lấy bao nhiêu ở **Kho tổng** và/hoặc **Văn phòng**, giá tự điền theo đơn gần nhất của khách (sửa được); **★ Mặt hàng mới** cho mặt hàng chưa có trong danh mục. **Lưu phiếu** tạo file Excel trong `output/phieu-xuat/` (giống phiếu giao hàng của cửa hàng, chỉ tiêu đề là PHIẾU XUẤT KHO), trừ tồn ngay và đưa một bản vào `phieu-giao-hang/da-xu-ly/` (bỏ lại file đó vào thư mục phiếu cũng không bị trừ hai lần). Phiếu sai: mở chi tiết phiếu → **Huỷ phiếu** → hỏi tiếp có **xoá hẳn** không (mã phiếu được dùng lại, file chuyển vào `output/phieu-xuat/da-xoa/`).
- **Hàng về** giờ tạo cả file Excel trong `output/hang-ve/` (hỏi có mở file không); chi tiết phiếu có **Mở file**. **Chọn file để nhập…** đọc file hàng về (kiểu cũ điền tay, hoặc file của chính app) ở bất kỳ đâu, cho xem các dòng rồi **Xác nhận nhập hàng về**. Trang **Cần xử lý** liệt kê các file trong `input/`: file hàng về dùng được có **Xem và nhập** / **Bỏ**; file không dùng được chỉ **Mở file** / **Ẩn** (không bao giờ bị di chuyển).
- Bấm vào **tên cột** để sắp xếp (bấm lần nữa: đảo chiều), như bản Python; riêng bảng gõ số (Kiểm kê, Chuyển hàng, Dùng thử) giữ thứ tự. Cột **Tồn** của Tồn kho không bị ghim: các cột co lại theo bề rộng cửa sổ nên luôn thấy hết.

**Chưa có (so với README và hướng dẫn công khai của bản Python):** **Khôi phục từ Cloud** (cố ý); quản lý tài khoản (tạo, đổi vai trò, thu hồi); gửi nhật ký lên Cloud. Không làm: cột Tồn ghim (bảng Tồn kho luôn vừa cửa sổ nên cột Tồn luôn hiện). ⚠ Mới viết 20/11, **CI xanh 98 test (đã biên dịch), chưa ai bấm thử trên Mac**: phím ⌘F; bộ lọc Loại tiền ở Danh sách đơn hàng; hộp chọn ngôn ngữ + thư mục lần đầu mở (chỉ hiện khi máy chưa có thư mục làm việc); gõ giá bằng tệ trong Phiếu xuất kho (khi nút đang ở ¥, bảng tính theo tỷ giá lúc mở cửa sổ, file phiếu vẫn ghi ₫); tự kiểm tra bản mới (Cài đặt → Chung → Bản mới; **chỉ chạy được khi kho GitHub của bản Swift công khai**, hiện kho còn private nên báo «chưa kiểm tra được»); tiếng Anh / tiếng Trung đã thêm cho cửa sổ chi tiết, Cài đặt, hộp yêu cầu nhân viên (còn sót vài chữ ở các hộp nhỏ). Cloud đã có nhưng chưa thử với Cloud thật. Cửa sổ khách có bộ lọc ngày (Mọi thời gian hoặc Từ–Đến); file Excel theo khách theo đúng khoảng đang chọn (⚠ chưa ai bấm thử). Bản Swift **không tự đổi loại tiền và điền tỷ giá**: phiếu bằng tệ được ghi loại tiền ngay lúc đọc; tỷ giá kèm theo do bản Python điền ở lần mở sau. ⚠ Nút ₫ | ¥, đổi ngôn ngữ (Cài đặt → Chung), xuất Excel Thống kê, «Tên trên phiếu đã học» và khôi phục mặt hàng đã xoá đã có trong code nhưng **chưa ai bấm thử** trên Mac.

## Cần anh/chị thử và ghi lại

Muốn thử với phiếu và số liệu thật mà chưa muốn đụng dữ liệu đang dùng: làm trên **bản thử** (Cài đặt → Tạo bản
thử từ dữ liệu đang dùng; bản thử chép luôn các phiếu và `phieu-goc`, mọi việc quét phiếu chỉ xảy ra trong bản sao). Khi
đã yên tâm mới mở dữ liệu đang dùng. Cách so với bản Python:

0. **Quét phiếu thật** (việc chính của bước này): trong **bản thử**, chép vào `phieu-giao-hang` của bản thử (mở bằng
   Cài đặt → Mở thư mục bản thử) vài phiếu **mới** của khách (chưa có trong kho) → **Quét lại phiếu**. So với bản Python
   đọc **cùng phiếu đó** trên một bản sao khác (hoặc so tay): phiếu có vào đúng khách, đúng ngày, đúng số lượng, đúng giá?
   Tồn kho giảm đúng ở **Kho tổng** (chờ chọn nơi)? Dòng hàng lạ có hiện ở **Cần xử lý**, gợi ý mặt hàng có hợp lý
   không (bản Python gợi ý gì thì bản Swift gợi ý đúng thế)? Chọn xong → **Áp dụng và đọc lại phiếu** → phiếu vào kho?
   Sửa một phiếu đã vào (đổi số lượng, lưu lại cùng tên) → có hiện **Phiếu bị sửa** với nút Dùng bản mới / Giữ bản cũ? Xoá
   hoặc đổi tên một file phiếu → đổi tên thì không sao, xoá thì hiện **File đã bị xoá/di chuyển** (tồn không đổi)?
   Phiếu có tên file hoặc thư mục tiếng Việt có dấu (kể cả file chép từ Zalo/Windows) có đọc được không?
   Mở **chi tiết đơn** → **Mở file gốc** mở được phiếu; **Đọc lại cả phiếu** chạy đúng.
0b. **Phiếu xuất kho** (trên bản thử): làm 1 phiếu cho một khách quen, 2 dòng (một dòng lấy ở cả hai nơi, một dòng có **★ Mặt hàng mới**). Giá tự điền có đúng giá lần mua gần nhất không? **Lưu** → mở file Excel: giống phiếu giao hàng của cửa hàng (chữ, khung, cỡ chữ, tổng tiền bằng chữ)? In thử ra giấy A4 ngang có vừa không? Tồn ở hai nơi giảm đúng? Chép file đó vào `phieu-giao-hang` rồi **Quét lại phiếu** → không bị trừ lần hai? Mở bản Python trên cùng dữ liệu (sau khi thoát bản Swift) → đọc được phiếu? Huỷ phiếu → **xoá hẳn** → tồn trở lại, mã phiếu dùng lại được.
1. **Hàng về**: nhập 1 phiếu từ cửa khẩu (có 1 mặt hàng mới), 1 phiếu khách trả lại (xem đơn giá tự điền có đúng giá
   khách đã mua không); mở file Excel vừa tạo xem có như bản Python làm không; bỏ một file hàng về điền tay vào `input` → Cần xử lý → Xem và nhập. Tồn ở **Tồn kho** tăng đúng ở nơi đã chọn? Sửa phiếu đó → tồn đổi đúng?
2. **Kiểm kê**: gõ số đếm cho vài mặt hàng (một nơi, cả hai nơi) → Lưu → tồn bằng đúng số đếm? Cột **Chênh lệch** đúng?
3. **Chuyển hàng** Kho tổng → Văn phòng: tổng tồn không đổi, từng nơi đổi đúng? Sửa phiếu chuyển → đúng?
4. **Xuất dùng thử**: tồn giảm đúng ở nơi đã chọn; **Thống kê** không tính là xuất bán.
5. **Huỷ phiếu** (từ cửa sổ chi tiết): tồn trở lại như trước?
6. Gõ số kiểu `1,5` và `１２`: app hiểu đúng? Enter trong cột vàng chuyển xuống dòng dưới? Bấm **một lần** vào ô vàng
   rồi gõ luôn có được không (bản Python gõ được ngay)?
7. **Bật bộ gõ tiếng Việt (Telex)**: gõ ghi chú có dấu ở cột **Ghi chú tồn kho**, và gõ số vào cột vàng khi Telex vẫn
   bật. Có bị lặp chữ/số hoặc mất chữ không? (Bản Python trên Mac từng bị lỗi "gõ 1 số ra 2" kiểu này.)
8. **Khoá dùng chung**: đang mở bản Swift, mở bản Python → phải báo "DiBeKho đang mở rồi". Thoát bản Swift, mở bản
   Python → mở bình thường, và (khi có mạng) các thay đổi làm ở bản Swift lên Cloud / web.
8b. **Gộp khách hàng** (trong bản thử): trang **Khách hàng**, giữ ⌘ Command (hoặc Shift) bấm chọn 2 khách trở lên → **Gộp khách hàng…**
   → gõ/chọn tên chung → Lưu → xác nhận. Đơn của các khách cũ có sang khách chung không? MST/email có giữ lại? Chọn 1 khách thì có báo lỗi?
8c. **Cloud (chỉ khi anh/chị muốn thử, bằng tài khoản Nhân viên, trên thư mục dữ liệu chưa nối hoặc bản sao)**: Cài đặt → Cloud → gõ địa chỉ, mã kết nối, tài khoản → Đăng nhập → **Đồng bộ ngay**. Thay đổi làm ở Swift có hiện «Chờ chủ duyệt»? Có thể **Bỏ thay đổi chưa duyệt** không? Trên máy chủ (tài khoản Chủ): mục **Yêu cầu từ nhân viên (web)** có hiện hàng về / phiếu giao / kiểm kê gửi từ trang web không; **Xem và vào sổ…** có ghi đúng, **Từ chối** có gửi lý do? Hai máy sửa cùng một chỗ → có hộp chọn bản giữ? Mọi bước ở đây đều ⚠ chưa thử với Cloud thật.
9. Bố cục, tên nút, câu chữ: chỗ nào khác bản Python làm anh/chị (hoặc khách) lúng túng? Chụp màn hình gửi lại.

## So bộ đọc phiếu mới với bản Python trên phiếu thật (một lệnh, đã làm ở giai đoạn 2)

Cần **Cách 2** (Xcode + bản clone). Thư mục `phieu-that` có dữ liệu khách: chỉ chép bằng USB, để ở thư mục nhà, xong
thì xoá.

```bash
DIBEKHO_REAL_NOTES=~/phieu-that swift test --filter NotesTests
```

Phải thấy `customer's notes: 71 read, 0 different` và `0 failures` (lệnh chỉ in tên file trung tính, không in nội dung
phiếu).

## 9. Danh mục mặt hàng (Cài đặt → «Danh mục mặt hàng…»)
Chỉ thử trên **bản thử**. Thêm một mặt hàng (nếu trông giống mặt hàng có sẵn, app hỏi có mở mặt hàng đó để sửa không); sửa bằng nháy đúp; **Xoá**: mặt hàng chưa có trong phiếu thì xoá, đã dùng thì chuyển «Ngừng dùng»; **Gộp mặt hàng trùng…**: chọn một dòng rồi chọn dòng còn lại (mã lớn gộp vào mã nhỏ). Ô «Báo động khi tồn dưới» đổi ngưỡng. **Nhập danh mục từ Excel…**: chọn file bảng thống kê tháng; nếu không thấy cột tồn kho, app cho chọn cột; trong bảng xem trước, nháy đúp ô để sửa, nháy đúp cột «Dòng» để tick/bỏ tick.

## 10. Dữ liệu gốc, Excel theo khách, file lạ trong `input/` (CI xanh; ⚠ chưa thử trên Mac)
Làm trên **bản thử**.
- **Cài đặt → Chuyển dữ liệu và sao lưu → khung «Dữ liệu gốc (Excel)» → Xuất dữ liệu gốc…**: ra `output/DiBeKho_DuLieuGoc_<ngày>_<giờ>.xlsx` (3 trang: mặt hàng, khách hàng, tồn kho). Mở bằng Excel/Numbers: khung tiêu đề, cột rộng vừa, cố định 4 dòng đầu. Dòng tiêu đề có nút lọc như bản Python.
- **Nhập dữ liệu gốc…**: chọn lại đúng file đó (hoặc file cũ không có cột Mã). Nếu dòng tồn kho không khớp theo mã, app hiện bảng vàng để anh/chị chọn mặt hàng cho từng dòng. Xác nhận → app tự tạo bản sao lưu «truoc-nhap-du-lieu-goc» rồi mới ghi. Nhập hai lần liên tiếp không được nhân đôi mặt hàng/khách; số tồn là số **đếm** (đặt lại), không cộng thêm.
- **Chi tiết khách → Xuất Excel…**: `output/KhachHang_<tên>_<ngày giờ>.xlsx` gồm trang các đơn (từng dòng, tổng đơn, phí riêng) và trang mặt hàng (số lượng, doanh thu, giá thấp/cao). So với bản Python cho cùng khách (mọi thời gian).
- **Cần xử lý**: bỏ file dữ liệu gốc, file danh mục (bảng thống kê tháng) hoặc gói `.dibekho` vào `input/` → mỗi file có nút Nhập riêng (gói chỉ nhập được trên **bản thử**) và nút Bỏ (chuyển vào `input/da-xu-ly/`). File không dùng được vẫn chỉ có Mở file / Ẩn.

## 11. Giao diện giống bản Python (đợt 1, viết 20/11; CI xanh 21/11 run 44831954081, ⚠ chưa thử trên Mac)

Nút, ô chọn ngày, hộp chọn là của macOS nên không giống hệt từng điểm ảnh bản Qt; bố cục, thứ tự và chữ thì phải giống.
- **Phiếu xuất kho** và **Nhập hàng về**: bảng hàng có khung, kẻ ô, cột số dòng bên trái, tiêu đề cột ở giữa; ô số lượng, Lấy ở…, Đơn giá có nút ▲▼ (mỗi lần ±1, không xuống dưới 0); cột ✕ cuối dòng. Cột Mặt hàng giãn theo cửa sổ. Nhập hàng về không còn bị tràn, mất phần bên trái; Huỷ bỏ đóng được cửa sổ.
- **Cài đặt → Danh mục mặt hàng**: hai khung «Danh mục mặt hàng» và «Tên trên phiếu đã học». Bấm vào một đơn ở khung dưới: các dòng phải hiện ra (trước đây mở ra trống; ⚠ cách sửa dựa trên phỏng đoán nguyên nhân, cần anh/chị xác nhận).
- **Cài đặt → Chung**: Ngôn ngữ, Cỡ chữ, Bản mới, Thư mục làm việc (Mở, **Đổi thư mục…**), Tên máy, Phiên bản + Giấy phép; khung «Đặt lại dữ liệu» (hai nút, hiện chỉ dùng được trên bản thử); «Gỡ app». **Đổi thư mục…** ghi `workspace` vào `config.json` (file dùng chung với bản Python; các khoá khác giữ nguyên, thư mục mới chưa có dữ liệu thì app tạo kho trống) và chỉ có tác dụng từ lần mở sau. Đừng thử nút này trên máy đang dùng thật trừ khi muốn đổi thư mục thật.
- **Cửa sổ chính**: dòng «Lần quét gần nhất… · N việc cần xử lý» nằm cạnh các nút trên cùng; không còn dòng đo thời gian (ms) ở dưới, không còn khung xanh «Dữ liệu đang dùng» (bản thử / chỉ xem vẫn có khung cam).
- **Nút bấm to hơn khoảng 10%** (theo yêu cầu 20/11, cho quen tay như bản cũ): cùng vị trí, cùng chữ, cùng việc; chỉ khung nút cao và rộng hơn. Hộp thông báo (Có / Không) và menu vẫn là của macOS. Nút mặc định không còn tô xanh.
- **Các bảng danh sách**: có kẻ ô, màu xen kẽ dòng; cột tự vừa nội dung (tối đa 520), cột thứ hai (thường là Mặt hàng/Khách) giãn lấp chỗ trống. Gõ vào ô lọc thì cột không nhảy độ rộng.

## 12. Giao diện giống bản Python (đợt 2, viết 21/11; CI xanh 21/11 run 44831954081, ⚠ chưa thử trên Mac)

So từng màn với ảnh cùng tên trong `anh-ban-goc/`. Làm trên **bản thử**.
- **Tra cứu** (ảnh 03): ô tìm có nút ✕ xoá chữ; ba khung Mặt hàng / Khách hàng / Phiếu chiếm hết chiều cao, kéo vạch giữa các khung để đổi cao thấp. Bảng khách có thêm cột MST, Email.
- **Kiểm kê** (ảnh 05): cột rộng theo nội dung, bảng cuộn ngang được (như bản Python), không còn bóp cột cho vừa cửa sổ. Tiêu đề cột «Theo app Kho tổng» nằm một dòng (bản Python hai dòng).
- **Đơn hàng** (ảnh 07): đủ bộ lọc như bản Python: Loại phiếu (giao hàng, hàng về, kiểm kê, chuyển, dùng thử), Từ … đến … (mặc định 90 ngày gần nhất), Mọi thời gian, Khách hàng, Mặt hàng, Gồm cả phiếu đã huỷ, ô tìm mã phiếu/tên khách, Loại tiền. Cột «Nơi». Chuột phải một phiếu giao hàng còn hiệu lực → **Đọc lại cả phiếu**. Ô tìm nay chỉ tìm mã phiếu và tên khách (đúng bản Python), không tìm tên file nữa. Ô lọc ở Tồn kho không còn dính sang cửa sổ này.
- **Phiếu chuyển hàng… / Phiếu dùng thử… / Phiếu kiểm kê…** (ở Kiểm kê): cùng cửa sổ Đơn hàng, cố định loại phiếu, mặc định Mọi thời gian; có Từ/đến, Mặt hàng, ô tìm.
- **Khách hàng** (ảnh 08): thứ tự cột như bản Python (MST, Email ở cuối), cột Địa chỉ giãn, dòng hướng dẫn trên cùng, ô tìm có ✕.
- **Thống kê** (ảnh 09): «Kỳ:» có Ngày, Tháng, Quý, Năm, Khoảng tự chọn; «Chia theo:» Không chia / Theo ngày / Theo tháng (thêm cột «Nhập 05/10», «Xuất 05/10»…); hàng nút **Mặt hàng: Tất cả**, **Nhóm hàng: Tất cả**, **Khách hàng: Tất cả** (bấm → danh sách tick có ô lọc, «Bỏ chọn hết (= Tất cả)»; nút đổi thành «3 đã chọn») và **Xuất Excel…** bên phải; hai dòng tóm tắt đúng chữ bản Python (chọn mặt hàng/nhóm thì không có phí riêng; chọn khách thì mất cột Tồn đầu/cuối kỳ và chỉ còn mặt hàng khách đó lấy); «Xuất nhiều nhất» (có Hạng) bên trái, **biểu đồ** «Số lượng xuất theo thời gian» bên phải (trên 62 ngày: mỗi cột một tháng). File Excel theo đúng phạm vi và cách chia đang chọn (dòng «Phạm vi» ghi tên đã chọn). So số với bản Python cho cùng kỳ và phạm vi.
- **Chi tiết đơn** (ảnh 17–20): tiêu đề «Đơn hàng 108», nhãn có dấu «:», tên khách là liên kết (bấm mở chi tiết khách); hàng về có «Nhập vào / Nguồn / Nhà cung cấp hoặc Khách + Đơn», chuyển hàng có «Từ / Đến», kiểm kê có cột Nơi / Số đếm / Chênh lệch; dòng «App đọc lúc». Dưới bảng: «3 dòng hàng · tổng số lượng 25», «Tiền hàng … · phí khác … · **tổng tiền …**». Nút (Mở file gốc, Đọc lại cả phiếu, Sửa…, Huỷ phiếu) ở dưới bên trái, **Đóng** ở góc phải dưới. Nháy đúp một dòng → chi tiết mặt hàng.
- **Chi tiết khách** (ảnh 21): «Sửa thông tin khách hàng…» góc phải trên; Tổng quan, Doanh thu (số in đậm); hàng Mọi thời gian / Từ / đến với **Xuất Excel…** bên phải; khung «Mặt hàng khách hay mua» (nháy đúp → mặt hàng) và khung «Các đơn của khách và giá»: dòng đơn in đậm, các dòng hàng thụt vào dưới, rồi dòng phí (bản Python là cây mở/gập được; ở đây là danh sách phẳng). Nháy đúp → chi tiết đơn.
- **Chi tiết mặt hàng** (ảnh 22): tiêu đề «Tên — quy cách — loại», Tồn in to đậm kèm đơn vị, «Kho tổng … + Văn phòng …», ghi chú tồn kho màu cam đậm; lịch sử mới nhất ở trên, dòng tồn âm tô đỏ, nháy đúp → phiếu; khung khách lấy nhiều nhất, nháy đúp → khách.
- **Cần xử lý** (ảnh 02b): thứ tự khung như bản Python: Đơn chưa chọn nơi lấy hàng, Tên hàng chưa có trong danh mục, kiểm kê, yêu cầu nhân viên, yêu cầu web, file, input.
- **Cài đặt → Chuyển dữ liệu và sao lưu** (ảnh 06-cai-dat-3): ba khung như bản Python: «Chuyển dữ liệu sang máy khác» (Máy này, lần xuất/nhập gần nhất, ⚠ thay đổi chưa xuất; Xuất dữ liệu, Nhận dữ liệu (kiểm tra input) → mở Cần xử lý), «Dữ liệu gốc (Excel)», «Sao lưu» (danh sách bản sao lưu + thời điểm; Sao lưu ngay, Khôi phục bản đã chọn — chỉ trên bản thử, Khôi phục mặt hàng…, Mở thư mục sao lưu). Dưới đó là các khung chỉ bản Swift có (Dữ liệu đang dùng, Bản thử + Nhập gói dữ liệu…, Chỉ xem).

- **Chuyển hàng… / Xuất dùng thử…** (ảnh 13, 14): hộp Chuyển từ / Chuyển đến rộng hết hàng; nút **Lưu phiếu chuyển** đứng trước **Huỷ bỏ** (như bản Python). Cột vàng vẫn luôn thấy vì bảng co vừa cửa sổ (không ghim cột).

## 13. Hộp thoại nhỏ giống bản Python (đợt 3, viết 21/11; CI xanh 21/11 run 44831954081, ⚠ chưa thử trên Mac)

So với ảnh 23–31 trong `anh-ban-goc/`. Làm trên **bản thử**.
- **Thêm / Sửa mặt hàng** (Cài đặt → Danh mục, ảnh 23, 24), **★ Mặt hàng mới…** (ảnh 25), **Chọn mặt hàng khác…** (ảnh 26), **Gộp khách hàng…** (ảnh 28), **Xuất Excel…** của Thống kê: nút **Lưu / OK đứng trước Huỷ bỏ** như bản Python; nút nằm ngay dưới ô cuối, khoảng trống dồn xuống dưới. Ô Nhóm hàng của ★ Mặt hàng mới có mũi tên ▾ giống hộp Sửa mặt hàng.
- **＋ Khách hàng mới…** (Phiếu xuất kho) và **Sửa thông tin khách hàng…** (ảnh 27): có tiêu đề to, nhãn «Tên khách hàng *», ô Email hiện mẫu «ten@congty.vn»; chữ gõ được bỏ khoảng trắng thừa. Bấm Lưu mà không đổi gì thì không ghi gì (như bản Python).
- **Giấy phép mã nguồn mở…** (ảnh 29): có dòng giới thiệu trên cùng, cửa sổ to bằng bản Python; nội dung là phần mềm của bản Swift (GRDB, ZIPFoundation), không phải Qt/Python.
- **Nhật ký** (ảnh 30): đã giống từ trước (chọn máy, gợi ý, Làm mới / Sao chép / Lưu ra file… / Mở thư mục / Xoá nhật ký, Đóng bên phải).
- **Đăng nhập Cloud** (ảnh 31): bản Swift đăng nhập ngay trong tab Cloud (bản Python là hộp riêng); nay có tiêu đề «Đăng nhập», nhãn có dấu «:», và vẫn có ô địa chỉ + mã kết nối (bản Swift chưa có sẵn địa chỉ Cloud trong app).
- Phiếu xuất kho / Nhập hàng về giữ «Huỷ bỏ» rồi «Lưu phiếu» vì bản Python cũng vậy (ảnh 15b, 16d).

## 14. Hộp nhập Excel, khôi phục, kiểm kê từ web (đợt 4, viết 21/11; CI xanh 21/11 run 44831954081, ⚠ chưa thử trên Mac)

So với ảnh 32–37 mới chụp của bản Python (dữ liệu bịa). Làm trên **bản thử**.
- **Hàng về → Chọn file để nhập…**: nay nhận cả **file dữ liệu gốc** và **file danh mục** (bảng thống kê tháng), như chữ gợi ý của nút và như bản Python (trước đây bản Swift báo «không phải file hàng về»). File nằm trong `input/` thì nhập xong được chuyển vào `input/da-xu-ly/`.
- **Nhập danh mục** (ảnh 32) và **chọn cột tồn** (ảnh 33): đã giống từ trước.
- **Nhập dữ liệu gốc → bảng gán mặt hàng** (ảnh 34), **Khôi phục mặt hàng…** (ảnh 35) và hộp «có thể trùng mặt hàng»: có hàng tiêu đề cột và khung bảng như bản Python.
- **Kiểm kê từ web** (ảnh 36): chữ đúng như bản Python, bảng có khung, nút «Vào sổ kiểm kê» trước «Huỷ bỏ»; Enter không tự vào sổ.
- **Chọn bản giữ khi trùng** (ảnh 37): bản Swift để ngay trong tab Cloud, mỗi dòng có hai nút (bản Python là cửa sổ riêng, chọn dòng rồi bấm nút); việc làm giống nhau.

## 15. Bảng sát mép, thanh tab Cài đặt to hơn, logo riêng (viết 21/11 sau ảnh chủ dự án; ⚠ chưa biên dịch)

- Mọi bảng: hàng sát mép trái như tiêu đề cột (hết dải trống bên trái, cột không còn lệch so với tiêu đề); bảng có cột co giãn lấp hết chiều ngang ngay cả khi chưa có dòng (ví dụ Tra cứu lúc chưa gõ gì).
- Cài đặt: thanh tab Chung / Mặt hàng / Chuyển dữ liệu / Cloud to hơn khoảng 10%, tab đang chọn tô màu nhấn.
- Logo riêng cho bản Swift: nền vàng, nhà kho xanh (bản Python nền xanh, nhà trắng), để phân biệt hai app trên Dock, Launchpad và trong Finder. macOS có thể vẫn hiện logo cũ một lúc do nhớ đệm; khởi động lại Dock (hoặc máy) là thấy.

## 16. Cloud giống bản Python, rà lần cuối (viết 21/11; CI xanh run 44843766991, ⚠ chưa thử với Cloud thật)

Làm trên **dữ liệu đang dùng** (Cloud không chạy trên bản thử). Nên thử khôi phục bằng một tài khoản Cloud thử trước.
- **Hộp hỏi «tìm thiết bị trong mạng nội bộ»**: không còn hiện khi mở app (app hỏi tên máy qua mạng, nay lấy tên máy tại chỗ như bản Python).
- **Cài đặt → Cloud**: một khung như bản Python. Gồm: dòng tài khoản và nút Đăng xuất; hàng nút «Đồng bộ ngay», «Khôi phục từ Cloud…» (chỉ chủ), «Xem các thay đổi trùng» (khi có), «Bỏ thay đổi chưa duyệt…» (máy nhân viên còn thay đổi); dòng trạng thái và lần sao lưu cuối; ô **«Gửi nhật ký sử dụng»**.
- **Đăng nhập**: cửa sổ riêng như bản Python (Huỷ bỏ, Đăng nhập). Sai mật khẩu thì báo chữ đỏ ngay trong cửa sổ. Phiên hết hạn (đổi mật khẩu, đăng xuất trên web): bấm nút Cloud góc phải sẽ hỏi lại mật khẩu.
- **Nút Cloud góc phải**: phiên hết hạn thì hỏi mật khẩu; có thay đổi trùng thì mở cửa sổ chọn bản giữ; còn lại thì đồng bộ ngay.
- **Chọn bản giữ khi trùng**: cửa sổ riêng có bảng (Mục / Khác nhau). Chọn dòng rồi bấm «Giữ bản của máy này» hoặc «Giữ bản trên Cloud».
- **Khôi phục từ Cloud…**: chọn bản sao lưu trong bảng (thời điểm, máy, dung lượng), hỏi 2 lần, app sao lưu trước. Cloud nhận dữ liệu trước, xong mới thay file trên máy. Sau đó tải lại các phiếu gốc còn thiếu.
- **Gửi nhật ký sử dụng**: bật sẵn như bản Python. Nhật ký được che tên khách, tên file, số điện thoại, đường dẫn **giống hệt bản Python** (có test so từng chữ). Trên Cloud nhật ký **tách theo tài khoản đăng nhập**, mỗi máy mỗi ngày một dòng; bản Swift ghi phiên bản `swift-0.0.1` để phân biệt với bản Python.
- **Cần xử lý → Yêu cầu từ nhân viên (web)** và **thay đổi nhân viên chờ duyệt**: nay là bảng có cột như bản Python (Loại / Người gửi / Nội dung / Gửi lúc / Thao tác), chữ lấy đúng của bản Python.
- Chữ lẻ cho giống bản Python: lỗi lưu phiếu xuất kho, tiêu đề hộp chọn mặt hàng khi gộp, ghi chú nguồn tỷ giá (rê chuột lên dòng tỷ giá), lỗi mở bộ cài bản mới.

## 17. Bảng Tồn kho giống bản Python hơn (viết 21/11 sau ảnh so sánh; ⚠ chưa biên dịch)

- **Tồn kho**: cột «Tồn», «Ghi chú tồn kho», «Kho tổng» hiện ngay khi mở, không phải kéo ngang. Các cột tên dài bị giới hạn độ rộng như bản Python (Mặt hàng 180, Tên Trung 150, Quy cách 100, Loại/màu 90, Nhóm hàng 110, Đơn vị 60; Ghi chú tồn kho luôn 160). Chữ bị cắt thì rê chuột lên ô để đọc đủ.
- **Mọi bảng**: dòng cao hơn, bằng bản Python (khoảng 36 điểm mỗi dòng ở cỡ 120%).
- **Tồn kho**: số ở cột «Tồn» in đậm cho dễ nhìn (chủ dự án yêu cầu; bản Python không có).

## 18. Cửa sổ đăng nhập chỉ còn tên đăng nhập và mật khẩu (viết 21/11; ⚠ chưa biên dịch)

- Như bản Python: địa chỉ Cloud và mã kết nối được gắn sẵn vào bản dựng (secrets `DIBEKHO_CLOUD_URL`, `DIBEKHO_CLOUD_KEY` của repo trên GitHub, không nằm trong code). Cửa sổ đăng nhập chỉ hỏi **Tên đăng nhập** và **Mật khẩu**.
- Bản dựng không có hai secrets đó thì cửa sổ vẫn hiện hai ô địa chỉ, như bản Python dựng từ mã công khai.

## 19. Danh mục mặt hàng chuyển sang Tra cứu (viết 21/11 theo yêu cầu chủ dự án; ⚠ chưa biên dịch)

- **Tra cứu** có 2 tab: «Tra cứu» (như cũ) và **«Danh mục mặt hàng»**. Tab danh mục chiếm cả trang, thấy được nhiều dòng; đủ nút Thêm / Sửa / Xoá / Gộp và ô mức báo sắp hết như trước.
- Bấm ⌘F khi đang ở tab danh mục: quay về ô tìm kiếm.
- **Cài đặt**: tab thứ hai đổi tên thành «Tên trên phiếu đã học», chỉ còn khung đó, chiếm cả trang.
- Khác bản Python có chủ đích: bản Python vẫn để danh mục ở Cài đặt.

## 20. Bo góc các phần lớn (viết 21/11 theo yêu cầu chủ dự án; ⚠ chưa biên dịch)

- Bảng dữ liệu, các khung có tiêu đề, bảng dòng hàng trong phiếu, biểu đồ thống kê và cột trang bên trái được bo góc. Độ bo bằng 10% cạnh ngắn của phần đó, tối đa 12 pt. Nút giữ nguyên.
- Bảng dữ liệu có thêm viền mảnh để thấy góc bo; viền đổi màu theo chế độ sáng/tối.
- Cần xem: góc bảng không bị cắt mất thanh cuộn hay tiêu đề cột; khung trong Cài đặt → Cloud và Tra cứu không bị lệch.

## 21. Phiếu xuất kho bằng nhân dân tệ (viết 21/11 theo yêu cầu chủ dự án; ⚠ chưa biên dịch)

- Công tắc góc trái dưới ở **¥** (giao diện tiếng Việt hay tiếng Trung đều vậy) thì **Phiếu xuất kho…** mới là phiếu tệ: gõ giá bằng ¥, lưu bằng ¥, file Excel ghi giá và tổng bằng ¥, dòng bằng chữ ghi "… NHÂN DÂN TỆ". Đơn này nằm ở cột tiền tệ trong Đơn hàng.
- Hộp hỏi trước khi lưu hiện số ¥ kèm số ₫ xấp xỉ.
- Sửa một phiếu đã lưu: phiếu giữ đúng loại tiền lúc lưu, dù công tắc đang ở đâu.
- Cần xem: mở file phiếu tệ bằng Excel/Numbers thấy ký hiệu ¥ và 2 số lẻ; phiếu hiện ở cột **Tiền hàng (CNY)** trong Đơn hàng.

## 22. Bỏ bản thử, đăng nhập khi mở app, đăng xuất là thoát (viết 21/11/2026; ⚠ chưa biên dịch)

- Mở app: màn hình **Đăng nhập** có logo (nền vàng, nhà kho xanh) và tên DiBeKho; nút **Thoát** và **Đăng nhập**. Gõ sai
  mật khẩu: dòng chữ đỏ, ô mật khẩu xoá trống. Máy đã đăng nhập: mở thẳng vào app (lúc chờ chỉ thấy logo và vòng quay).
- Mất mạng, máy đã nối Cloud trước đó: vẫn mở được, góc trên phải báo mất kết nối. Máy chưa nối lần nào mà mất mạng:
  màn hình Đăng nhập báo cần mạng.
- **Cài đặt → Cloud → Đăng xuất** → hỏi lại → «Đã đăng xuất. App sẽ đóng…» → app đóng. Mở lại: màn hình Đăng nhập.
- Máy mới chưa có thư mục làm việc: hộp chọn ngôn ngữ và thư mục (nút **Thoát** thay cho **Để sau**), rồi màn hình Đăng nhập.
- Không còn: dải cam BẢN THỬ / CHỈ XEM, các khung «Bản thử» và «Chỉ xem» trong Cài đặt → Chuyển dữ liệu và sao lưu, nút
  «Khôi phục bản đã chọn», khung «Đặt lại dữ liệu» trong Cài đặt → Chung. Ở **Cần xử lý**, gói `.dibekho` hiện dòng «Bản
  Mac chưa nhập được gói dữ liệu.».
- Tiêu đề cửa sổ: «DiBeKho» (trước là «DiBeKho Swift (bản thử)»).

## 23. Bấm ô mặt hàng ở Phiếu xuất kho trên macOS 26 (viết 23/11/2026; chủ dự án đã thử OK 24/11/2026)
Chủ dự án báo: menu hiện ra nhưng bấm «Chọn mặt hàng trong kho…» thì không có gì xảy ra (macOS 26). CI trên macOS 15 bấm được cùng chỗ đó, nên app giờ chạy mục được chọn theo ba đường khác nhau, đường nào tới trước thì chạy, và chỉ chạy một lần.

Cần thử trên Mac:
1. Phiếu xuất kho → bấm ô «— Bấm để chọn mặt hàng —» → bấm «Chọn mặt hàng trong kho…»: cửa sổ Chọn mặt hàng phải mở ra, có đủ danh sách.
2. Chọn một mặt hàng rồi bấm «Đồng ý» (và thử cả nháy đúp vào dòng): ô mặt hàng phải hiện tên, và gõ được số ở «Lấy ở Kho tổng».
3. Bấm mục thứ hai «Mặt hàng mới (chưa có trong kho)…» và mục «Xoá dòng này» (có khi đã chọn hàng).
4. Làm lại đúng các bước trên ở Hàng về (ô mặt hàng, ô «Nhà cung cấp», «Nhập vào»).
6. Cùng một đoạn code chạy mọi menu kiểu này, nên thử nốt: ▾ «Nhóm hàng» trong hộp Mặt hàng mới và hộp Sửa mặt hàng (Tra cứu → Danh mục mặt hàng), và ▾ chọn tên giữ lại trong hộp «Gộp khách hàng…» (Khách hàng → chọn 2 khách → Gộp khách hàng…).

Nếu còn chỗ nào bấm không ăn: mở Terminal, dán lệnh này rồi làm lại thao tác hỏng, xong chép mấy dòng `ui:` gửi lại.

```bash
"/Applications/DiBeKho Swift.app/Contents/MacOS/DiBeKhoSwift" 2>&1 | grep "ui:"
```

Ý nghĩa: `picked: true` mà `action: -1, highlighted: -1` là macOS không nói mục nào được chọn; `picked: false` là menu đóng mà không nhận lệnh chọn; không có dòng `menu closed` nào là cú bấm chưa tới được nút.

## 24. Gợi ý khách hàng khi gõ ở Phiếu xuất kho (viết 24/11/2026 theo yêu cầu chủ dự án; ⚠ chưa thử trên Mac thật)
Gõ vài chữ của tên khách thì ô khách hàng chỉ còn những khách hợp, và danh sách tự bật ra. Luật giống hệt ô tìm kiếm của app (và giống bản Python, bản web): không cần dấu, các chữ có thể đảo thứ tự, gõ mấy số điện thoại cũng ra.

Cần thử trên Mac:
1. Phiếu xuất kho → gõ `khach` vào ô Khách hàng: danh sách bật ra chỉ còn những khách hợp. Bấm ↓ rồi Enter: điện thoại, người liên hệ, địa chỉ, MST, email và đơn giá điền theo khách đó.
2. **Gõ tiếng Việt kiểu Telex**: gõ `khachs` → phải ra `khách`, ô không được tự nhảy chữ hay thay chữ đang gõ. Gõ tiếp vài chữ nữa, chữ đang gõ phải giữ nguyên.
3. Gõ tên khách cũ đầy đủ (có dấu) rồi Tab: các ô dưới tự điền như trước.
4. CI ngày 24/11 cho thấy: bấm chuột vào tên trong danh sách thì điền đủ và danh sách đóng lại; chọn bằng ↓ rồi Enter cũng điền đủ, nhưng danh sách có khi còn nằm lại trên màn hình thêm một lúc (bấm ra chỗ khác là mất). Bạn xem trên macOS 26 có bị vậy không.
5. Nếu danh sách **không tự bật ra** trên macOS 26 (app dùng lệnh riêng của hệ thống, có thể không còn): bấm ▾ xem có đúng chỉ còn những khách hợp không, rồi báo lại — khi đó tôi sẽ tự vẽ danh sách.

## 25. Văn phòng Bắc Ninh — nơi thứ ba (viết 25/11/2026 theo yêu cầu khách; ⚠ chưa biên dịch)
1. **Tồn kho**: có thêm cột **Văn phòng Bắc Ninh**; cột Văn phòng cũ giờ tên **Văn phòng Hà Nội**, số giữ nguyên.
2. **Kiểm kê**: hàng nút thứ hai có ô **Đếm ở:** (Kho tổng / Văn phòng Hà Nội / Văn phòng Bắc Ninh). Bảng chỉ còn một cột «Theo app» và một cột vàng «Đếm được» của nơi đã chọn. Gõ vài số rồi đổi **Đếm ở**: app phải hỏi, đồng ý thì các số biến mất; bấm Không thì ô chọn quay lại nơi cũ. Lưu: hộp xác nhận ghi đúng tên nơi; hai nơi còn lại không đổi.
3. **Phiếu xuất kho**: mỗi dòng có Đang có / Lấy ở cho cả ba nơi; chữ «Văn phòng Bắc Ninh» trên tiêu đề cột không bị cắt. Lưu phiếu lấy ở Bắc Ninh rồi mở chi tiết đơn: ghi đúng nơi; đơn lấy nhiều nơi hiện «Nhiều nơi» trong danh sách đơn.
4. **Chuyển hàng** Văn phòng Hà Nội → Văn phòng Bắc Ninh; **Hàng về** «Nhập vào» Bắc Ninh; **Dùng thử** ở Bắc Ninh: số từng nơi đổi đúng.
5. Mở dữ liệu đang dùng của bản Python 0.6.6 (schema 12): app nâng lên schema 13, hàng ở Văn phòng cũ nằm ở Văn phòng Hà Nội.

## 26. Thông tin công ty và «Tải file gốc từ Cloud» (viết 27/11/2026; ⚠ chưa biên dịch)
1. **Cài đặt → Thông tin công ty** (tab thứ năm): hai ô đã điền sẵn từ phiếu giao hàng. Đổi địa chỉ, bấm **Lưu thông tin công ty**; mở một phiếu xuất cũ, **Sửa phiếu xuất kho…** → Lưu: file Excel in địa chỉ mới.
2. Đơn mà Mac chưa có file gốc: cửa sổ đơn có nút **Tải file gốc từ Cloud**; bấm thì hiện thanh tiến trình.
3. Danh sách đơn hàng: chọn nhiều đơn (⌘ / Shift) → **Tải file gốc từ Cloud**: tiến trình «Đang tải i/n», xong báo số file.
5. Lập một phiếu rồi **tắt app ngay** (nút ✕ đỏ, thử cả ⌘Q): app tự gửi rồi mới thoát (tối đa 15 giây; nhật ký có dòng `quit: originals … uploaded`). Mở lại: không bị đòi đăng nhập.
4. Lập một phiếu trên Mac, đợi đồng bộ, rồi mở file gốc của phiếu đó ở máy Windows (không cần tắt app trên Mac).

## 27. Gõ số rồi bấm Lưu ngay (sửa 28/11/2026; ⚠ chưa biên dịch)
Khách báo: Chuyển hàng đã gõ số mà vẫn báo «Chưa nhập số lượng nào». Thử **không bấm Tab / Enter** sau số cuối:
1. **Chuyển hàng…**: gõ số vào một ô vàng → bấm **Lưu phiếu chuyển**: phải hỏi xác nhận, đúng số vừa gõ. Làm lại với **Xuất dùng thử…**.
2. **Kiểm kê**: gõ số đếm cho 2 mặt hàng → bấm **Lưu kiểm kê**: hộp xác nhận ghi **2** mặt hàng (trước đây số cuối bị bỏ sót mà không báo).
3. Nhập danh mục từ Excel: sửa số tồn ở một ô → bấm nút nhập ngay: số vừa sửa được dùng.
4. Đang gõ dở trong ô vàng rồi đổi «Chuyển từ» (hoặc «Đếm ở»): số không bị mất ngầm / không nhảy sang nơi khác.

## 28. Cột đơn giá ở Nhập hàng về (viết 28/11/2026; ⚠ chưa biên dịch)
1. **Hàng về → ＋ Nhập hàng về…** (Cửa khẩu hoặc Nhà cung cấp khác): chọn mặt hàng đã bán có giá bằng đồng → cột **Đơn giá (đơn gần nhất)** hiện số kèm ₫; mặt hàng đơn mới nhất bán bằng tệ → hiện ¥; chưa bán lần nào có giá → «—».
2. Chọn **Khách hàng trả lại**: cột này ẩn, còn **Đơn giá trả lại** như cũ.
3. Đang gõ **Ghi chú tồn kho** rồi bấm sang trang khác ở cột trái (không bấm Enter): quay lại thì ghi chú còn.
