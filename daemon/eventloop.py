"""
daemon.eventloop
~~~~~~~~~~~~~~~~

Custom-built Event Loop for daemon package.
Mechanism: select.select() — 1 thread, multiple connections.

Does not use asyncio. Does not use selectors.
Uses only: socket, select, threading (Lock).

Main classes:
    - EventLoop        : Central event loop (singleton)
    - SelectHTTPServer : HTTP server integrating EventLoop + HttpAdapter pipeline

Usage with AsynapRous / trackerapp / chatapp:
    Automatic when backend runs in "callback" mode:
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
#  CallbackRegistry — Maps socket → handler function
# =============================================================================

class CallbackRegistry:
    """
    Stores the mapping: socket → callback function.

    When select() reports socket X is ready, EventLoop queries this table
    to determine which function to call.

    Attributes:
        _read_callbacks (dict): {socket: func} for READ events.
        _write_callbacks (dict): {socket: func} for WRITE events.
        _lock (Lock): Protects concurrent access from multiple threads.
    """

    def __init__(self):
        self._read_callbacks = {}
        self._write_callbacks = {}
        self._lock = threading.Lock()

    def register_read(self, sock, callback):
        """Register callback for READ event on socket."""
        with self._lock:
            self._read_callbacks[sock] = callback

    def register_write(self, sock, callback):
        """Register callback for WRITE event on socket."""
        with self._lock:
            self._write_callbacks[sock] = callback

    def unregister(self, sock):
        """Stop monitoring socket (called when closing connection)."""
        with self._lock:
            self._read_callbacks.pop(sock, None)
            self._write_callbacks.pop(sock, None)

    def get_read_sockets(self):
        """Get list of sockets registered for READ events."""
        with self._lock:
            return list(self._read_callbacks.keys())

    def get_write_sockets(self):
        """Get list of sockets registered for WRITE events."""
        with self._lock:
            return list(self._write_callbacks.keys())

    def get_read_callback(self, sock):
        """Get READ callback for socket, or None."""
        with self._lock:
            return self._read_callbacks.get(sock)

    def get_write_callback(self, sock):
        """Get WRITE callback for socket, or None."""
        with self._lock:
            return self._write_callbacks.get(sock)


# =============================================================================
#  TaskQueue — Queue for immediate tasks in next event loop iteration
# =============================================================================

class TaskQueue:
    """
    Queue for callbacks that need to run IMMEDIATELY (no I/O wait needed).

    Equivalent to asyncio.call_soon().
    """

    def __init__(self):
        self._queue = deque()
        self._lock = threading.Lock()

    def enqueue(self, callback, *args):
        """Add a callback and its arguments to the queue."""
        with self._lock:
            self._queue.append((callback, args))

    def drain(self):
        """Retrieve and execute all pending tasks."""
        with self._lock:
            pending = list(self._queue)
            self._queue.clear()
        for callback, args in pending:
            try:
                callback(*args)
            except Exception:
                traceback.print_exc()


# =============================================================================
#  EventLoop — Heart of the system
# =============================================================================

class TimerHandle:
    """Represents a scheduled timer task."""

    def __init__(self, execute_at, callback, args):
        self.execute_at = execute_at
        self.callback = callback
        self.args = args
        self.cancelled = False

    def __lt__(self, other):
        """Compare timer handles by execution time for heap ordering."""
        return self.execute_at < other.execute_at

    def cancel(self):
        """Mark this timer as cancelled."""
        self.cancelled = True

class EventLoop:
    """
    Custom-built Event Loop using select().

    One event loop iteration (one tick):
        1. Drain all tasks in TaskQueue (pending callbacks)
        2. Call select.select() → OS returns list of ready sockets
        3. Call registered callback for each ready socket
        4. Return to step 1

    Singleton: entire process shares one EventLoop instance.
    """

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, select_timeout=0.05):
        """Get or create EventLoop singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(select_timeout)
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset singleton instance (for testing)."""
        with cls._lock:
            cls._instance = None

    def __init__(self, select_timeout=0.05):
        """
        Initialize EventLoop.

        :param select_timeout (float): Maximum time in seconds that select()
                                       waits when no events are pending.
                                       Default: 50ms.
        """
        self._registry = CallbackRegistry()
        self._task_queue = TaskQueue()
        self._timers = []  # Min-Heap priority queue for scheduled timers
        self._running = False
        self._select_timeout = select_timeout

    def call_later(self, delay, callback, *args):
        """Schedule callback to run after `delay` seconds."""
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
        Register callback: when socket has data → call callback(sock).

        :param sock: socket object (must be in non-blocking mode).
        :param callback: callable accepting one parameter (socket).
        """
        self._registry.register_read(sock, callback)

    def register_write(self, sock, callback):
        """
        Register callback: when socket is writable → call callback(sock).

        :param sock: socket object (must be in non-blocking mode).
        :param callback: callable accepting one parameter (socket).
        """
        self._registry.register_write(sock, callback)

    def unregister(self, sock):
        """Stop monitoring socket."""
        self._registry.unregister(sock)

    def call_soon(self, callback, *args):
        """Schedule callback to run in the next event loop iteration."""
        self._task_queue.enqueue(callback, *args)

    # ------------------------------------------------------------------
    #  Main event loop
    # ------------------------------------------------------------------

    def _run_once(self):
        """Execute one iteration of the event loop."""
        # Step 1: Process all pending tasks
        self._task_queue.drain()

        # Step 2: Process timers that have reached their deadline
        now = time.time()
        with self._lock:
            while self._timers and self._timers[0].execute_at <= now:
                handle = heapq.heappop(self._timers)
                if not handle.cancelled:
                    self._task_queue.enqueue(handle.callback, *handle.args)

        # Step 3: Calculate intelligent timeout for select()
        timeout = self._select_timeout
        with self._lock:
            if self._timers:
                time_to_next = self._timers[0].execute_at - time.time()
                timeout = max(0.0, min(timeout, time_to_next))

        read_sockets = self._registry.get_read_sockets()
        write_sockets = self._registry.get_write_sockets()

        if not read_sockets and not write_sockets:
            time.sleep(timeout)
            return

        try:
            readable, writable, _ = select.select(
                read_sockets, write_sockets, [], timeout
            )
        except (ValueError, OSError):
            self._cleanup_dead_sockets(read_sockets, write_sockets)
            return

        # Step 4a: Process READ events
        for sock in readable:
            callback = self._registry.get_read_callback(sock)
            if callback:
                try:
                    callback(sock)
                except Exception:
                    traceback.print_exc()
                    self.unregister(sock)

        # Step 4b: Process WRITE events
        for sock in writable:
            callback = self._registry.get_write_callback(sock)
            if callback:
                try:
                    callback(sock)
                except Exception:
                    traceback.print_exc()
                    self.unregister(sock)

    def run_forever(self):
        """
        Run event loop continuously until stop() is called.

        One thread serves multiple concurrent connections.
        """
        print("[EventLoop] Starting select()-based event loop")
        self._running = True
        while self._running:
            self._run_once()
        print("[EventLoop] Stopped.")

    def stop(self):
        """Stop the event loop after completing current iteration."""
        self._running = False

    def _cleanup_dead_sockets(self, read_list, write_list):
        """Remove dead/closed sockets from the registry."""
        for sock in read_list + write_list:
            try:
                select.select([sock], [], [], 0)
            except (ValueError, OSError):
                self.unregister(sock)


# =============================================================================
#  ConnectionBuffer — Aggregates partial data from one connection
# =============================================================================

class ConnectionBuffer:
    """
    Buffer that stores incomplete data from one TCP connection.

    Why we need a buffer:
    - select() saying "readable" doesn't mean the complete request arrived.
    - recv() may return data in small chunks → we need to accumulate.
    - HTTP request ends with \\r\\n\\r\\n → lets us know when complete.

    :param conn: socket connection with client.
    :param addr: (ip, port) of client.
    """

    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.buffer = b""
        self.done = False  # True when a complete HTTP request is received
        self.last_active_time = time.time()

    def feed(self, data: bytes):
        """Add data to buffer. Mark done when \\r\\n\\r\\n is encountered."""
        self.last_active_time = time.time()
        self.buffer += data
        if b"\r\n\r\n" in self.buffer:
            self.done = True

    def reset(self):
        """Reset buffer for socket reuse (Keep-Alive)."""
        self.buffer = b""
        self.done = False
        self.last_active_time = time.time()

    def get_request(self) -> str:
        """Return the complete request as a string."""
        return self.buffer.decode("utf-8", errors="replace")


# =============================================================================
#  SelectHTTPServer — HTTP Server integrated with EventLoop
# =============================================================================

class SelectHTTPServer:
    """
    HTTP Server using EventLoop (select-based).

    Integrates with daemon's HttpAdapter pipeline via request_handler.

    Request processing flow:
        Client connects
            → server_sock readable → _on_new_connection()
            → accept() + register_read(conn, _on_data)
        Client sends data
            → conn readable → _on_data()
            → aggregate into ConnectionBuffer
            → complete request → _handle_request()
            → call request_handler(raw_request, addr) → bytes
            → sendall() → close conn

    :param ip: IP to bind (e.g., "0.0.0.0").
    :param port: Port to listen on.
    :param request_handler: callable(raw_request: str, addr: tuple) -> bytes.
                            See HttpAdapter.process_request() for complete
                            handler (auth + routing + response).
    """

    def __init__(self, ip: str, port: int, request_handler):
        self.ip = ip
        self.port = port
        self.request_handler = request_handler
        self.loop = EventLoop.get_instance()
        self._buffers = {}  # {conn: ConnectionBuffer}
        self._server_sock = None

        # Start periodic cleanup (every 10 seconds)
        self.loop.call_later(10.0, self._cleanup_idle_connections)

    def start(self):
        """Create server socket and register with event loop."""
        self._server_sock = socket.socket(socket.AF_INET,
                                          socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET,
                                     socket.SO_REUSEADDR, 1)
        self._server_sock.setblocking(False)
        self._server_sock.bind((self.ip, self.port))
        self._server_sock.listen(128)

        self.loop.register_read(self._server_sock,
                                self._on_new_connection)
        print(f"[SelectHTTPServer] Listening on {self.ip}:{self.port}")

    def _on_new_connection(self, server_sock):
        """
        Callback: Client connection incoming.

        accept() gets new connection, sets non-blocking, registers _on_data.
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
        Callback: Socket has data to read.

        Non-blocking recv() → aggregate into buffer.
        When buffer has complete HTTP request → process it.
        """
        buf = self._buffers.get(conn)
        if not buf:
            self._close_conn(conn)
            return

        try:
            data = conn.recv(4096)
        except BlockingIOError:
            return  # No data yet — wait for next select()
        except OSError:
            self._close_conn(conn)
            return

        if not data:
            self._close_conn(conn)  # Client closed connection
            return

        buf.feed(data)

        if buf.done:
            self._handle_request(conn, buf)

    def _handle_request(self, conn, buf):
        """Call request_handler to process HTTP request and send response."""
        try:
            raw_request = buf.get_request()
            response = self.request_handler(raw_request, buf.addr)

            if isinstance(response, str):
                response = response.encode("utf-8")

            conn.sendall(response)

            # --- CHECK KEEP-ALIVE ---
            if "connection: keep-alive" in raw_request.lower():
                buf.reset()  # Reuse connection, don't close!
            else:
                self._close_conn(conn)  # Close connection

        except Exception:
            traceback.print_exc()
            self._close_conn(conn)

    def _cleanup_idle_connections(self):
        """Periodic cleanup: terminate idle connections (> 60s)."""
        now = time.time()
        for conn, buf in list(self._buffers.items()):
            if now - buf.last_active_time > 60.0:
                print(f"[Terminator] Timeout closing idle connection: {buf.addr}")
                self._close_conn(conn)

        # Schedule next cleanup
        if self.loop._running:
            self.loop.call_later(10.0, self._cleanup_idle_connections)

    def _close_conn(self, conn):
        """Close connection and clean up from registry."""
        self.loop.unregister(conn)
        self._buffers.pop(conn, None)
        try:
            conn.close()
        except OSError:
            pass


# =============================================================================
#  HttpAdapter Integration — Integration with daemon.httpadapter
# =============================================================================

def make_http_handler(ip, port, routes):
    """
    Create HTTP request handler using HttpAdapter.process_request().

    EventLoop (select) handles I/O (recv/send).
    HttpAdapter handles HTTP protocol (auth, routing, response).

    Clear layering:
        EventLoop layer  →  SelectHTTPServer  →  ConnectionBuffer (recv)
        HTTP layer       →  HttpAdapter.process_request() (parse/auth/route)
        API layer        →  master_api_handler()          (business logic)

    :param ip (str): IP of backend server.
    :param port (int): Port of backend server.
    :param routes (dict): Route handler table {(method, path): handler_func}.
    :return: callable(raw_request: str, addr: tuple) -> bytes
    """
    from .httpadapter import HttpAdapter

    def handler(raw_request: str, addr: tuple) -> bytes:
        """
        Call HttpAdapter.process_request() to handle the request.

        HttpAdapter handles:
            - Parse HTTP request (Request.prepare)
            - Authentication: Cookie session_id + Basic Auth
            - Authorization: public / private / API
            - Routing: call handler from routes
            - Build response bytes
        """
        adapter = HttpAdapter(ip, port, None, addr, routes)
        return adapter.process_request(raw_request, addr)

    return handler


def run_select_server(ip: str, port: int, routes: dict):
    """
    Start HTTP server using select() event loop.

    Combines:
        make_http_handler() → HttpAdapter.process_request() (HTTP layer)
        SelectHTTPServer    → EventLoop                  (I/O layer)

    Called from backend.py when mode="callback".

    :param ip (str): IP to bind.
    :param port (int): Port to listen on.
    :param routes (dict): Route handler table.
    """
    print("[eventloop] mode=callback — select() EventLoop (no asyncio)")

    if routes:
        print("[eventloop] Registered routes:")
        for (method, path), func in routes.items():
            print(f"   + [{method}] {path} → {func.__name__}")

    handler = make_http_handler(ip, port, routes)
    loop = EventLoop.get_instance()
    server = SelectHTTPServer(ip, port, handler)
    server.start()
    loop.run_forever()

