import socket
import struct
import json
import threading
import select
import asyncio as _real_asyncio

PUSH = 1
PULL = 2

def send_msg(sock, msg_dict):
    """Đóng gói JSON bằng struct header 4 byte (chứa chiều dài) để tránh bị dính cục"""
    data = json.dumps(msg_dict).encode('utf-8')
    header = struct.pack('!I', len(data))
    sock.sendall(header + data)

def recv_msg(sock):
    """Đọc đủ 4 byte header, sau đó đọc đủ N byte body"""
    header_data = _recv_all(sock, 4)
    if not header_data:
        return None
    msg_len = struct.unpack('!I', header_data)[0]
    body_data = _recv_all(sock, msg_len)
    if not body_data:
        return None
    return json.loads(body_data.decode('utf-8'))

def _recv_all(sock, n):
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return data

class MiniZmqSocket:
    def __init__(self, sock_type, is_async=False, hwm=1000):
        self.sock_type = sock_type
        self.is_async = is_async
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.is_server = False
        self.clients = []
        self.lock = threading.Lock()
        self.idx = 0
        
        # --- Khởi tạo Hàng đợi RAM (Queue) và I/O Thread ---
        import queue
        self.outbound_queue = queue.Queue(maxsize=hwm) # Giả lập HWM
        if self.sock_type == PUSH:
            threading.Thread(target=self._io_background_worker, daemon=True).start()

    def bind(self, uri):
        ip, port = uri.replace("tcp://", "").split(":")
        self.sock.bind((ip, int(port)))
        self.sock.listen(5)
        self.is_server = True
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while True:
            try:
                conn, addr = self.sock.accept()
                with self.lock:
                    self.clients.append(conn)
            except:
                break

    def connect(self, uri):
        ip, port = uri.replace("tcp://", "").split(":")
        import time
        while True:
            try:
                self.sock.connect((ip, int(port)))
                break
            except ConnectionRefusedError:
                time.sleep(1) # Đợi Server bật lên

    def _io_background_worker(self):
        """Luồng chạy ngầm: Cứ rảnh là lôi từ Queue trong RAM ra gửi đi qua mạng"""
        while True:
            data = self.outbound_queue.get() # Sẽ ngủ (block) nếu Queue rỗng để tiết kiệm CPU
            
            # Đẩy qua mạng
            if self.clients:
                with self.lock:
                    client = self.clients[self.idx % len(self.clients)]
                    self.idx += 1
                try:
                    send_msg(client, data)
                except:
                    self.clients.remove(client)
            else:
                try:
                    send_msg(self.sock, data)
                except:
                    pass
            self.outbound_queue.task_done()

    # --- Đồng bộ (Sync) ---
    def send_json(self, data):
        """Chỉ nhét vào RAM Queue rồi return ngay lập tức (100% Non-blocking)"""
        import queue
        try:
            self.outbound_queue.put(data, block=False)
        except queue.Full:
            print("[MiniZMQ] HWM đạt giới hạn 1000! Đã vứt bỏ gói tin để cứu RAM.")

    def recv_json(self):
        # Nếu là Server PULL (chờ từ nhiều worker)
        if self.is_server: 
            while True:
                with self.lock:
                    rlist = self.clients.copy()
                if not rlist:
                    import time; time.sleep(0.1)
                    continue
                readable, _, _ = select.select(rlist, [], [], 1.0)
                for c in readable:
                    try:
                        data = recv_msg(c)
                        if data:
                            return data
                        else:
                            self.clients.remove(c)
                    except:
                        self.clients.remove(c)
        # Nếu là Client PULL
        else:
            return recv_msg(self.sock)

    # --- Bất đồng bộ (Async) ---
    async def send_json_async(self, data):
        loop = _real_asyncio.get_running_loop()
        await loop.run_in_executor(None, MiniZmqSocket.send_json, self, data)

    async def recv_json_async(self):
        loop = _real_asyncio.get_running_loop()
        return await loop.run_in_executor(None, MiniZmqSocket.recv_json, self)

class Context:
    def socket(self, sock_type, hwm=1000):
        return MiniZmqSocket(sock_type, is_async=False, hwm=hwm)

class AsyncContext:
    def socket(self, sock_type, hwm=1000):
        sock = MiniZmqSocket(sock_type, is_async=True, hwm=hwm)
        # Ghi đè hàm để hỗ trợ await
        sock.send_json = sock.send_json_async
        sock.recv_json = sock.recv_json_async
        return sock

class asyncio:
    Context = AsyncContext
