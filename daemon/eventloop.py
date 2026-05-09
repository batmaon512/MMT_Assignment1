"""
daemon.eventloop
~~~~~~~~~~~~~~~~

Module Event Loop tự xây dựng cho daemon package.
Cơ chế: select.select() — 1 thread, nhiều kết nối.

Không dùng asyncio. Không dùng selectors.
Chỉ dùng: socket, select, threading (Lock).

Các class chính:
    - EventLoop        : Vòng lặp sự kiện trung tâm (singleton)
    - SelectHTTPServer : HTTP server tích hợp EventLoop + HttpAdapter pipeline

Cách dùng trong AsynapRous / trackerapp / chatapp:
    Tự động khi backend chạy ở mode "callback":
        python start_backend.py --mode callback
        python start_chatapp.py --mode callback
"""

import select
import socket
import threading
import time
import traceback
import heapq
from collections import deque


# =============================================================================
#  CallbackRegistry — Danh bạ ánh xạ socket → handler function
# =============================================================================

class CallbackRegistry:
    """
    Lưu trữ ánh xạ: socket → callback function.

    Khi select() báo socket X sẵn sàng, EventLoop tra bảng này
    để biết cần gọi hàm nào.

    Attributes:
        _read_callbacks  (dict): {socket: func} cho sự kiện ĐỌC.
        _write_callbacks (dict): {socket: func} cho sự kiện GHI.
        _lock (Lock): Bảo vệ truy cập đồng thời từ nhiều thread.
    """

    def __init__(self):
        self._read_callbacks  = {}
        self._write_callbacks = {}
        self._lock = threading.Lock()

    def register_read(self, sock, callback):
        """Đăng ký callback cho sự kiện ĐỌC trên sock."""
        with self._lock:
            self._read_callbacks[sock] = callback

    def register_write(self, sock, callback):
        """Đăng ký callback cho sự kiện GHI trên sock."""
        with self._lock:
            self._write_callbacks[sock] = callback

    def unregister(self, sock):
        """Hủy theo dõi sock (gọi khi đóng kết nối)."""
        with self._lock:
            self._read_callbacks.pop(sock, None)
            self._write_callbacks.pop(sock, None)

    def get_read_sockets(self):
        with self._lock:
            return list(self._read_callbacks.keys())

    def get_write_sockets(self):
        with self._lock:
            return list(self._write_callbacks.keys())

    def get_read_callback(self, sock):
        with self._lock:
            return self._read_callbacks.get(sock)

    def get_write_callback(self, sock):
        with self._lock:
            return self._write_callbacks.get(sock)


# =============================================================================
#  TaskQueue — Hàng đợi task chạy ngay trong vòng lặp tiếp theo
# =============================================================================

class TaskQueue:
    """
    Hàng đợi cho các callback cần chạy NGAY (không cần chờ I/O).

    Tương đương với asyncio.call_soon().
    """

    def __init__(self):
        self._queue = deque()
        self._lock  = threading.Lock()

    def enqueue(self, callback, *args):
        with self._lock:
            self._queue.append((callback, args))

    def drain(self):
        """Lấy và chạy tất cả task đang chờ."""
        with self._lock:
            pending = list(self._queue)
            self._queue.clear()
        for callback, args in pending:
            try:
                callback(*args)
            except Exception:
                traceback.print_exc()


# =============================================================================
#  EventLoop — Trái tim của hệ thống
# =============================================================================

class TimerHandle:
    """Đối tượng đại diện cho một tác vụ hẹn giờ."""
    def __init__(self, execute_at, callback, args):
        self.execute_at = execute_at
        self.callback = callback
        self.args = args
        self.cancelled = False

    def __lt__(self, other):
        return self.execute_at < other.execute_at

    def cancel(self):
        self.cancelled = True

class EventLoop:
    """
    Vòng lặp sự kiện (Event Loop) tự xây dựng bằng select().

    Nguyên lý 1 vòng lặp (1 tick):
        1. Chạy hết task trong TaskQueue (pending callbacks)
        2. Gọi select.select() → OS trả về danh sách socket sẵn sàng
        3. Gọi callback đã đăng ký cho từng socket sẵn sàng
        4. Quay lại bước 1

    Singleton: toàn bộ process dùng chung 1 EventLoop instance.
    """

    _instance = None
    _lock      = threading.Lock()

    @classmethod
    def get_instance(cls, select_timeout=0.05):
        """Lấy hoặc tạo EventLoop singleton."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(select_timeout)
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset singleton (dùng cho test)."""
        with cls._lock:
            cls._instance = None

    def __init__(self, select_timeout=0.05):
        """
        :param select_timeout (float): Thời gian (giây) select() chờ tối đa
               khi không có sự kiện. Mặc định 50ms.
        """
        self._registry       = CallbackRegistry()
        self._task_queue     = TaskQueue()
        self._timers         = [] # Hàng đợi Min-Heap cho hẹn giờ
        self._running        = False
        self._select_timeout = select_timeout

    def call_later(self, delay, callback, *args):
        """Lên lịch callback chạy sau `delay` giây."""
        execute_at = time.time() + delay
        handle = TimerHandle(execute_at, callback, args)
        with self._lock:
            heapq.heappush(self._timers, handle)
        return handle

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    def register_read(self, sock, callback):
        """
        Đăng ký: Khi sock có dữ liệu đến → gọi callback(sock).

        :param sock: socket object (phải ở non-blocking mode).
        :param callback: callable nhận 1 tham số là sock.
        """
        self._registry.register_read(sock, callback)

    def register_write(self, sock, callback):
        """Đăng ký: Khi sock có thể ghi → gọi callback(sock)."""
        self._registry.register_write(sock, callback)

    def unregister(self, sock):
        """Hủy theo dõi sock."""
        self._registry.unregister(sock)

    def call_soon(self, callback, *args):
        """Lên lịch callback chạy trong vòng lặp tiếp theo."""
        self._task_queue.enqueue(callback, *args)

    # ------------------------------------------------------------------
    #  Vòng lặp chính
    # ------------------------------------------------------------------

    def _run_once(self):
        """
        Thực hiện 1 iteration của event loop.
        """
        # Bước 1: Drain TaskQueue
        self._task_queue.drain()

        # Bước 1.5: Xử lý các Timer đã đến hạn
        now = time.time()
        with self._lock:
            while self._timers and self._timers[0].execute_at <= now:
                handle = heapq.heappop(self._timers)
                if not handle.cancelled:
                    self._task_queue.enqueue(handle.callback, *handle.args)
        
        # Bước 2: Tính toán timeout thông minh cho select()
        timeout = self._select_timeout
        with self._lock:
            if self._timers:
                time_to_next = self._timers[0].execute_at - time.time()
                timeout = max(0.0, min(timeout, time_to_next))

        r_list = self._registry.get_read_sockets()
        w_list = self._registry.get_write_sockets()

        if not r_list and not w_list:
            time.sleep(timeout)
            return

        try:
            readable, writable, _ = select.select(
                r_list, w_list, [], timeout
            )
        except (ValueError, OSError):
            self._cleanup_dead_sockets(r_list, w_list)
            return

        # Bước 3a: Xử lý sự kiện ĐỌC
        for sock in readable:
            cb = self._registry.get_read_callback(sock)
            if cb:
                try:
                    cb(sock)
                except Exception:
                    traceback.print_exc()
                    self.unregister(sock)

        # Bước 3b: Xử lý sự kiện GHI
        for sock in writable:
            cb = self._registry.get_write_callback(sock)
            if cb:
                try:
                    cb(sock)
                except Exception:
                    traceback.print_exc()
                    self.unregister(sock)

    def run_forever(self):
        """
        Chạy event loop liên tục cho đến khi gọi stop().
        1 thread duy nhất phục vụ nhiều kết nối đồng thời.
        """
        print("[EventLoop] Starting select()-based event loop")
        self._running = True
        while self._running:
            self._run_once()
        print("[EventLoop] Stopped.")

    def stop(self):
        """Dừng vòng lặp sau khi kết thúc iteration hiện tại."""
        self._running = False

    def _cleanup_dead_sockets(self, r_list, w_list):
        for sock in r_list + w_list:
            try:
                select.select([sock], [], [], 0)
            except (ValueError, OSError):
                self.unregister(sock)


# =============================================================================
#  ConnectionBuffer — Buffer gom dữ liệu từng mảnh của 1 kết nối
# =============================================================================

class ConnectionBuffer:
    """
    Buffer lưu dữ liệu chưa đọc hết của 1 TCP kết nối.

    Lý do cần buffer:
    - select() báo "readable" không có nghĩa toàn bộ request đã đến.
    - recv() có thể trả về từng phần nhỏ → cần gom lại.
    - HTTP request kết thúc bằng \\r\\n\\r\\n → ta biết request đã đầy đủ.

    :param conn: socket kết nối với client.
    :param addr: (ip, port) của client.
    """

    def __init__(self, conn, addr):
        self.conn   = conn
        self.addr   = addr
        self.buffer = b""
        self.done   = False   # True khi đã nhận đủ 1 HTTP request
        self.last_active_time = time.time()

    def feed(self, data: bytes):
        """Thêm dữ liệu vào buffer. Đánh dấu done khi gặp \\r\\n\\r\\n."""
        self.last_active_time = time.time()
        self.buffer += data
        if b"\r\n\r\n" in self.buffer:
            self.done = True
            
    def reset(self):
        """Reset buffer để tái sử dụng socket (Keep-Alive)."""
        self.buffer = b""
        self.done = False
        self.last_active_time = time.time()

    def get_request(self) -> str:
        """Trả về toàn bộ request dưới dạng string."""
        return self.buffer.decode("utf-8", errors="replace")


# =============================================================================
#  SelectHTTPServer — HTTP Server tích hợp EventLoop
# =============================================================================

class SelectHTTPServer:
    """
    HTTP Server sử dụng EventLoop (select-based).

    Tích hợp với HttpAdapter pipeline của daemon thông qua
    tham số request_handler.

    Luồng xử lý 1 request:
        Client kết nối
            → server_sock readable → _on_new_connection()
            → accept() + register_read(conn, _on_data)
        Client gửi data
            → conn readable → _on_data()
            → gom vào ConnectionBuffer
            → đủ request → _handle_request()
            → gọi request_handler(raw_request, addr) → bytes
            → sendall() → đóng conn

    :param ip: IP bind (vd: "0.0.0.0").
    :param port: Port lắng nghe.
    :param request_handler: callable(raw_request: str, addr: tuple) -> bytes.
                            Xem HttpAdapter.make_callback_handler() để tạo handler
                            đầy đủ (auth + routing + response).
    """

    def __init__(self, ip: str, port: int, request_handler):
        self.ip              = ip
        self.port            = port
        self.request_handler = request_handler
        self.loop            = EventLoop.get_instance()
        self._buffers        = {}   # {conn: ConnectionBuffer}
        self._server_sock    = None
        
        # Bắt đầu vòng tuần tra dọn rác (mỗi 10 giây)
        self.loop.call_later(10.0, self._cleanup_idle_connections)

    def start(self):
        """Tạo server socket và đăng ký vào event loop."""
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.setblocking(False)
        self._server_sock.bind((self.ip, self.port))
        self._server_sock.listen(128)

        self.loop.register_read(self._server_sock, self._on_new_connection)
        print(f"[SelectHTTPServer] Listening on {self.ip}:{self.port}")

    def _on_new_connection(self, server_sock):
        """
        Callback: Có client kết nối đến.

        accept() lấy conn mới, đặt non-blocking, đăng ký _on_data.
        """
        try:
            conn, addr = server_sock.accept()
            conn.setblocking(False)
            print(f"[SelectHTTPServer] New connection from {addr}")
            self._buffers[conn] = ConnectionBuffer(conn, addr)
            self.loop.register_read(conn, self._on_data)
        except BlockingIOError:
            pass
        except Exception as e:
            print(f"[SelectHTTPServer] Accept error: {e}")

    def _on_data(self, conn):
        """
        Callback: conn có dữ liệu để đọc.

        Non-blocking recv() → gom vào buffer.
        Khi buffer đủ 1 HTTP request → xử lý.
        """
        buf = self._buffers.get(conn)
        if not buf:
            self._close_conn(conn)
            return

        try:
            data = conn.recv(4096)
        except BlockingIOError:
            return   # Chưa có dữ liệu — chờ select() lần sau
        except OSError:
            self._close_conn(conn)
            return

        if not data:
            self._close_conn(conn)  # Client đóng kết nối
            return

        buf.feed(data)

        if buf.done:
            self._handle_request(conn, buf)

    def _handle_request(self, conn, buf):
        """
        Gọi request_handler để xử lý HTTP request và gửi response.
        """
        try:
            raw_request = buf.get_request()
            response    = self.request_handler(raw_request, buf.addr)

            if isinstance(response, str):
                response = response.encode("utf-8")

            conn.sendall(response)
            
            # --- KIỂM TRA KEEP-ALIVE ---
            if "connection: keep-alive" in raw_request.lower():
                buf.reset() # Tái sử dụng ống nước, không đóng!
            else:
                self._close_conn(conn) # Đóng kết nối

        except Exception:
            traceback.print_exc()
            self._close_conn(conn)

    def _cleanup_idle_connections(self):
        """Cai ngục đi tuần tiêu diệt kết nối nhàn rỗi (> 60s)"""
        now = time.time()
        for conn, buf in list(self._buffers.items()):
            if now - buf.last_active_time > 60.0:
                print(f"[Terminator] Timeout closing idle connection: {buf.addr}")
                self._close_conn(conn)
                
        # Tiếp tục hẹn giờ cho lần đi tuần sau
        if self.loop._running:
            self.loop.call_later(10.0, self._cleanup_idle_connections)

    def _close_conn(self, conn):
        """Đóng kết nối và dọn dẹp khỏi registry."""
        self.loop.unregister(conn)
        self._buffers.pop(conn, None)
        try:
            conn.close()
        except OSError:
            pass


# =============================================================================
#  HttpAdapter Integration — Tích hợp với daemon.httpadapter
# =============================================================================

def make_http_handler(ip, port, routes):
    """
    Tạo HTTP request handler dùng HttpAdapter.process_request().

    EventLoop (select) chịu trách nhiệm I/O (recv/send).
    HttpAdapter chịu trách nhiệm giao thức HTTP (auth, routing, response).

    Phân tầng rõ ràng:
        EventLoop layer  →  SelectHTTPServer  →  ConnectionBuffer (recv)
        HTTP layer       →  HttpAdapter.process_request()          (parse/auth/route)
        API layer        →  master_api_handler()                   (business logic)

    :param ip (str): IP của backend server.
    :param port (int): Port của backend server.
    :param routes (dict): Bảng route handlers {(method, path): handler_func}.
    :return: callable(raw_request: str, addr: tuple) -> bytes
    """
    from .httpadapter import HttpAdapter

    def handler(raw_request: str, addr: tuple) -> bytes:
        """
        Gọi HttpAdapter.process_request() để xử lý request.

        HttpAdapter đã có đầy đủ:
            - Parse HTTP request (Request.prepare)
            - Xác thực: Cookie session_id + Basic Auth
            - Phân quyền: public / private / API
            - Routing: gọi handler từ routes
            - Build response bytes
        """
        adapter = HttpAdapter(ip, port, None, addr, routes)
        return adapter.process_request(raw_request, addr)

    return handler


def run_select_server(ip: str, port: int, routes: dict):
    """
    Khởi động HTTP server dùng select() event loop.

    Kết hợp:
        make_http_handler() → HttpAdapter.process_request() (HTTP layer)
        SelectHTTPServer    → EventLoop                     (I/O layer)

    Được gọi từ backend.py khi mode="callback".

    :param ip (str): IP bind.
    :param port (int): Port lắng nghe.
    :param routes (dict): Bảng route handler.
    """
    print("[eventloop] mode=callback — select() EventLoop (no asyncio)")

    if routes:
        print("[eventloop] Registered routes:")
        for (method, path), func in routes.items():
            print(f"   + [{method}] {path} → {func.__name__}")

    handler = make_http_handler(ip, port, routes)
    loop    = EventLoop.get_instance()
    server  = SelectHTTPServer(ip, port, handler)
    server.start()
    loop.run_forever()

