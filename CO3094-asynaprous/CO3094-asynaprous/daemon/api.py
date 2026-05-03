import json
import threading
import time
from .response import Response

ONLINE_TTL = 5.0
ONLINE = {}
SIGNAL_BOX = {}
DELAY_OFFER = {}
PEER_REGISTRY = {}
PEER_MESSAGES = {}
REGISTRY_LOCK = threading.Lock()


def _json_response(req, payload, status=200, extra_headers=None):
    resp = Response()
    resp.status_code = status
    resp.reason = {
        200: "OK",
        201: "Created",
        400: "Bad Request",
        401: "Unauthorized",
        404: "Not Found",
    }.get(status, "OK")
    resp._content = json.dumps(payload).encode('utf-8')
    resp.headers['Content-Type'] = 'application/json'
    if extra_headers:
        for key, value in extra_headers.items():
            resp.headers[key] = value
    header_str = resp.build_response_header(req)
    return header_str + resp._content


def _parse_json_body(req):
    if not req.body:
        return None
    try:
        return json.loads(req.body)
    except Exception:
        return None


def _cleanup_online(now):
    expired = [name for name, ts in ONLINE.items() if now - ts > ONLINE_TTL]
    for name in expired:
        ONLINE.pop(name, None)

def app_echo(req):
    """
    API Echo: Nhận chữ gì thì trả về đúng chữ đó.
    Sử dụng Response object để đóng gói Header chuyên nghiệp.
    """
    message = "Khong co du lieu"
    if req.body:
        try:
            data = json.loads(req.body)
            message = data.get('text', '')
        except:
            message = req.body
            
    response_body = f"ECHO: Ban vua noi la '{message}'"
    
    # Sử dụng ông Thủ kho Response để tự động tính Content-Length và Date
    resp = Response()
    resp._content = response_body.encode('utf-8')
    resp.headers['Content-Type'] = 'text/plain'
    
    header_str = resp.build_response_header(req)
    return header_str + resp._content

def app_hello(req):
    """API Chào hỏi"""
    response_body = "HELLO: Chao mung ban den voi may chu AsynapRous!"
    
    resp = Response()
    resp._content = response_body.encode('utf-8')
    resp.headers['Content-Type'] = 'text/plain'
    
    header_str = resp.build_response_header(req)
    return header_str + resp._content

def app_login(req):
    """Login endpoint returning JSON for the web client."""
    # HttpAdapter validates Basic auth and injects req.user on success.
    if req.user:
        body = '{"success": true, "message": "Login successful"}'
        cookie_header = ""
        if hasattr(req, 'new_cookie') and req.new_cookie:
            cookie_header += f"Set-Cookie: {req.new_cookie}\r\n"
        cookie_header += f"Set-Cookie: account={req.user}; Path=/\r\n"
        res = f"HTTP/1.1 200 OK\r\n{cookie_header}Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n{body}"
        return res.encode('utf-8')
    else:
        body = '{"success": false, "error": "Invalid username or password"}'
        res = (
            "HTTP/1.1 401 Unauthorized\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n{body}"
        )
        return res.encode('utf-8')

def app_me(req):
    """Return the current authenticated user."""
    if req.user:
        body = '{"username": "' + req.user + '"}'
        res = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n{body}"
        return res.encode('utf-8')
    else:
        body = '{"error": "Chua dang nhap"}'
        res = f"HTTP/1.1 401 Unauthorized\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n{body}"
        return res.encode('utf-8')

def app_logout(req):
    """Logout endpoint that clears both session and account cookies."""
    session_id = None
    if req.cookies:
        session_id = req.cookies.get('session_id')
    if session_id:
        try:
            from .httpadapter import ACTIVE_SESSIONS, remove_session
            ACTIVE_SESSIONS.pop(session_id, None)
            remove_session(session_id)
        except Exception:
            pass
    body = '{"success": true}'
    # Đặt thời hạn Max-Age=0 để Trình duyệt tự xóa Cookie
    res = (
        "HTTP/1.1 200 OK\r\n"
        "Set-Cookie: session_id=; Max-Age=0; Path=/; HttpOnly\r\n"
        "Set-Cookie: account=; Max-Age=0; Path=/\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n\r\n{body}"
    )
    return res.encode('utf-8')

def app_status(req):
    """Health check endpoint."""
    response_body = '{"status": "online", "server": "AsynapRous", "version": "1.0", "message": "Server dang hoat dong tot!"}'
    
    resp = Response()
    resp._content = response_body.encode('utf-8')
    resp.headers['Content-Type'] = 'application/json'
    
    header_str = resp.build_response_header(req)
    return header_str + resp._content


def app_online(req):
    data = _parse_json_body(req)
    if not data:
        return _json_response(req, {"code": 0, "message": "Invalid JSON"}, status=400)

    name = (data.get("name") or req.user or "").strip()
    ip = (data.get("ip") or "").strip()
    port = data.get("port")

    if not name:
        return _json_response(req, {"code": 0, "message": "Missing name"}, status=400)

    now = time.time()
    with REGISTRY_LOCK:
        ONLINE[name] = now
        _cleanup_online(now)
        if ip or port:
            PEER_REGISTRY[name] = {
                "ip": ip,
                "port": port,
                "last_seen": now,
            }

    return _json_response(req, {"code": 1, "online": sorted(list(ONLINE.keys()))})


def app_submit_info(req):
    data = _parse_json_body(req)
    if not data:
        return _json_response(req, {"code": 0, "message": "Invalid JSON"}, status=400)

    name = (data.get("name") or req.user or "").strip()
    ip = (data.get("ip") or "").strip()
    port = data.get("port")

    if not name:
        return _json_response(req, {"code": 0, "message": "Missing name"}, status=400)

    now = time.time()
    with REGISTRY_LOCK:
        PEER_REGISTRY[name] = {"ip": ip, "port": port, "last_seen": now}
        ONLINE[name] = now
        _cleanup_online(now)

    return _json_response(req, {"code": 1, "message": "Registered"}, status=201)


def app_get_list(req):
    now = time.time()
    with REGISTRY_LOCK:
        _cleanup_online(now)
        peers = [
            {"name": name, **info}
            for name, info in PEER_REGISTRY.items()
            if ONLINE.get(name)
        ]
    return _json_response(req, {"code": 1, "peers": peers})


def app_connect_peer(req):
    data = _parse_json_body(req)
    if not data:
        return _json_response(req, {"code": 0, "message": "Invalid JSON"}, status=400)

    target = (data.get("target") or "").strip()
    if not target:
        return _json_response(req, {"code": 0, "message": "Missing target"}, status=400)

    with REGISTRY_LOCK:
        info = PEER_REGISTRY.get(target)

    if not info:
        return _json_response(req, {"code": 0, "message": "Target not found"}, status=404)

    return _json_response(req, {"code": 1, "peer": {"name": target, **info}})


def app_broadcast_peer(req):
    data = _parse_json_body(req)
    if not data:
        return _json_response(req, {"code": 0, "message": "Invalid JSON"}, status=400)

    sender = (data.get("from") or req.user or "").strip()
    message = data.get("message")
    if not sender or message is None:
        return _json_response(req, {"code": 0, "message": "Missing fields"}, status=400)

    with REGISTRY_LOCK:
        for name in PEER_REGISTRY.keys():
            if name == sender:
                continue
            PEER_MESSAGES.setdefault(name, []).append({
                "from": sender,
                "message": message,
                "time": time.time(),
            })

    return _json_response(req, {"code": 1, "message": "Broadcast queued"})


def app_send_peer(req):
    data = _parse_json_body(req)
    if not data:
        return _json_response(req, {"code": 0, "message": "Invalid JSON"}, status=400)

    sender = (data.get("from") or req.user or "").strip()
    target = (data.get("to") or "").strip()
    message = data.get("message")
    if not sender or not target or message is None:
        return _json_response(req, {"code": 0, "message": "Missing fields"}, status=400)

    with REGISTRY_LOCK:
        PEER_MESSAGES.setdefault(target, []).append({
            "from": sender,
            "message": message,
            "time": time.time(),
        })

    return _json_response(req, {"code": 1, "message": "Message queued"})


def app_signal(req):
    data = _parse_json_body(req)
    if not data:
        return _json_response(req, {"code": 0, "message": "Invalid JSON"}, status=400)

    sender = data.get("from")
    target = data.get("to")
    msg_type = data.get("type")

    if not sender or not target or not msg_type:
        return _json_response(req, {"code": 0, "message": "Missing fields"}, status=400)

    key = "->".join(sorted([sender, target]))
    if msg_type == "offer":
        now = time.time()
        last_time = DELAY_OFFER.get(key, 0)
        if now - last_time < 3:
            return _json_response(req, {"code": 2, "message": "Offer too soon"})
        DELAY_OFFER[key] = now

    with REGISTRY_LOCK:
        SIGNAL_BOX.setdefault(target, []).append({
            "from": sender,
            "type": msg_type,
            "offer": data.get("offer"),
            "answer": data.get("answer"),
            "candidate": data.get("candidate"),
        })

    return _json_response(req, {"code": 1, "message": "Signal stored"})


def app_signal_poll(req):
    data = _parse_json_body(req)
    if not data:
        return _json_response(req, {"code": 0, "message": "Invalid JSON"}, status=400)

    name = data.get("name")
    if not name:
        return _json_response(req, {"code": 0, "message": "Missing name"}, status=400)

    with REGISTRY_LOCK:
        messages = SIGNAL_BOX.get(name, [])
        SIGNAL_BOX[name] = []

    return _json_response(req, {"code": 1, "messages": messages})

# API route table
API_ROUTES = {
    # POST/PUT handlers
    ('POST', '/echo'): app_echo,
    ('PUT', '/hello'): app_hello,
    ('POST', '/api/login'): app_login,
    ('POST', '/api/logout'): app_logout,
    ('POST', '/online'): app_online,
    ('POST', '/signal'): app_signal,
    ('POST', '/signal_poll'): app_signal_poll,
    ('POST', '/submit-info'): app_submit_info,
    ('POST', '/get-list'): app_get_list,
    ('POST', '/connect-peer'): app_connect_peer,
    ('POST', '/broadcast-peer'): app_broadcast_peer,
    ('POST', '/send-peer'): app_send_peer,
    
    # GET handlers
    ('GET', '/hello'): app_hello,
    ('GET', '/status'): app_status,
    ('GET', '/api/me'): app_me
}

def master_api_handler(req, resp):
    """Master router for API hooks and static file serving."""
    if req.hook:
        return req.hook(req)
    elif req.method == 'GET':
        # Xử lý các yêu cầu lấy file tĩnh (chỉ áp dụng cho GET)
        return resp.build_response(req)
    else:
        # Nếu là phương thức khác (POST, PUT...) mà không có API thì chặn luôn
        return resp.build_notfound()
