# Hướng Dẫn Thực Nghiệm và Đánh Giá Hiệu Năng Các Kiến Trúc Mạng

## 1. Giới thiệu Bối cảnh Thực nghiệm
Trong khuôn khổ Đồ án môn học Mạng Máy Tính, mục tiêu cốt lõi của nhóm là xây dựng và đánh giá một hệ thống máy chủ mạng hiệu năng cao. Nhằm cung cấp góc nhìn khách quan và định lượng về năng lực xử lý I/O, tài liệu này mô tả quy trình thực nghiệm (benchmark) đo lường thông lượng mạng thuần túy (Raw Network Throughput) trên ba kiến trúc máy chủ phổ biến:

1. **Kiến trúc Đa luồng (Multi-threading):** Mô hình xử lý truyền thống, trong đó mỗi kết nối từ máy khách (client) sẽ được Hệ điều hành cấp phát một luồng (thread) riêng biệt để xử lý.
2. **Kiến trúc Vòng lặp Sự kiện (Callback-based Event Loop):** Mô hình cốt lõi do nhóm tự phát triển, áp dụng cơ chế I/O không đồng bộ (Non-blocking I/O) kết hợp hàm `select()`. Mô hình này cho phép quản lý đồng thời hàng ngàn socket trên một luồng CPU duy nhất mà không bị khóa (blocking).
3. **Kiến trúc Coroutine (Python Asyncio):** Việc sử dụng thư viện tiêu chuẩn `asyncio` của Python, dựa trên mô hình Máy trạng thái (State Machine) và lập lịch tác vụ (Task Scheduling).

### Lý do lựa chọn phương pháp đo lường Thuần túy (Raw Benchmark)
Để đánh giá chính xác sức mạnh cốt lõi của tầng mạng (Network Layer), kịch bản kiểm thử sử dụng module `raw_benchmark_server.py` thay vì hệ thống nguyên bản. Module này được thiết kế để loại bỏ hoàn toàn chi phí (overhead) tại Tầng Ứng dụng (Application Layer), bao gồm phân tích chuỗi HTTP, xử lý định tuyến (routing) và mã hóa JSON. Việc loại bỏ điểm thắt cổ chai tại bộ vi xử lý (CPU) do xử lý chuỗi giúp thực nghiệm bộc lộ rõ giới hạn phần cứng và năng lực của các thuật toán điều phối I/O giữa ba kiến trúc.

## 2. Các chỉ số Đo lường (Evaluation Metrics)
Các kết quả thực nghiệm được phân tích dựa trên các chỉ số hiệu năng (KPIs) cơ bản sau:
* **Concurrency (Mức độ đồng thời):** Số lượng kết nối mạng mô phỏng được tạo ra tại cùng một thời điểm.
* **RPS (Requests Per Second - Thông lượng):** Số lượng yêu cầu được máy chủ xử lý hoàn tất trong vòng một giây. Đây là chỉ số trọng tâm để đánh giá năng lực chịu tải của hệ thống.
* **Avg Latency (ms - Độ trễ trung bình):** Thời gian trung bình tính từ khi máy khách gửi yêu cầu cho đến khi nhận được phản hồi hoàn chỉnh.
* **P95 Latency (ms):** Mức độ trễ của 5% lượng kết nối chậm nhất, được sử dụng để đánh giá độ ổn định và tính nhất quán trong thời gian phản hồi của hệ thống.
* **Errors (Lỗi):** Số lượng yêu cầu bị từ chối hoặc mất kết nối, thường xuất hiện khi hệ thống cạn kiệt cổng mạng (ephemeral ports) hoặc quá tải bộ đệm (buffers).

---

## 3. Hướng dẫn Thực thi Kịch bản Kiểm thử

Yêu cầu môi trường: Cần khởi chạy 4 cửa sổ dòng lệnh (Terminal / Command Prompt / PowerShell) độc lập để các tiến trình không gây nhiễu lẫn nhau trong quá trình cấp phát tài nguyên hệ thống.

### Bước 1: Khởi động các Máy chủ Thử nghiệm (Raw Servers)
Tiến hành khởi chạy ba máy chủ tương ứng với ba kiến trúc trên các cổng mạng khác nhau:

- **Terminal 1** (Kiến trúc Đa luồng):
  ```bash
  python raw_benchmark_server.py --port 9010 --mode threading
  ```
- **Terminal 2** (Kiến trúc Vòng lặp Sự kiện):
  ```bash
  python raw_benchmark_server.py --port 9020 --mode callback
  ```
- **Terminal 3** (Kiến trúc Coroutine):
  ```bash
  python raw_benchmark_server.py --port 9030 --mode asyncio
  ```

### Bước 2: Kích hoạt Kịch bản Tải (Load Generation)
Tại **Terminal 4**, thực thi công cụ kiểm thử tự động nhằm tạo ra lượng truy vấn lớn hướng đến cả ba máy chủ. Kịch bản sẽ tự động gia tăng mức độ đồng thời (concurrency) qua từng chặng để tìm ra điểm bão hòa của hệ thống.

- **Kịch bản kiểm thử tiêu chuẩn** (Tổng tải 2000 yêu cầu, tăng dần mỗi bước 200):
  ```bash
  python benchmark_all.py -n 2000 --step 200
  ```

- **Kịch bản kiểm thử mức độ cao** (Tổng tải 6000 yêu cầu, tăng dần mỗi bước 200):
  ```bash
  python benchmark_all.py -n 6000 --step 200
  ```

## 4. Kết xuất và Đánh giá Dữ liệu
Quá trình kiểm thử sẽ diễn ra trong khoảng 30 đến 60 giây. Sau khi hoàn tất, hệ thống tự động trả về hai dạng báo cáo:
1. **Bảng tóm tắt trực tiếp (Console Output):** Trình bày thống kê các chỉ số RPS, Latency và đánh giá kiến trúc đạt thông lượng cao nhất tại mỗi mốc đồng thời.
2. **Dữ liệu thô (CSV Export):** Tự động kết xuất toàn bộ số liệu định lượng ra tệp tin `benchmark_servers.csv`.

Dữ liệu từ tệp tin CSV phục vụ trực tiếp cho việc xây dựng các biểu đồ tương quan (đồ thị đường, đồ thị cột) để tích hợp vào chương **Đánh giá Hiệu năng (Performance Evaluation)** của Báo cáo Đồ án môn học, cung cấp luận cứ khoa học trực quan về sự ưu việt trong quản lý I/O của mô hình Không đồng bộ (Asynchronous) so với Đồng bộ (Synchronous).
