# Brief nghiên cứu: Phát triển hệ thống kho của khách thành WMS cho luận án tốt nghiệp

> File này dùng để mở đầu một session mới. Đọc kèm file `01-he-thong-kho-khach-hang.md` (hệ thống giai đoạn 1 đã/đang xây dựng cho khách).
> Ngôn ngữ trao đổi: tiếng Việt. Thuật ngữ và nội dung luận án: tiếng Nga.

## 1. Bối cảnh và vấn đề

- **Đề tài ВКР:** «Разработка информационных систем управления складскими операциями (WMS) операторами».
- **Ngành:** 09.03.02 «Информационные системы и технологии».
- **Khách hàng thật:** doanh nghiệp kinh doanh sơn, ~45 mặt hàng, kho và văn phòng ở hai địa điểm.
- **Khoảng cách:** khách chỉ cần hệ thống quản lý **tồn kho và đơn hàng** (giai đoạn 1): danh mục, phiếu nhập, đơn hàng, tồn kho realtime, thống kê, chạy trên 2 máy Windows. Đây là phần mềm kế toán kho, **chưa phải WMS**: nó quản lý *con số tồn*, chưa quản lý *các thao tác vật lý trong kho* và *người vận hành kho (оператор)*.

**Câu hỏi nghiên cứu:** Cần phân tích, thiết kế và hiện thực những gì để phát triển hệ thống giai đoạn 1 thành một WMS định hướng người vận hành, phù hợp với tên đề tài, mà vẫn dựa trên nghiệp vụ thật của khách?

## 2. Định nghĩa làm việc

> WMS (система управления складом) là hệ thống thông tin tự động hoá và kiểm soát các nghiệp vụ vật lý trong kho — nhận hàng (приёмка), cất hàng (размещение), lưu trữ, soạn hàng (комплектация/отбор), xuất hàng (отгрузка), kiểm kê (инвентаризация) — ở mức từng vị trí lưu trữ (адресное хранение) và từng lô hàng (партия), với người dùng trung tâm là nhân viên vận hành kho (оператор).

## 3. Phân tích khoảng trống: giai đoạn 1 có gì, WMS cần gì

| Năng lực | Giai đoạn 1 (khách yêu cầu) | WMS (mục tiêu luận án) |
|---|---|---|
| Đơn vị quản lý tồn | Sản phẩm | Sản phẩm × lô × vị trí |
| Vị trí lưu trữ | Không | Khu, kệ, tầng, ô; khu chức năng (nhận, xuất, cách ly) |
| Lô, hạn dùng | Không | Có; cảnh báo sắp hết hạn |
| Nhận hàng | Phiếu nhập → tồn tăng | Kiểm đếm theo đơn đặt, ghi nhận chênh lệch, ghi lô, nhiệm vụ cất hàng |
| Xuất hàng | Đơn → tồn giảm | Lệnh xuất → nhiệm vụ soạn hàng cho operator → kiểm tra → xuất |
| Chọn lô khi xuất | Không | FEFO + ràng buộc "một màu một lô" (đặc thù sơn) |
| Kiểm kê | Không | Kiểm kê theo vị trí, điều chỉnh chênh lệch có duyệt |
| Giao diện operator | Màn hình máy tính | Điện thoại/tablet, quét QR/mã vạch bằng camera, ít thao tác |
| Theo dõi công việc | Không | Nhiệm vụ (задание), trạng thái, người thực hiện, thời gian; năng suất operator |
| Truy xuất nguồn gốc | Không | Lô X đang ở đâu, đã giao cho khách nào |

Lợi thế: giai đoạn 1 đã được thiết kế theo nguyên tắc **mọi thay đổi tồn đi qua `stock_movements`**, nên mở rộng sang lô và vị trí chủ yếu là thêm chiều dữ liệu, không phải viết lại lõi.

## 4. Các hướng phát triển (đề xuất cho giai đoạn 2 — phần lõi của luận án)

Sắp theo mức độ ưu tiên. Ba hướng đầu là bắt buộc để đề tài đúng nghĩa WMS; các hướng sau làm nếu còn thời gian.

### 4.1. Адресное хранение (quản lý vị trí) — bắt buộc
- Mô hình phân cấp vị trí, mã vị trí dạng `A-02-3-1`, in tem QR cho ô.
- Hỗ trợ cả vị trí cố định (mặc định theo sản phẩm) và vị trí động.
- Nghiệp vụ cất hàng (размещение) và chuyển vị trí (перемещение) có quét xác nhận.

### 4.2. Партионный учёт (quản lý lô và hạn dùng) — bắt buộc
- Ghi số lô, ngày sản xuất, hạn dùng khi nhận hàng.
- **Thuật toán chọn lô khi xuất** (điểm nhấn thuật toán của luận án):
  1. Tìm các lô đủ số lượng cho cả dòng đơn (cùng màu, cùng quy cách).
  2. Trong số đó chọn lô hết hạn sớm nhất (FEFO).
  3. Nếu không lô nào đủ: chia theo FEFO và cảnh báo "đơn gồm nhiều lô".
  4. Sắp xếp các vị trí lấy hàng theo thứ tự đường đi trong kho.
- Truy xuất nguồn gốc lô; cảnh báo hàng sắp hết hạn.
- So sánh với FIFO/FEFO thuần bằng mô phỏng trên dữ liệu thật hoặc giả lập (số đơn bị chia lô, lượng hàng quá hạn).

### 4.3. Рабочее место оператора (ứng dụng cho nhân viên kho) — bắt buộc
- PWA chạy trên điện thoại Android rẻ, quét QR/mã vạch bằng camera (ví dụ thư viện ZXing / html5-qrcode).
- Danh sách nhiệm vụ: nhận hàng, cất hàng, soạn hàng, kiểm kê. Mỗi bước: quét vị trí → quét hàng → nhập số lượng → xác nhận.
- Kiểm tra lỗi tại chỗ: quét sai vị trí, sai lô, sai số lượng → báo ngay.
- Thiết kế UX cho môi trường kho: nút lớn, ít chữ, dùng được bằng một tay.

### 4.4. Nhận hàng có kiểm đếm và kiểm kê theo vị trí — nên có
- Đối chiếu số thực nhận với đơn đặt nhà cung cấp; biên bản chênh lệch.
- Kiểm kê từng phần (cycle counting) theo vị trí, điều chỉnh cần quản lý duyệt.

### 4.5. Theo dõi hiệu quả vận hành — nên có
- Thời gian thực hiện nhiệm vụ, số dòng soạn mỗi giờ, tỉ lệ lỗi soạn hàng.
- Dashboard cho quản lý. Đây cũng là nguồn số liệu cho chương kinh tế.

### 4.6. Hoạt động khi mạng ở kho yếu (offline-first) — tuỳ chọn
- Operator vẫn thao tác được khi mất mạng; hàng đợi đồng bộ, xử lý xung đột (ví dụ hai người cùng lấy một lô).
- Phù hợp mục độ tin cậy, nhưng phức tạp; chỉ làm nếu khách xác nhận mạng ở kho không ổn định.

### 4.7. Tích hợp bên thứ ba — cần ít nhất một
Lựa chọn (chọn theo khả năng thực tế):
- Bot Telegram/Zalo gửi cảnh báo tồn thấp, sắp hết hạn, đơn mới cần soạn.
- API hoá đơn điện tử của nhà cung cấp khách đang dùng (nếu có tài khoản API).
- Xuất/nhập dữ liệu với phần mềm kế toán của khách (Excel/CSV hoặc API).

## 5. Ánh xạ sang 5 phần bắt buộc của ВКР

| Phần ВКР | Nội dung từ dự án | Sản phẩm cần có |
|---|---|---|
| 1. Анализ предметной области | Doanh nghiệp, quy trình AS-IS, vấn đề có số liệu; so sánh МойСклад, 1С:УТ/WMS, Odoo Inventory, KiotViet, MISA; luận chứng phát triển riêng | Bảng so sánh; số liệu đo thời gian/sai sót từ khách |
| 2. Требования и проектирование | ТЗ (ГОСТ 34.602-2020); IDEF0 AS-IS/TO-BE; BPMN nhận–cất–soạn–xuất–kiểm kê; UML Use Case, Activity (chọn lô), State (vòng đời nhiệm vụ, chứng từ), Sequence (soạn hàng có quét), Component, Deployment; ERD | Bộ sơ đồ hoàn chỉnh |
| 3. Программная реализация | Server NestJS, DB PostgreSQL, web văn phòng, PWA operator, realtime, tích hợp bên thứ ba | Mã nguồn, ảnh màn hình, mô tả module |
| 4. Экономическая эффективность | Khối lượng phát triển (theo giai đoạn hoặc COCOMO II), chi phí (lương, страховые взносы, khấu hao, VPS); hiệu quả: thời gian tiết kiệm, giảm lỗi soạn, giảm hàng quá hạn; so sánh TCO 3 năm với МойСклад; срок окупаемости | Bảng tính chi phí và hiệu quả |
| 5. Тестирование, надёжность, безопасность | Unit test thuật toán chọn lô, tồn không âm; test đồng thời; E2E; tải (k6); OWASP Top 10, phân quyền; sao lưu và khôi phục; kịch bản sự cố | Báo cáo kiểm thử, bảng kịch bản sự cố |

## 6. Nhiệm vụ nghiên cứu cụ thể (cho session mới)

1. **Phân tích lĩnh vực:** tổng hợp lý thuyết WMS (chức năng điển hình, phân loại hệ thống, tiêu chuẩn mã vạch GS1), đặc thù kho sơn (lô, hạn dùng, hàng dễ cháy).
2. **So sánh giải pháp có sẵn:** lập bảng tiêu chí (chi phí, quản lý vị trí, lô/FEFO, app operator, phù hợp doanh nghiệp nhỏ, ngôn ngữ, nơi lưu dữ liệu). Kiểm tra giá và chức năng hiện tại trên trang chính thức, ghi nguồn và ngày truy cập.
3. **Thiết kế mở rộng mô hình dữ liệu:** từ schema giai đoạn 1, thêm `locations`, `lots`, `stock` theo (product, lot, location), `tasks`/`task_lines`; kế hoạch migration không mất dữ liệu cũ.
4. **Đặc tả và chứng minh thuật toán chọn lô:** mã giả, Activity Diagram, độ phức tạp, test case; kịch bản mô phỏng so sánh FEFO thuần với FEFO + một-lô.
5. **Thiết kế UX ứng dụng operator:** luồng màn hình cho từng loại nhiệm vụ, wireframe.
6. **Kế hoạch triển khai thử:** đề xuất khách thử giai đoạn 2 trên một phần kho (ví dụ 5–10 mặt hàng bán chạy) để có số liệu thật và акт о внедрении.
7. **Khung luận án:** mục lục chi tiết theo yêu cầu của trường, phân bổ số trang.

## 7. Cách trình bày trung thực trong luận án

- Giai đoạn 1 là **hệ thống đã triển khai cho khách** (yêu cầu thật, đang vận hành).
- Giai đoạn 2 (các chức năng WMS) là **phát triển của tác giả dựa trên phân tích nghiệp vụ thật**, được hiện thực trên cùng mã nguồn, kiểm thử trên dữ liệu thật hoặc giả lập, và triển khai thử nếu khách đồng ý.
- Không trình bày chức năng chưa làm như đã triển khai. Nếu chưa triển khai thật, ghi rõ "опытная эксплуатация на тестовых данных".
- Xin phép khách bằng văn bản về việc dùng quy trình và dữ liệu (đã ẩn tên khách hàng, giá) trong luận án.

## 8. Rủi ro

| Rủi ro | Cách xử lý |
|---|---|
| Khách không muốn dùng chức năng WMS | Làm giai đoạn 2 dưới dạng module bật/tắt; thử trên dữ liệu giả lập; vẫn đủ cho luận án |
| Không xin được акт о внедрении | Chuẩn bị акт cho giai đoạn 1 (đã dùng thật) và mô tả giai đoạn 2 là thử nghiệm |
| Phạm vi phình to | Ưu tiên 4.1–4.3; các hướng còn lại ghi vào "hướng phát triển tiếp" |
| Hội đồng hỏi "sao không dùng МойСклад?" | Bảng so sánh + TCO ở chương 1 và 4 |
| Quy định dùng AI của trường | Hỏi người hướng dẫn; code có thể dùng trợ lý AI nhưng tự hiểu và giải thích được; văn bản luận án tự viết |

## 9. Cần xác nhận với người hướng dẫn

- [ ] Đề tài có chấp nhận hệ thống làm cho khách hàng thật ở nước ngoài (nếu khách ở Việt Nam) không?
- [ ] Phần hiện thực giai đoạn 2 trên dữ liệu thử nghiệm có đủ cho chương 3 không, hay bắt buộc phải triển khai thật?
- [ ] Quy định của trường về sử dụng công cụ AI.
- [ ] Mẫu trình bày, số trang, hạn nộp từng phần.

## 10. Cách làm việc (dành cho trợ lý AI trong session mới)

- Bắt đầu bằng việc đọc cả hai file brief, tóm tắt lại hiểu biết và hỏi những điểm chưa rõ.
- Với thông tin về sản phẩm thương mại, luật, tiêu chuẩn: tra cứu nguồn hiện hành, ghi nguồn; không dựa vào trí nhớ.
- Kết quả nghiên cứu nên ở dạng dùng lại được cho luận án: bảng so sánh, sơ đồ, mã giả, danh sách tài liệu tham khảo theo ГОСТ Р 7.0.100-2018.
- Giải thích để người dùng hiểu và tự viết được; không viết hộ văn bản luận án.
