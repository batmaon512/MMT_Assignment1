# AsynApRous: Khung Xử Lý Ảnh Bất Đồng Bộ Hiệu Năng Cao (High-Concurrency Framework)

AsynApRous là một khung Web Server bất đồng bộ (asynchronous) hiệu năng cao được phát triển tùy chỉnh, tích hợp cùng **MiniZMQ**—một hệ thống nhắn tin PUSH/PULL tương tự ZeroMQ nhưng được viết hoàn toàn bằng Python thuần (không phụ thuộc thư viện ngoài). Dự án này được xây dựng từ con số không nhằm phục vụ môn học Mạng Máy Tính, thể hiện sự am hiểu sâu sắc về lập trình Socket cấp thấp, xử lý đồng thời (Concurrency) và kiến trúc hệ thống phân tán.

## 🚀 Các Tính Năng Nổi Bật

*   **Custom Event Loop & HTTP Server (`daemon/`)**: Một Web Server bất đồng bộ (non-blocking) được xây dựng dựa trên `select()` và `asyncio`, có khả năng chịu tải hàng ngàn kết nối cùng lúc mà không bị treo.
*   **Hệ Thống Nhắn Tin MiniZMQ (`minizmq.py`)**: 
    *   **Mô hình PUSH/PULL**: Phân phối đều lượng lớn công việc xử lý ảnh cho các máy trạm (Worker) theo cơ chế Round-Robin.
    *   **Custom Framing**: Sử dụng giao thức bọc gói tin `[4-byte Length Header] + [JSON Payload]` để ngăn chặn triệt để tình trạng dính cục luồng TCP (TCP stream corruption).
    *   **Tự Động Kết Nối Lại & Kháng Lỗi (Fault Tolerance)**: Server và Worker có thể tắt/bật lại theo bất kỳ thứ tự nào. Nếu Worker đột ngột mất kết nối, Server sẽ tự động nhặt lại gói tin đang gửi dở và nhét lại vào hàng đợi (Queue), đảm bảo tuyệt đối không rớt dữ liệu (Zero Data Loss).
*   **Quản Lý Luồng & Bất Đồng Bộ Nâng Cao (Advanced Concurrency)**:
    *   **Giảm Tải I/O**: Quá trình phân giải HTTP request được đẩy sang một luồng phụ (Executor) để không làm chặn luồng sự kiện chính (Event Loop).
    *   **Chống Nghẽn Cổ Chai Luồng (ThreadPool Starvation)**: Image Worker được phân bổ một bể chứa luồng độc lập (`cpu_executor` tối đa 8 threads) chuyên trị các tác vụ ngốn CPU (như chỉnh sửa ảnh bằng Pillow). Điều này đảm bảo luồng I/O mạng luôn rảnh rang để kéo/đẩy gói tin.
*   **Lưu Lượng Cực Lớn (High Throughput)**: Có khả năng duy trì ổn định **~100 Requests/giây** đối với các gói dữ liệu ảnh Base64 cực nặng trong môi trường phân tán nội bộ.

## 🏗️ Kiến Trúc Hoạt Động

1.  **Client** gửi một HTTP POST request chứa chuỗi ảnh Base64 lên endpoint `/images/process`.
2.  **Server (`imageapp.py`)**:
    *   Sinh ra một ID `request_id` dạng số đếm tăng dần cho mỗi request.
    *   Tạo một chốt chặn `threading.Event()` để đứng đợi kết quả một cách bất đồng bộ.
    *   Đóng gói nhiệm vụ và ném qua `MiniZMQ PUSH` tới cổng mạng `5557`.
3.  **Workers (`image_worker.py`)**:
    *   Luôn túc trực kéo việc (Pull) từ cổng `5557` thông qua `MiniZMQ PULL`.
    *   Xử lý ảnh (thu nhỏ kích thước, đóng dấu bản quyền watermark) bằng một ThreadPool CPU độc lập.
    *   Trả kết quả ngược lại qua `MiniZMQ PUSH` tới cổng `5558`.
4.  **Collector (`imageapp.py`)**:
    *   Một luồng chạy ngầm trên Server lắng nghe kết quả đổ về tại cổng `5558` qua `MiniZMQ PULL`.
    *   So khớp kết quả nhận được với `request_id` tương ứng và mở chốt `.set()` cho Event đang đợi.
5.  **Server** đóng gói tấm ảnh đã xử lý xong và phản hồi 200 OK về cho Client.

## 🛠️ Cài Đặt & Sử Dụng

### 1. Yêu Cầu Hệ Thống
*   Python 3.9 trở lên
*   `Pillow` (Thư viện xử lý ảnh)
*   `aiohttp` (Tuỳ chọn, dùng cho load testing)

### 2. Khởi Động Hệ Thống

Bật Server Chính (bao gồm HTTP Server + ZMQ Collector):
```bash
python start_imageapp.py
```

Bật một hoặc nhiều Máy Trạm Xử Lý Ảnh (mỗi Worker ở một Terminal riêng biệt):
```bash
python image_worker.py
```

### 3. Tải Kiểm Thử (Load Testing)
Để đo hiệu năng và sức chịu tải của hệ thống, hãy chạy file benchmark có sẵn:
```bash
python load_test.py
```
*Lưu ý: Kịch bản kiểm thử này sẽ tạo ra 10 Client đồng thời gửi tổng cộng 50 bức ảnh lớn lên Server liên tục.*

## 📜 Giấy Phép
Dự án được phát triển với mục đích học thuật và nghiên cứu cho môn học Mạng Máy Tính (CO3093/CO3094) tại Trường Đại Học Bách Khoa TP.HCM (HCMUT). Mọi quyền được bảo lưu.
