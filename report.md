# BÁO CÁO BÀI TẬP LỚN 1
## Môn: Mạng Máy Tính (CO3093)
### Chủ đề: Non-blocking HTTP Server và Chat Application

---

## 1. Tổng quan kiến trúc hệ thống

Hệ thống được xây dựng theo mô hình đa tiến trình gồm ba thành phần chính:

- **Proxy Server**: Nhận request từ client, định tuyến đến backend phù hợp (không đề cập trong báo cáo này).
- **Backend Server** (`daemon/backend.py`): Xử lý HTTP request, xác thực người dùng, phục vụ file tĩnh và các API RESTful.
- **ChatApp / AsynapRous WebApp** (`apps/chatapp.py`, `daemon/asynaprous.py`): Ứng dụng chat kết hợp mô hình Client–Server và Peer-to-Peer.

Tất cả các thành phần sử dụng **Python standard library** (`socket`, `asyncio`, `threading`, `selectors`) mà **không dùng bất kỳ web framework bên ngoài nào**.

---

## 2. Cơ chế Non-blocking (Phần 2.1)

### 2.1 Ba chế độ xử lý đồng thời

Hệ thống hỗ trợ ba cơ chế non-blocking được lựa chọn qua tham số `--mode`:

| Cơ chế | Mô tả | Lệnh khởi động |
|--------|-------|----------------|
| **Coroutine** (mặc định) | `asyncio` event loop, `async/await` | `--mode coroutine` |
| **Threading** | Mỗi kết nối tạo một thread riêng | `--mode threading` |

#### Chế độ Coroutine (`asyncio`)

```python
# daemon/backend.py
async def async_server(ip="0.0.0.0", port=7000, routes={}):
    async_server = await asyncio.start_server(
        get_handle_client_coroutine(ip, port, routes), ip, port
    )
    async with async_server:
        await async_server.serve_forever()
```

- Sử dụng `asyncio.start_server` với `StreamReader` / `StreamWriter` (high-level API của asyncio).
- Mỗi kết nối được xử lý bởi một coroutine độc lập, **nhường CPU** khi chờ I/O (`await reader.read()`), cho phép một thread đơn phục vụ hàng nghìn kết nối đồng thời.

#### Chế độ Threading

```python
# daemon/backend.py
if mode_async == "threading":
    client_thread = threading.Thread(
        target=handle_client,
        args=(ip, port, conn, addr, routes)
    )
    client_thread.daemon = True
    client_thread.start()
```

- Mỗi kết nối đến được chuyển cho một **daemon thread** xử lý độc lập.
- Dùng `select.select()` để chờ kết nối đến mà không bị block vòng lặp chính.

#### Wrapper coroutine đóng gói `routes`

Để truyền tham số `routes` vào coroutine handler (vốn chỉ nhận `reader, writer`), một closure wrapper được dùng:

```python
def get_handle_client_coroutine(ip, port, routes):
    async def handle_client_coroutine(reader, writer):
        daemon = HttpAdapter(ip, port, None, addr, routes)
        await daemon.handle_client_coroutine(reader, writer)
    return handle_client_coroutine
```

### 2.2 Khởi động backend với lựa chọn mode

```bash
# Coroutine mode (port 9011)
python start_backend.py --server-port 9011 --mode coroutine

# Threading mode (port 9010)
python start_backend.py --server-port 9010 --mode threading
```

```python
# start_backend.py
import daemon.backend as _bk
_bk.mode_async = args.mode
create_backend(ip, port, routes=API_ROUTES)
```

---

## 3. Xác thực HTTP (Phần 2.2)

### 3.1 Luồng xác thực (Authentication Flow)

Xác thực được thực hiện trong `HttpAdapter` (cả hai phiên bản `handle_client` và `handle_client_coroutine`), gồm hai bước:

**Bước 1: Kiểm tra Cookie `session_id`** (RFC 6265)

```python
if req.cookies and 'session_id' in req.cookies:
    session_id = req.cookies['session_id']
    if session_id in ACTIVE_SESSIONS:
        is_authenticated = True
        current_user = ACTIVE_SESSIONS[session_id]
    else:
        user = validate_session(session_id)  # Kiểm tra trong file db/sessions_id.txt
        if user:
            is_authenticated = True
            current_user = user
            add_session(session_id, user)
```

**Bước 2: Nếu chưa có Cookie → kiểm tra HTTP Basic Auth** (RFC 7235 / RFC 2617)

```python
if not is_authenticated and req.auth:
    auth_parts = req.auth.split(' ')
    if auth_parts[0] == 'Basic':
        decoded_str = base64.b64decode(auth_parts[1]).decode('utf-8')
        username, password = decoded_str.split(':', 1)
        if VALID_USERS.get(username) == password:
            is_authenticated = True
            new_session = create_session(username)
            add_session(new_session, username)
            new_cookie_to_set = f"session_id={new_session}; Path=/; HttpOnly"
```

### 3.2 Quản lý Session

| Thành phần | Mô tả |
|-----------|-------|
| `ACTIVE_SESSIONS` (RAM) | Dictionary lưu `session_id → username`, tối đa 100 phiên |
| `db/sessions_id.txt` | File lưu session persistent, format: `sid\|user\|expire_timestamp` |
| `db/account.txt` | File tài khoản, format: `username:password` |
| `SESSION_TTL` | 86400 giây (24 giờ) |

**Hàm quản lý session:**
- `create_session(username)`: Tạo UUID hex, lưu vào file và RAM.
- `validate_session(session_id)`: Kiểm tra còn hạn và tồn tại.
- `remove_session(session_id)`: Xóa khi logout.

### 3.3 Phân quyền & Điều hướng (Authorization)

```python
public_paths = ['/', '/login.html', '/register.html']
is_public = (
    req.path in public_paths
    or req.path.startswith('/css')
    or req.path.startswith('/js')
    or req.path == '/api/login'
    ...
)

if not is_authenticated and not is_public:
    if is_api:
        # Trả về 401 Unauthorized với header WWW-Authenticate
        response = self.build_unauthorized_response(req)
    else:
        # Redirect về trang đăng nhập
        response = b"HTTP/1.1 302 Found\r\nLocation: /login.html\r\n..."
```

### 3.4 API xác thực

| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `POST /api/login` | POST | Xác thực, trả `Set-Cookie: session_id=...` |
| `POST /api/logout` | POST | Xóa session, đặt `Max-Age=0` để trình duyệt xóa cookie |
| `GET /api/me` | GET | Trả tên user hiện tại (cần xác thực) |

---

## 4. Xử lý HTTP Request và Response

### 4.1 Module `Request` (`daemon/request.py`)

Class `Request` chịu trách nhiệm phân tích gói tin HTTP thô:

```python
def prepare(self, request, routes=None):
    self.method, self.path, self.version = self.extract_request_line(request)
    self.headers = self.prepare_headers(request)
    self._raw_headers, self._raw_body = self.fetch_headers_body(request)
    self.body = self._raw_body
    # Parse Cookie header
    cookie_str = self.headers.get('cookie', '')
    self.cookies = {}
    if cookie_str:
        for pair in cookie_str.split(';'):
            if '=' in pair:
                key, value = pair.strip().split('=', 1)
                self.cookies[key] = value
    # Parse Authorization header
    self.auth = self.headers.get('authorization', None)
    # Route hook resolution
    if routes:
        self.hook = routes.get((self.method, self.path))
```

### 4.2 Module `Response` (`daemon/response.py`)

Class `Response` xây dựng HTTP response hoàn chỉnh:

- **`get_mime_type(path)`**: Phát hiện MIME type từ extension file.
- **`prepare_content_type(mime_type)`**: Xác định `base_dir` phục vụ file (HTML từ `www/`, CSS/JS/image từ `static/`).
- **`build_content(path, base_dir)`**: Đọc file từ đĩa, trả về nội dung nhị phân.
- **`build_response_header(request)`**: Tạo HTTP header: `Content-Type`, `Content-Length`, `Date`, `Server`, `Cache-Control`.
- **`build_response(request)`**: Pipeline đầy đủ → MIME detection → load file → build header → ghép response.

### 4.3 Module `HttpAdapter` (`daemon/httpadapter.py`)

`HttpAdapter` là lớp điều phối trung tâm, tích hợp `Request` + `Response` + Authentication + Routing:

```
Client → [socket recv] → Request.prepare() → [Auth check] → master_api_handler() → [socket send]
```

Hỗ trợ hai phương thức:
- `handle_client(conn, addr, routes)`: Phiên bản đồng bộ (threading mode).
- `handle_client_coroutine(reader, writer)`: Phiên bản bất đồng bộ (coroutine mode), dùng `await reader.read()` và `await writer.drain()`.

---

## 5. API Routes (`daemon/api.py`)

Bảng các API endpoint được đăng ký trong `API_ROUTES`:

### 5.1 API xác thực và thông tin

| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `/api/login` | POST | Đăng nhập, set cookie |
| `/api/logout` | POST | Đăng xuất, xóa cookie |
| `/api/me` | GET | Lấy thông tin user hiện tại |
| `/status` | GET | Health check server |

### 5.2 API Chat (Peer-to-Peer)

| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `/submit-info` | POST | Đăng ký IP:port peer với tracker |
| `/get-list` | POST | Lấy danh sách peers online |
| `/connect-peer` | POST | Lấy thông tin kết nối đến một peer |
| `/broadcast-peer` | POST | Gửi tin nhắn đến tất cả peers |
| `/send-peer` | POST | Gửi tin nhắn trực tiếp đến một peer |
| `/online` | POST | Heartbeat, cập nhật trạng thái online |
| `/signal` | POST | Lưu tín hiệu P2P (offer/answer) |
| `/signal_poll` | POST | Lấy và xóa hàng đợi tín hiệu |

### 5.3 API Benchmark

| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `/benchmark/sync` | GET | Dùng `time.sleep(50ms)` → test threading |
| `/benchmark/async` | GET | Dùng `asyncio.sleep(50ms)` → test coroutine |
| `/benchmark_1.jpg` | GET | Trả ảnh 11MB, test throughput lớn |

---

## 6. Ứng dụng Chat Hybrid (Phần 2.3)

### 6.1 Kiến trúc Hybrid Client-Server + P2P

```
                    ┌──────────────────┐
                    │  Tracker Server  │
                    │  (trackerapp.py) │
                    │  PORT: 9000      │
                    └────────┬─────────┘
                             │ submit-info / get-list
                ┌────────────┼────────────┐
                ▼            ▼            ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ ChatApp  │  │ ChatApp  │  │ ChatApp  │
        │ Peer A   │  │ Peer B   │  │ Peer C   │
        │ PORT:8001│  │ PORT:8001│  │ PORT:8001│
        └──────┬───┘  └────┬─────┘  └────┬─────┘
               └───────────┴─────────────┘
                    Direct P2P (send-peer / broadcast-peer)
```

### 6.2 Giai đoạn khởi tạo (Client-Server Paradigm)

**Đăng ký peer với Tracker** (`/submit-info`):

```python
# trackerapp.py
@app.route('/submit-info', methods=['POST'])
def submit_info(req):
    resolved_ip = resolve_peer_ip(ip, remote)  # Tự phát hiện IP LAN thực
    PEER_REGISTRY[name] = {"ip": resolved_ip, "port": port, "last_seen": now}
    ONLINE[name] = now
```

**Phát hiện IP LAN tự động** (giải quyết vấn đề peer kết nối qua `localhost`):

```python
def resolve_peer_ip(candidate_ip, remote_addr):
    # Ưu tiên IP do peer tự khai báo nếu hợp lệ
    if ip and ip not in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
        return resolved
    # Fallback: lấy IP nguồn từ TCP connection
    if remote_addr and remote_addr[0] not in ["127.0.0.1", ...]:
        return remote_addr[0]
    # Last resort: LAN IP của máy tracker
    return MY_LAN_IP
```

**Lấy danh sách peer** (`/get-list`):

```python
@app.route('/get-list', methods=['POST'])
def get_list(req):
    cleanup_online(now)  # Xóa peer offline (TTL = 30s)
    peers = [{"name": name, **info} for name, info in PEER_REGISTRY.items()
             if ONLINE.get(name)]
    return json_response({"code": 1, "peers": peers})
```

### 6.3 Giai đoạn Chat (Peer-to-Peer Paradigm)

**Gửi tin nhắn trực tiếp đến peer** (`send_to_peer`):

```python
# chatapp.py
async def send_to_peer(target_ip, target_port, payload):
    """Gửi tin nhắn qua TCP trực tiếp, không qua tracker."""
    body = json.dumps(payload).encode('utf-8')
    http_request = (
        f"POST /internal/receive-msg HTTP/1.1\r\n"
        f"Content-Length: {len(body)}\r\n\r\n"
    ).encode('utf-8') + body
    reader, writer = await asyncio.open_connection(target_ip, int(target_port))
    writer.write(http_request)
    await writer.drain()
    ...
```

**Broadcast đến tất cả peers đồng thời** (`/broadcast-peer`):

```python
@app.route('/broadcast-peer', methods=['POST'])
async def broadcast_peer(req):
    tasks = [
        send_to_peer(info["ip"], info["port"], payload)
        for name, info in PEER_CACHE.items()
        if name != sender_name
    ]
    await asyncio.gather(*tasks, return_exceptions=True)  # Đồng thời, không chặn nhau
```

**Nhận tin nhắn từ peer** (`/internal/receive-msg`):

```python
@app.route('/internal/receive-msg', methods=['POST'])
def internal_receive_msg(req):
    data = json.loads(req.body)
    MESSAGE_QUEUE.append(data)  # Lưu vào hàng đợi

@app.route('/poll-messages', methods=['POST'])
def poll_messages(req):
    msgs = list(MESSAGE_QUEUE)
    MESSAGE_QUEUE.clear()
    return json_response({"code": 1, "messages": msgs})
```

### 6.4 Cache peer cục bộ (Offline P2P)

```python
PEER_CACHE = {}  # {name: {"ip": ..., "port": ...}}

# Khi get-list → cập nhật cache
for peer in res.get("peers", []):
    PEER_CACHE[peer["name"]] = {"ip": peer["ip"], "port": peer["port"]}

# Khi send-peer → thử cache trước, rồi mới hỏi tracker
target_peer = PEER_CACHE.get(target_name)
if not target_peer:
    peers_res = await make_tracker_request_async("/get-list", {}, req)
    ...
```

### 6.5 AsynapRous Framework (`daemon/asynaprous.py`)

Framework routing decorator nhẹ do tự xây dựng:

```python
class AsynapRous:
    def route(self, path, methods=['GET']):
        def decorator(func):
            for method in methods:
                self.routes[(method.upper(), path)] = func
            # Tự động wrap sync/async handler
            if inspect.iscoroutinefunction(func):
                return async_wrapper
            else:
                return sync_wrapper
        return decorator

    def run(self):
        create_backend(self.ip, self.port, self.routes)
```

---

## 7. Benchmark: Coroutine vs Threading (Phần đo hiệu năng)

### 7.1 Mô tả

Script `benchmark.py` thực hiện so sánh hiệu năng hai chế độ bằng cách gửi N request đồng thời (điều chỉnh theo `--steps`) đến hai server riêng biệt:

| Server | Mode | Port |
|--------|------|------|
| Coroutine server | asyncio | 9011 |
| Threading server | multi-thread | 9010 |

### 7.2 Hai loại endpoint benchmark

**Endpoint `sleep` (mặc định):**
- **Coroutine**: `GET /benchmark/async` → `asyncio.sleep(50ms)` → event loop phục vụ các request khác trong lúc chờ.
- **Threading**: `GET /benchmark/sync` → `time.sleep(50ms)` → thread bị block riêng lẻ.

**Endpoint `image`:**
- `GET /benchmark_1.jpg` → trả về file ảnh 11MB để test throughput I/O lớn.
- Phiên bản async dùng `loop.run_in_executor()` để đọc file không block event loop.

### 7.3 Phương pháp đo lường

```python
# Benchmark coroutine: dùng asyncio với Semaphore kiểm soát concurrency
async def _gather_async(host, port, path, n, c, results, errors):
    sem = asyncio.Semaphore(c)  # Giới hạn c kết nối đồng thời
    tasks = [asyncio.create_task(async_worker(..., sem)) for _ in range(n)]
    await asyncio.gather(*tasks)

# Benchmark threading: dùng thread theo batch
def fire_threaded(host, port, path, n, c):
    while sent < n:
        batch = min(c, n - sent)
        threads = [Thread(target=sync_worker, ...) for _ in range(batch)]
        for t in threads: t.start(); t.join()
```

**Metrics thu thập:** Throughput (req/s), Avg latency, P50, P95, Std deviation, Error count.

### 7.4 Kết quả kỳ vọng

| Scenario | Winner | Lý do |
|----------|--------|-------|
| I/O-bound (sleep) ở concurrency cao | **Coroutine** | Event loop nhường CPU, 1 thread xử lý nhiều kết nối |
| I/O-bound (sleep) ở concurrency thấp | **Threading** | Thread overhead thấp, mỗi thread độc lập |
| File lớn (image) ở concurrency cao | **Coroutine** | Không tạo thread mới cho mỗi request |

---

## 8. Cấu trúc file dự án

```
MMT_Assignment1/
├── daemon/
│   ├── backend.py       # Backend server (threading + coroutine)
│   ├── httpadapter.py   # HTTP request/response + authentication
│   ├── request.py       # HTTP request parser
│   ├── response.py      # HTTP response builder (MIME, file serving)
│   ├── asynaprous.py    # Lightweight web app framework (decorator routing)
│   ├── api.py           # API route handlers
│   └── dictionary.py    # CaseInsensitiveDict utility
├── apps/
│   ├── chatapp.py       # Chat peer daemon (hybrid C/S + P2P)
│   └── trackerapp.py    # Tracker server (peer registry)
├── www/                 # Static HTML pages (login, form, welcome)
├── static/              # CSS, JS, images
├── db/                  # account.txt, sessions_id.txt
├── config/              # proxy.conf
├── start_backend.py     # Entry: khởi động backend
├── start_chatapp.py     # Entry: khởi động peer chat
├── start_tracker.py     # Entry: khởi động tracker
└── benchmark.py         # Công cụ benchmark coroutine vs threading
```

---

## 9. Hướng dẫn chạy hệ thống

### 9.1 Khởi động Backend (HTTP Server)

```bash
# Coroutine mode
python start_backend.py --server-port 9011 --mode coroutine

# Threading mode
python start_backend.py --server-port 9010 --mode threading
```

### 9.2 Khởi động Tracker

```bash
python start_tracker.py --server-port 9000
```

### 9.3 Khởi động Chat Peer

```bash
# Mỗi peer chạy trên một máy/cổng khác nhau
python start_chatapp.py --server-port 8001 --tracker-ip 192.168.x.x --tracker-port 9000
```

### 9.4 Chạy Benchmark

```bash
# So sánh ở các mức concurrency: 50, 100, 150, 200, 250, 300
python benchmark.py -n 300 --step 50 -r 200

# Dùng endpoint ảnh
python benchmark.py --endpoint image -n 100 --step 20
```

---

## 10. Kết luận

Bài tập lớn đã thực hiện được các yêu cầu chính:

1. **Non-blocking HTTP Server**: Xây dựng backend hỗ trợ cả hai cơ chế `coroutine (asyncio)` và `threading`, có thể chuyển đổi linh hoạt qua tham số dòng lệnh.

2. **Xác thực HTTP**: Triển khai đầy đủ HTTP Basic Authentication (RFC 2617/7235) và Cookie-based session management (RFC 6265), kết hợp phân quyền truy cập tài nguyên.

3. **Chat Application Hybrid**: Xây dựng ứng dụng chat sử dụng mô hình kết hợp Client-Server (đăng ký, khám phá peer qua Tracker) và Peer-to-Peer (nhắn tin trực tiếp, broadcast không qua trung gian).

4. **Benchmark**: Công cụ đo hiệu năng cho thấy coroutine vượt trội ở tải cao (I/O-bound, nhiều kết nối đồng thời), trong khi threading phù hợp ở tải vừa.

5. **Tự xây dựng Framework**: `AsynapRous` là micro-framework routing decorator tự implement, không dùng thư viện bên ngoài, tuân thủ yêu cầu của đề bài.
