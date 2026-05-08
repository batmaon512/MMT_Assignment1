"""
test_chatapp.py
===============
Kiểm thử toàn diện các chức năng của ChatApp và Tracker.

Cách chạy:
    # Bước 1: Khởi động tracker
    python start_tracker.py --server-port 9001

    # Bước 2: Khởi động 2 chat peer (giả lập 2 người dùng)
    python start_chatapp.py --server-port 8001 --tracker-port 9001
    python start_chatapp.py --server-port 8002 --tracker-port 9001

    # Bước 3: Chạy test
    python test_chatapp.py

    # Hoặc tùy chỉnh
    python test_chatapp.py --tracker-port 9001 --peer-a 8001 --peer-b 8002 \
                           --user-a alice --user-b bob --password 123456
"""

import socket
import json
import time
import argparse
import base64

# =============================================================================
#  Cấu hình mặc định
# =============================================================================

DEFAULT_HOST        = "127.0.0.1"
DEFAULT_TRACKER     = 9001
DEFAULT_PEER_A_PORT = 8001
DEFAULT_PEER_B_PORT = 8002
DEFAULT_USER_A      = "hoang"    # hoang:11111
DEFAULT_USER_B      = "thanh"    # thanh:22222
DEFAULT_PASS_A      = "11111"
DEFAULT_PASS_B      = "22222"

# Tất cả tài khoản trong hệ thống
ALL_ACCOUNTS = {
    "admin": "123456",
    "hoang": "11111",
    "thanh": "22222",
    "tai":   "36363",
    "nhut":  "12345",
}


# =============================================================================
#  HTTP Client tối giản (blocking socket)
# =============================================================================

class SimpleHTTPClient:
    """
    HTTP client đơn giản dùng blocking socket.
    Tự động đính kèm Basic Auth hoặc Cookie.
    """

    def __init__(self, host, port, username=None, password=None):
        self.host     = host
        self.port     = port
        self.username = username
        self.password = password
        self.session_cookie = None   # Lưu session_id sau khi login

    def _build_request(self, method, path, body=None):
        """Tạo raw HTTP request bytes."""
        body_bytes = b""
        if body is not None:
            body_bytes = json.dumps(body).encode("utf-8")

        headers = (
            f"{method} {path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
        )

        # Gắn Cookie nếu đã có session
        if self.session_cookie:
            headers += f"Cookie: session_id={self.session_cookie}\r\n"
        # Gắn Basic Auth nếu chưa có Cookie
        elif self.username and self.password:
            creds   = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            headers += f"Authorization: Basic {creds}\r\n"

        headers += "Connection: close\r\n\r\n"
        return headers.encode("utf-8") + body_bytes

    def request(self, method, path, body=None, timeout=5):
        """
        Gửi HTTP request và trả về (status_code, response_dict/str).
        """
        try:
            raw = self._build_request(method, path, body)
            s   = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((self.host, self.port))
            s.sendall(raw)

            # Nhận response
            resp_bytes = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                resp_bytes += chunk
            s.close()

            # Parse status line
            lines      = resp_bytes.split(b"\r\n")
            status_line = lines[0].decode("utf-8", errors="replace")
            status_code = int(status_line.split()[1]) if len(status_line.split()) >= 2 else 0

            # Parse Set-Cookie từ response headers
            for line in lines[1:]:
                decoded = line.decode("utf-8", errors="replace")
                if decoded.lower().startswith("set-cookie:") and "session_id=" in decoded:
                    parts = decoded.split("session_id=", 1)[1].split(";")[0].strip()
                    if parts and parts != "":
                        self.session_cookie = parts

            # Parse JSON body
            if b"\r\n\r\n" in resp_bytes:
                body_raw = resp_bytes.split(b"\r\n\r\n", 1)[1]
                try:
                    return status_code, json.loads(body_raw.decode("utf-8"))
                except Exception:
                    return status_code, body_raw.decode("utf-8", errors="replace")

            return status_code, {}

        except Exception as e:
            return 0, {"error": str(e)}

    def post(self, path, body=None):
        return self.request("POST", path, body)

    def get(self, path):
        return self.request("GET", path, None)


# =============================================================================
#  Test runner
# =============================================================================

passed = 0
failed = 0
total  = 0

def test(name, condition, detail=""):
    global passed, failed, total
    total += 1
    if condition:
        passed += 1
        print(f"  ✅ PASS  {name}")
    else:
        failed += 1
        print(f"  ❌ FAIL  {name}")
        if detail:
            print(f"          → {detail}")


def section(title):
    print()
    print(f"{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# =============================================================================
#  Các nhóm test
# =============================================================================

def test_tracker(host, tracker_port, user_a, pass_a, user_b, pass_b):
    """Test Tracker server APIs trực tiếp."""
    section("TRACKER TESTS")

    # Dùng đúng mật khẩu của user_a để xác thực với tracker
    tracker = SimpleHTTPClient(host, tracker_port, user_a, pass_a)

    # Test 1: submit-info (đăng ký peer A)
    code, resp = tracker.post("/submit-info", {
        "name": user_a, "ip": "127.0.0.1", "port": 8001
    })
    test("submit-info peer A", code == 200 and resp.get("code") == 1,
         f"code={code} resp={resp}")

    # Test 2: submit-info (đăng ký peer B)
    code, resp = tracker.post("/submit-info", {
        "name": user_b, "ip": "127.0.0.1", "port": 8002
    })
    test("submit-info peer B", code == 200 and resp.get("code") == 1,
         f"code={code} resp={resp}")

    # Test 3: online (heartbeat)
    code, resp = tracker.post("/online", {"name": user_a})
    test("online heartbeat", code == 200 and resp.get("code") == 1,
         f"code={code} resp={resp}")

    # Test 4: get-list (lấy danh sách) — cần auth, tracker tự auth qua cookie
    # Sau submit-info tracker đã biết user, dùng cookie đã có
    code, resp = tracker.post("/get-list", {})
    peers = resp.get("peers", [])
    names = [p.get("name") for p in peers]
    test("get-list returns peers", code == 200 and len(peers) >= 1,
         f"code={code} resp={resp}")
    test(f"get-list contains {user_a}", user_a in names,
         f"names={names}")

    return peers


def test_chatapp_auth(host, port, username, password, label):
    """Test xác thực của ChatApp."""
    section(f"AUTH TESTS — {label} (port {port})")

    client = SimpleHTTPClient(host, port)

    # Test 5: Login với Basic Auth
    client.username = username
    client.password = password
    code, resp = client.post("/api/login", {})
    test(f"login ({username})", code == 200 and resp.get("success") == True,
         f"code={code} resp={resp}")
    has_cookie = client.session_cookie is not None
    test("session cookie set", has_cookie,
         f"cookie={client.session_cookie}")

    # Test 6: Login sai password
    bad = SimpleHTTPClient(host, port, username, "wrongpassword")
    code, resp = bad.post("/api/login", {})
    test("reject wrong password", code == 401,
         f"code={code}")

    # Test 7: Logout
    code, resp = client.post("/api/logout", {})
    test("logout success", code == 200 and resp.get("success") == True,
         f"code={code} resp={resp}")

    return client   # Trả về client đã đăng nhập (cookie có thể đã expire sau logout)


def test_chatapp_peer(host, port_a, port_b, tracker_port,
                      user_a, user_b, pass_a, pass_b):
    """Test toàn bộ luồng Chat P2P giữa 2 peer."""
    section("P2P CHAT TESTS")

    # Tạo 2 client với đúng mật khẩu của từng người
    client_a = SimpleHTTPClient(host, port_a, user_a, pass_a)
    client_b = SimpleHTTPClient(host, port_b, user_b, pass_b)

    # Đăng nhập
    client_a.post("/api/login", {})
    client_b.post("/api/login", {})
    test("peer A logged in", client_a.session_cookie is not None)
    test("peer B logged in", client_b.session_cookie is not None)

    # Test: submit-info (đăng ký với tracker qua chatapp)
    code, resp = client_a.post("/submit-info", {
        "name": user_a, "ip": "127.0.0.1", "port": port_a
    })
    test("peer A submit-info", code == 200 and resp.get("code") == 1,
         f"code={code} resp={resp}")

    code, resp = client_b.post("/submit-info", {
        "name": user_b, "ip": "127.0.0.1", "port": port_b
    })
    test("peer B submit-info", code == 200 and resp.get("code") == 1,
         f"code={code} resp={resp}")

    # Test: online heartbeat
    code, resp = client_a.post("/online", {"name": user_a})
    test("peer A online heartbeat", code == 200 and resp.get("code") == 1,
         f"code={code} resp={resp}")

    # Test: get-list
    code, resp = client_a.post("/get-list", {})
    peers = resp.get("peers", [])
    names = [p.get("name") for p in peers]
    test("get-list from peer A", code == 200,
         f"code={code} resp={resp}")
    test(f"get-list has {user_b}", user_b in names,
         f"names={names}")

    # Test: connect-peer
    code, resp = client_a.post("/connect-peer", {"target": user_b})
    test(f"connect-peer to {user_b}", code == 200 and resp.get("code") == 1,
         f"code={code} resp={resp}")

    # Test: send-peer (P2P trực tiếp)
    msg_text = f"Hello {user_b}! This is a P2P message from {user_a}."
    code, resp = client_a.post("/send-peer", {
        "to":      user_b,
        "message": msg_text,
        "from":    user_a,
    })
    test(f"send-peer {user_a} → {user_b}", code == 200 and resp.get("code") == 1,
         f"code={code} resp={resp}")

    # Chờ message được xử lý
    time.sleep(0.3)

    # Test: poll-messages (peer B nhận tin)
    code, resp = client_b.post("/poll-messages", {})
    messages = resp.get("messages", [])
    test("peer B poll-messages", code == 200 and resp.get("code") == 1,
         f"code={code} resp={resp}")

    received = any(m.get("message") == msg_text for m in messages)
    test(f"peer B received message from {user_a}", received,
         f"messages={messages}")

    # Test: broadcast-peer
    broadcast_text = f"[BROADCAST] Hello everyone from {user_a}!"
    code, resp = client_a.post("/broadcast-peer", {
        "message": broadcast_text,
        "from":    user_a,
    })
    test("broadcast-peer", code == 200 and resp.get("code") == 1,
         f"code={code} resp={resp}")

    # Chờ broadcast
    time.sleep(0.3)

    # Test: peer B nhận broadcast
    code, resp = client_b.post("/poll-messages", {})
    messages = resp.get("messages", [])
    received_bc = any(m.get("message") == broadcast_text for m in messages)
    test(f"peer B received broadcast", received_bc,
         f"messages={messages}")

    # Test: peers (local cache)
    code, resp = client_a.post("/peers", {})
    test("get local peer cache", code == 200 and resp.get("code") == 1,
         f"code={code}")

    # Test: internal/receive-msg trực tiếp
    code, resp = client_b.post("/internal/receive-msg", {
        "from": "system",
        "to":   user_b,
        "message": "direct inject test",
        "time": time.time() * 1000,
    })
    test("internal/receive-msg", code == 200 and resp.get("code") == 1,
         f"code={code} resp={resp}")

    # Test: logout
    code, resp = client_a.post("/api/logout", {})
    test("peer A logout", code == 200 and resp.get("success") == True)
    code, resp = client_b.post("/api/logout", {})
    test("peer B logout", code == 200 and resp.get("success") == True)


# =============================================================================
#  Kiểm tra server
# =============================================================================

def check_server(host, port, label):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect((host, port))
        s.close()
        print(f"  ✅ {label} ({host}:{port}) — ONLINE")
        return True
    except Exception as e:
        print(f"  ❌ {label} ({host}:{port}) — {e}")
        return False


# =============================================================================
#  Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Test ChatApp & Tracker functionality"
    )
    parser.add_argument("--host",         default=DEFAULT_HOST)
    parser.add_argument("--tracker-port", type=int, default=DEFAULT_TRACKER)
    parser.add_argument("--peer-a",       type=int, default=DEFAULT_PEER_A_PORT)
    parser.add_argument("--peer-b",       type=int, default=DEFAULT_PEER_B_PORT)
    parser.add_argument("--user-a",       default=DEFAULT_USER_A)
    parser.add_argument("--user-b",       default=DEFAULT_USER_B)
    parser.add_argument("--pass-a",       default=DEFAULT_PASS_A,
                        help=f"Password of user-a (default: {DEFAULT_PASS_A})")
    parser.add_argument("--pass-b",       default=DEFAULT_PASS_B,
                        help=f"Password of user-b (default: {DEFAULT_PASS_B})")
    # Backward compat: --password sets cả 2
    parser.add_argument("--password",     default=None,
                        help="Set same password for both users (overrides --pass-a/--pass-b)")
    args = parser.parse_args()

    # Override nếu dùng --password
    if args.password:
        args.pass_a = args.password
        args.pass_b = args.password

    # Gợi ý từ danh sách tài khoản
    if args.user_a not in ALL_ACCOUNTS and args.pass_a == DEFAULT_PASS_A:
        suggested = list(ALL_ACCOUNTS.keys())
        print(f"  ⚠️  user-a='{args.user_a}' không có trong danh sách. Gợi ý: {suggested}")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  TEST: ChatApp & Tracker")
    print("=" * 60)
    print(f"  Tracker  : {args.host}:{args.tracker_port}")
    print(f"  Peer A   : {args.host}:{args.peer_a} ({args.user_a} / {args.pass_a})")
    print(f"  Peer B   : {args.host}:{args.peer_b} ({args.user_b} / {args.pass_b})")
    print(f"  Accounts : { {k:v for k,v in ALL_ACCOUNTS.items()} }")
    print()

    # Kiểm tra các server
    print("Checking servers...")
    tr_ok = check_server(args.host, args.tracker_port, "Tracker")
    pa_ok = check_server(args.host, args.peer_a,       f"Peer A ({args.user_a})")
    pb_ok = check_server(args.host, args.peer_b,       f"Peer B ({args.user_b})")
    print()

    if not tr_ok:
        print("❌ Tracker chưa chạy. Khởi động:")
        print(f"   python start_tracker.py --server-port {args.tracker_port}")

    if not pa_ok or not pb_ok:
        print("❌ Peer A hoặc B chưa chạy. Khởi động:")
        print(f"   python start_chatapp.py --server-port {args.peer_a} "
              f"--tracker-port {args.tracker_port}")
        print(f"   python start_chatapp.py --server-port {args.peer_b} "
              f"--tracker-port {args.tracker_port}")

    # Chạy tests
    if tr_ok:
        test_tracker(
            args.host, args.tracker_port,
            args.user_a, args.pass_a,
            args.user_b, args.pass_b
        )

    if pa_ok:
        test_chatapp_auth(
            args.host, args.peer_a,
            args.user_a, args.pass_a, f"Peer A"
        )

    if pb_ok:
        test_chatapp_auth(
            args.host, args.peer_b,
            args.user_b, args.pass_b, f"Peer B"
        )

    if pa_ok and pb_ok and tr_ok:
        test_chatapp_peer(
            args.host,
            args.peer_a, args.peer_b,
            args.tracker_port,
            args.user_a, args.user_b,
            args.pass_a, args.pass_b
        )

    # Kết quả
    print()
    print("=" * 60)
    print(f"  KẾT QUẢ: {passed}/{total} tests passed"
          + (f"  ({failed} FAILED)" if failed else "  🎉 All passed!"))
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
