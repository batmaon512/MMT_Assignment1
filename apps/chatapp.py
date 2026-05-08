import json
import time
import socket
import threading
from urllib import request as urllib_request

from daemon import AsynapRous

app = AsynapRous()

tracker_ip = "127.0.0.1"
tracker_port = 9000
MESSAGE_QUEUE = []

# Local cache: { name -> {"ip": ..., "port": ...} }
# Cho phép P2P hoạt động kể cả khi tracker offline.
PEER_CACHE = {}

# ─────────────────────────────────────────────────────────────────
#  Tiện ích
# ─────────────────────────────────────────────────────────────────

def json_response(payload, status=200):
    body = json.dumps(payload)
    status_text = "OK" if status == 200 else "Bad Request"
    res = (
        f"HTTP/1.1 {status} {status_text}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n\r\n{body}"
    )
    return res.encode('utf-8')


def make_tracker_request(path, data, req=None):
    """
    Gửi request đến Tracker bằng blocking socket (không dùng asyncio).

    :param path (str): API path trên tracker, vd "/submit-info".
    :param data (dict): JSON body gửi đi.
    :param req: HTTP Request object (để lấy cookie / auth nếu có).
    :return: dict — JSON response từ tracker.
    """
    try:
        body = json.dumps(data).encode('utf-8')

        # Thu thập headers tùy chọn
        cookie     = ""
        auth_hdr   = ""
        if req and req.headers:
            cookie   = req.headers.get('cookie', '')
            auth_hdr = req.headers.get('authorization', '')

        http_request = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {tracker_ip}:{tracker_port}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            + (f"Cookie: {cookie}\r\n" if cookie else "")
            + (f"Authorization: {auth_hdr}\r\n" if auth_hdr else "")
            + f"Connection: close\r\n\r\n"
        ).encode('utf-8') + body

        # Gửi qua blocking TCP socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((tracker_ip, tracker_port))
        s.sendall(http_request)

        # Nhận response
        resp_bytes = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp_bytes += chunk
        s.close()

        # Parse HTTP body
        if b"\r\n\r\n" in resp_bytes:
            resp_body = resp_bytes.split(b"\r\n\r\n", 1)[1]
        else:
            resp_body = resp_bytes

        return json.loads(resp_body.decode('utf-8'))

    except Exception as e:
        return {"code": 0, "error": str(e)}


def send_to_peer_sync(target_ip, target_port, payload):
    """
    Gửi tin nhắn trực tiếp đến peer bằng blocking socket (không dùng asyncio).

    Kết nối TCP trực tiếp → không qua tracker (P2P thuần túy).

    :param target_ip (str): IP của peer nhận.
    :param target_port (int/str): Port của peer nhận.
    :param payload (dict): Dữ liệu tin nhắn.
    :return: bool — True nếu thành công.
    """
    try:
        body = json.dumps(payload).encode('utf-8')
        http_request = (
            f"POST /internal/receive-msg HTTP/1.1\r\n"
            f"Host: {target_ip}:{target_port}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode('utf-8') + body

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((target_ip, int(target_port)))
        s.sendall(http_request)
        s.recv(4096)   # Đọc và bỏ qua response
        s.close()
        return True

    except Exception as e:
        print(f"[ChatApp] Error sending to peer {target_ip}:{target_port}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────
#  Auth routes
# ─────────────────────────────────────────────────────────────────

@app.route('/api/login', methods=['POST'])
def app_login(req):
    if getattr(req, 'user', None):
        body = '{"success": true, "message": "Login successful"}'
        cookie_header = ""
        if hasattr(req, 'new_cookie') and req.new_cookie:
            cookie_header += f"Set-Cookie: {req.new_cookie}\r\n"
        cookie_header += f"Set-Cookie: account={req.user}; Path=/\r\n"
        res = (
            f"HTTP/1.1 200 OK\r\n{cookie_header}"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n{body}"
        )
        return res.encode('utf-8')
    else:
        body = '{"success": false, "error": "Invalid username or password"}'
        res = (
            "HTTP/1.1 401 Unauthorized\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n{body}"
        )
        return res.encode('utf-8')


@app.route('/api/logout', methods=['POST'])
def app_logout(req):
    session_id = None
    if req.cookies:
        session_id = req.cookies.get('session_id')
    if session_id:
        try:
            from daemon.httpadapter import ACTIVE_SESSIONS, remove_session
            ACTIVE_SESSIONS.pop(session_id, None)
            remove_session(session_id)
        except Exception:
            pass
    body = '{"success": true}'
    res = (
        "HTTP/1.1 200 OK\r\n"
        "Set-Cookie: session_id=; Max-Age=0; Path=/; HttpOnly\r\n"
        "Set-Cookie: account=; Max-Age=0; Path=/\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n\r\n{body}"
    )
    return res.encode('utf-8')


# ─────────────────────────────────────────────────────────────────
#  Tracker API routes (sync, blocking socket)
# ─────────────────────────────────────────────────────────────────

@app.route('/submit-info', methods=['POST'])
def submit_info(req):
    """Đăng ký IP:port của peer này với tracker."""
    data = json.loads(req.body) if req.body else {}
    data["name"] = data.get("name") or getattr(req, "user", "")
    res = make_tracker_request("/submit-info", data, req)
    return json_response(res)


@app.route('/get-list', methods=['POST'])
def get_list(req):
    """Lấy danh sách peers online từ tracker, lưu vào cache cục bộ."""
    global PEER_CACHE
    res = make_tracker_request("/get-list", {}, req)
    # Cập nhật cache để dùng offline
    if res.get("code") == 1:
        for peer in res.get("peers", []):
            name = peer.get("name")
            if name:
                PEER_CACHE[name] = {"ip": peer.get("ip"), "port": peer.get("port")}
    return json_response(res)


@app.route('/peers', methods=['POST'])
def peers(req):
    """Trả về danh sách peers trong cache cục bộ."""
    global PEER_CACHE
    peer_list = [
        {"name": n, "ip": info.get("ip"), "port": info.get("port")}
        for n, info in PEER_CACHE.items()
    ]
    return json_response({"code": 1, "peers": peer_list})


@app.route('/online', methods=['POST'])
def online(req):
    """Heartbeat: báo cho tracker biết peer này vẫn online."""
    data = json.loads(req.body) if req.body else {}
    data["name"] = data.get("name") or getattr(req, "user", "")
    res = make_tracker_request("/online", data, req)
    return json_response(res)


@app.route('/connect-peer', methods=['POST'])
def connect_peer(req):
    """
    Lấy thông tin kết nối đến 1 peer cụ thể.

    Thử cache cục bộ trước, fallback về tracker nếu không có.
    """
    global PEER_CACHE
    data = json.loads(req.body) if req.body else {}
    target = data.get("target")
    if not target:
        return json_response({"code": 0, "message": "Missing target"})

    # Thử cache trước
    if target in PEER_CACHE:
        peer = PEER_CACHE[target]
        return json_response({
            "code": 1,
            "message": "Connected (cached)",
            "peer": {"name": target, **peer}
        })

    # Hỏi tracker
    peers_res = make_tracker_request("/get-list", {}, req)
    target_peer = next(
        (p for p in peers_res.get("peers", []) if p["name"] == target),
        None
    )

    if target_peer:
        PEER_CACHE[target] = {"ip": target_peer["ip"], "port": target_peer["port"]}
        return json_response({"code": 1, "message": "Connected", "peer": target_peer})
    else:
        return json_response({"code": 0, "message": "Peer not found"})


# ─────────────────────────────────────────────────────────────────
#  P2P routes (sync, blocking socket, threading cho broadcast)
# ─────────────────────────────────────────────────────────────────

@app.route('/send-peer', methods=['POST'])
def send_peer(req):
    """
    Gửi tin nhắn trực tiếp đến 1 peer (P2P).

    Không qua tracker. Dùng blocking socket.
    """
    global PEER_CACHE
    data = json.loads(req.body) if req.body else {}
    target_name = data.get("to")
    message     = data.get("message")
    sender_name = getattr(req, "user", None) or data.get("from")

    if not target_name or not message:
        return json_response({"code": 0, "message": "Missing fields"})

    # Thử cache trước
    target_peer = PEER_CACHE.get(target_name)
    if not target_peer:
        peers_res = make_tracker_request("/get-list", {}, req)
        found = next(
            (p for p in peers_res.get("peers", []) if p["name"] == target_name),
            None
        )
        if found:
            PEER_CACHE[target_name] = {"ip": found["ip"], "port": found["port"]}
            target_peer = PEER_CACHE[target_name]

    if not target_peer:
        return json_response({
            "code": 0,
            "message": f"Peer '{target_name}' not found"
        })

    payload = {
        "from": sender_name,
        "to":   target_name,
        "message": message,
        "time": time.time() * 1000
    }

    success = send_to_peer_sync(target_peer["ip"], target_peer["port"], payload)
    if success:
        return json_response({"code": 1, "message": "Message sent"})
    else:
        return json_response({"code": 0, "message": "Failed to send message"})


@app.route('/broadcast-peer', methods=['POST'])
def broadcast_peer(req):
    """
    Gửi tin nhắn đến TẤT CẢ peers đồng thời (P2P broadcast).

    Dùng threading thay vì asyncio.gather() để gửi song song.
    Mỗi peer nhận được 1 thread riêng → không chặn nhau.
    """
    global PEER_CACHE
    data = json.loads(req.body) if req.body else {}
    message     = data.get("message")
    sender_name = getattr(req, "user", None) or data.get("from")

    if not message:
        return json_response({"code": 0, "message": "Missing message"})

    # Cập nhật cache từ tracker (nếu tracker online)
    try:
        peers_res = make_tracker_request("/get-list", {}, req)
        for p in peers_res.get("peers", []):
            name = p.get("name")
            if name:
                PEER_CACHE[name] = {"ip": p["ip"], "port": p["port"]}
    except Exception:
        pass   # Dùng cache cũ nếu tracker offline

    payload = {
        "from": sender_name,
        "to":   "broadcast",
        "message": message,
        "time": time.time() * 1000
    }

    # Gửi đồng thời đến tất cả peers bằng threading
    threads = []
    for name, info in PEER_CACHE.items():
        if name == sender_name:
            continue
        t = threading.Thread(
            target=send_to_peer_sync,
            args=(info["ip"], info["port"], payload),
            daemon=True
        )
        t.start()
        threads.append(t)

    # Chờ tất cả thread hoàn thành (tối đa 5s)
    for t in threads:
        t.join(timeout=5)

    return json_response({"code": 1, "message": "Broadcast complete"})


@app.route('/internal/receive-msg', methods=['POST'])
def internal_receive_msg(req):
    """Nhận tin nhắn đến từ peer khác (P2P endpoint)."""
    global MESSAGE_QUEUE
    if req.body:
        try:
            data = json.loads(req.body)
            MESSAGE_QUEUE.append(data)
            return json_response({"code": 1, "message": "Received"})
        except Exception:
            return json_response({"code": 0, "message": "Invalid JSON"})
    return json_response({"code": 0, "message": "Empty body"})


@app.route('/poll-messages', methods=['POST'])
def poll_messages(req):
    """Lấy và xóa tất cả tin nhắn đang chờ trong hàng đợi."""
    global MESSAGE_QUEUE
    msgs = list(MESSAGE_QUEUE)
    MESSAGE_QUEUE.clear()
    return json_response({"code": 1, "messages": msgs})


# ─────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────

def create_chatapp(ip, port, tracker_host, tracker_p):
    global tracker_ip, tracker_port
    tracker_ip   = tracker_host
    tracker_port = tracker_p
    app.prepare_address(ip, port)
    app.run()
