#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# AsynapRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#

"""
daemon.httpadapter
~~~~~~~~~~~~~~~~~

This module provides a http adapter object to manage and persist 
http settings (headers, bodies). The adapter supports both
raw URL paths and RESTful route definitions, and integrates with
Request and Response objects to handle client-server communication.
"""

from .request import Request
from .response import Response
from .dictionary import CaseInsensitiveDict

import asyncio
import inspect
import os
import time
import uuid # Thư viện tạo chuỗi ngẫu nhiên cho Session ID

# --- DATABASE LƯU COOKIE (TRÊN RAM) ---
MAX_SESSIONS = 100
ACTIVE_SESSIONS = {}
SESSION_TTL = 86400

# --- DATABASE TÀI KHOẢN HỢP LỆ ---
ACCOUNTS_FILE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "db", "account.txt")
)
SESSIONS_FILE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "db", "sessions_id.txt")
)

def load_valid_users():
    users = {}
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    username, password = line.split(":", 1)
                    users[username.strip()] = password.strip()
    except FileNotFoundError:
        pass
    return users

VALID_USERS = load_valid_users() or {
    "admin": "123456",
    "user1": "password"
}

def add_session(session_id, username):
    """Hàm thêm Session mới, giới hạn tối đa 100 người"""
    if len(ACTIVE_SESSIONS) >= MAX_SESSIONS:
        # Xóa người đăng nhập cũ nhất (đầu danh sách)
        oldest_key = next(iter(ACTIVE_SESSIONS))
        del ACTIVE_SESSIONS[oldest_key]
    ACTIVE_SESSIONS[session_id] = username

def load_sessions():
    sessions = {}
    if not os.path.exists(SESSIONS_FILE):
        return sessions
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("|", 2)
                if len(parts) != 3:
                    continue
                sid, user, exp = parts
                try:
                    exp_val = float(exp)
                except ValueError:
                    continue
                if exp_val > time.time():
                    sessions[sid] = (user, exp_val)
    except Exception:
        return sessions
    return sessions

def save_sessions(sessions):
    os.makedirs(os.path.dirname(SESSIONS_FILE), exist_ok=True)
    lines = []
    for sid, data in sessions.items():
        user, exp = data
        lines.append(f"{sid}|{user}|{int(exp)}")
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def create_session(username):
    sessions = load_sessions()
    sessions = {sid: data for sid, data in sessions.items() if data[0] != username}
    session_id = uuid.uuid4().hex
    expire_time = time.time() + SESSION_TTL
    sessions[session_id] = (username, expire_time)
    save_sessions(sessions)
    return session_id

def validate_session(session_id):
    sessions = load_sessions()
    if session_id not in sessions:
        return None
    user, exp = sessions[session_id]
    if exp <= time.time():
        sessions.pop(session_id, None)
        save_sessions(sessions)
        return None
    return user

def remove_session(session_id):
    sessions = load_sessions()
    if session_id in sessions:
        sessions.pop(session_id, None)
        save_sessions(sessions)

class HttpAdapter:
    """
    A mutable :class:`HTTP adapter <HTTP adapter>` for managing client connections
    and routing requests.

    The `HttpAdapter` class encapsulates the logic for receiving HTTP requests,
    dispatching them to appropriate route handlers, and constructing responses.
    It supports RESTful routing via hooks and integrates with :class:`Request <Request>` 
    and :class:`Response <Response>` objects for full request lifecycle management.

    Attributes:
        ip (str): IP address of the client.
        port (int): Port number of the client.
        conn (socket): Active socket connection.
        connaddr (tuple): Address of the connected client.
        routes (dict): Mapping of route paths to handler functions.
        request (Request): Request object for parsing incoming data.
        response (Response): Response object for building and sending replies.
    """

    __attrs__ = [
        "ip",
        "port",
        "conn",
        "connaddr",
        "routes",
        "request",
        "response",
    ]

    def __init__(self, ip, port, conn, connaddr, routes):
        """
        Initialize a new HttpAdapter instance.

        :param ip (str): IP address of the client.
        :param port (int): Port number of the client.
        :param conn (socket): Active socket connection.
        :param connaddr (tuple): Address of the connected client.
        :param routes (dict): Mapping of route paths to handler functions.
        """

        #: IP address.
        self.ip = ip
        #: Port.
        self.port = port
        #: Connection
        self.conn = conn
        #: Conndection address
        self.connaddr = connaddr
        #: Routes
        self.routes = routes
        #: Request
        self.request = Request()
        #: Response
        self.response = Response()

    def build_unauthorized_response(self, req):
        resp = Response()
        resp.status_code = 401
        resp.reason = "Unauthorized"
        resp._content = b'{"error": "Unauthorized"}'
        resp.headers['Content-Type'] = 'application/json'
        resp.headers['WWW-Authenticate'] = 'Basic realm="AsynapRous", charset="UTF-8"'
        header_str = resp.build_response_header(req)
        return header_str + resp._content

    def handle_client(self, conn, addr, routes):
        """
        Handle an incoming client connection.

        This method reads the request from the socket, prepares the request object,
        invokes the appropriate route handler if available, builds the response,
        and sends it back to the client.

        :param conn (socket): The client socket connection.
        :param addr (tuple): The client's address.
        :param routes (dict): The route mapping for dispatching requests.
        """

        # Connection handler.
        self.conn = conn        
        # Connection address.
        self.connaddr = addr
        # Request handler
        req = self.request
        # Response handler
        resp = self.response

        # Handle the request
        msg = ""
        while True:
            chunk = conn.recv(1024).decode('utf-8', errors='ignore')
            if not chunk:
                break
            msg += chunk
            if '\r\n\r\n' in msg:
                break

        print("\n" + "="*40)
        print("[HttpAdapter] Raw message from client:")
        print(msg)
        print("="*40 + "\n")
        
        req.prepare(msg, routes)
        print("[HttpAdapter] Invoke handle_client connection {}".format(addr))

        # --- BẮT ĐẦU KIỂM TRA BẢO MẬT (AUTHENTICATION & COOKIE) ---
        is_authenticated = False
        current_user = None
        new_cookie_to_set = None

        # 1. Kiểm tra Cookie xem có thẻ hợp lệ không
        if req.cookies and 'session_id' in req.cookies:
            session_id = req.cookies['session_id']
            if session_id in ACTIVE_SESSIONS:
                is_authenticated = True
                current_user = ACTIVE_SESSIONS[session_id]
            else:
                user = validate_session(session_id)
                if user:
                    is_authenticated = True
                    current_user = user
                    add_session(session_id, user)

        # 2. Nếu chưa có thẻ, kiểm tra xem có gửi Mật khẩu (Basic Auth) không
        if not is_authenticated and req.auth:
            import base64
            auth_parts = req.auth.split(' ')
            if len(auth_parts) == 2 and auth_parts[0] == 'Basic':
                try:
                    # Giải mã chuỗi YWRtaW46MTIzNDU2 thành admin:123456
                    decoded_bytes = base64.b64decode(auth_parts[1])
                    decoded_str = decoded_bytes.decode('utf-8')
                    username, password = decoded_str.split(':', 1)
                    
                    if VALID_USERS.get(username) == password:
                        is_authenticated = True
                        current_user = username
                        # Đăng nhập đúng, cấp thẻ Cookie mới lưu vào RAM
                        new_session = create_session(username)
                        add_session(new_session, username)
                        new_cookie_to_set = f"session_id={new_session}; Path=/; HttpOnly"
                        req.new_cookie = new_cookie_to_set
                except Exception as e:
                    print("Lỗi giải mã Auth:", e)

        # 3. Phân quyền và Quyết định (Authorization & Routing)
        # Các đường dẫn được phép truy cập tự do không cần đăng nhập
        public_paths = ['/', '/login.html', '/register.html']
        is_public = (
            req.path in public_paths
            or req.path.startswith('/css')
            or req.path.startswith('/js')
            or req.path.startswith('/images')
            or req.path == '/api/login'
            or req.path == '/api/logout'  # logout must always be accessible
            or req.path == '/internal/receive-msg'  # peer-to-peer: no auth needed
        )
        api_paths = [
            '/online', '/signal', '/signal_poll',
            '/submit-info', '/get-list', '/connect-peer', '/broadcast-peer', '/send-peer',
            '/poll-messages'
        ]
        is_api = (req.path.startswith('/api/') and req.path != '/api/login') or req.path in api_paths

        if not is_authenticated and not is_public:
            if is_api:
                response = self.build_unauthorized_response(req)
            else:
                # Khách chưa đăng nhập mà dám vào trang riêng tư (VD: form.html) -> Đuổi về trang login
                response = b"HTTP/1.1 302 Found\r\n"
                response += b"Location: /login.html\r\n"
                response += b"Content-Length: 0\r\n\r\n"
        else:
            # Khách hợp lệ (hoặc đang ở trang Public), cho phép xử lý tiếp
            # Cài cắm cờ Set-Cookie vào thư viện headers của Thủ kho
            if new_cookie_to_set:
                resp.headers['Set-Cookie'] = new_cookie_to_set
            
            # Gắn tên người dùng vào Request để Lớp API biết ai đang truy cập
            req.user = current_user

            # PHÂN LỒNG XỬ LÝ (GIAO HẾT CHO LỚP API TRUNG TÂM QUYẾT ĐỊNH)
            from daemon.api import master_api_handler
            response = master_api_handler(req, resp)

        #print("[HttpAdapter] Response content {}".format(response))
        if isinstance(response, str):
            response = response.encode()
        conn.sendall(response)
        conn.close()

    async def handle_client_coroutine(self, reader, writer):
        """
        Xử lý kết nối của Khách hàng bằng cơ chế Bất đồng bộ (Async/Await).
        Siêu bồi bàn (CPU) sẽ không đứng chờ khi tải dữ liệu, mà nhường quyền xử lý cho các kết nối khác.
        """
        addr = writer.get_extra_info("peername")
        req = self.request
        resp = self.response
        routes = self.routes # Lấy cuốn danh bạ API đã được truyền vào từ Backend

        try:
            # 1. ĐỌC DỮ LIỆU BẤT ĐỒNG BỘ
            # Nếu Buffer trống, hàm sẽ 'ngủ đông' (await) nhường CPU cho Khách khác. 
            # Khi gói tin bay tới Buffer, hàm sẽ tự thức dậy làm tiếp!
            msg_bytes = await reader.read(4096)
            if not msg_bytes:
                return
            
            # 2. PHÂN TÍCH GÓI TIN (Giao cho lớp Request phân tách Header/Body)
            req.prepare(msg_bytes.decode('utf-8', errors='replace'), routes)

            # --- BẮT ĐẦU KIỂM TRA BẢO MẬT (AUTHENTICATION & COOKIE) ---
            is_authenticated = False
            current_user = None
            new_cookie_to_set = None

            # a) Kiểm tra vé vào cổng (Cookie session_id)
            if req.cookies and 'session_id' in req.cookies:
                session_id = req.cookies['session_id']
                if session_id in ACTIVE_SESSIONS:
                    is_authenticated = True
                    current_user = ACTIVE_SESSIONS[session_id] # Lấy tên User từ RAM
                else:
                    user = validate_session(session_id)
                    if user:
                        is_authenticated = True
                        current_user = user
                        add_session(session_id, user)

            # b) Nếu chưa có vé, kiểm tra Mật khẩu (Basic Auth)
            if not is_authenticated and req.auth:
                import base64
                auth_parts = req.auth.split(' ')
                if len(auth_parts) == 2 and auth_parts[0] == 'Basic':
                    try:
                        # Giải mã Base64
                        decoded_bytes = base64.b64decode(auth_parts[1])
                        decoded_str = decoded_bytes.decode('utf-8')
                        username, password = decoded_str.split(':', 1)
                        
                        # So khớp với CSDL
                        if VALID_USERS.get(username) == password:
                            is_authenticated = True
                            current_user = username
                            
                            # Đăng nhập thành công -> Cấp phát Vé (Session UUID)
                            new_session = create_session(username)
                            add_session(new_session, username)
                            
                            # Cài đặt tầm hoạt động của Cookie cho toàn bộ Website (Path=/)
                            new_cookie_to_set = f"session_id={new_session}; Path=/; HttpOnly"
                            req.new_cookie = new_cookie_to_set
                    except Exception as e:
                        pass # Giải mã lỗi hoặc sai cú pháp

            # --- PHÂN QUYỀN VÀ ĐIỀU HƯỚNG ---
            # Danh sách các khu vực công cộng ai cũng được vào
            public_paths = ['/', '/login.html', '/register.html']
            is_public = (
                req.path in public_paths
                or req.path.startswith('/css')
                or req.path.startswith('/js')
                or req.path.startswith('/images')
                or req.path == '/api/login'
                or req.path == '/api/logout'  # logout must always be accessible
                or req.path == '/internal/receive-msg'  # peer-to-peer: no auth needed
            )
            api_paths = [
                '/online', '/signal', '/signal_poll',
                '/submit-info', '/get-list', '/connect-peer', '/broadcast-peer', '/send-peer',
                '/poll-messages'
            ]
            is_api = (req.path.startswith('/api/') and req.path != '/api/login') or req.path in api_paths

            if not is_authenticated and not is_public:
                if is_api:
                    response = self.build_unauthorized_response(req)
                else:
                    # Kẻ lạ mặt xâm nhập khu vực kín -> Đuổi về trang Đăng nhập (Mã 302)
                    response = b"HTTP/1.1 302 Found\r\nLocation: /login.html\r\nContent-Length: 0\r\n\r\n"
            else:
                # Khách hợp lệ -> Kẹp thẻ Cookie mới (nếu có) vào tay ông Thủ kho
                if new_cookie_to_set:
                    resp.headers['Set-Cookie'] = new_cookie_to_set
                
                # Báo cho Master Router biết Khách này tên gì
                req.user = current_user
                
                # PHÂN LỒNG XỬ LÝ (GIAO HẾT CHO LỚP API TRUNG TÂM QUYẾT ĐỊNH)
                from daemon.api import master_api_handler
                response = master_api_handler(req, resp)
                # Nếu handler là async coroutine (dùng AsynapRous), cần await để lấy kết quả
                if asyncio.iscoroutine(response):
                    response = await response

            # Đảm bảo kết quả cuối cùng phải là dạng Bytes (Nhị phân)
            if isinstance(response, str):
                response = response.encode()

            # 4. GỬI DỮ LIỆU BẤT ĐỒNG BỘ
            writer.write(response)
            await writer.drain()

        except Exception as e:
            print("[Async Error] Lỗi trong quá trình phục vụ:", e)
        finally:
            # Luôn luôn phải dọn dẹp, đóng kết nối khi khách ăn xong!
            writer.close()
            await writer.wait_closed()

    @property
    def extract_cookies(self, req, resp):
        """
        Build cookies from the :class:`Request <Request>` headers.

        :param req:(Request) The :class:`Request <Request>` object.
        :param resp: (Response) The res:class:`Response <Response>` object.
        :rtype: cookies - A dictionary of cookie key-value pairs.
        """
        cookies = {}
        for header in headers:
            if header.startswith("Cookie:"):
                cookie_str = header.split(":", 1)[1].strip()
                for pair in cookie_str.split(";"):
                    key, value = pair.strip().split("=")
                    cookies[key] = value
        return cookies

    def build_response(self, req, resp):
        """Builds a :class:`Response <Response>` object 

        :param req: The :class:`Request <Request>` used to generate the response.
        :param resp: The  response object.
        :rtype: Response
        """
        response = Response()

        # Set encoding.
        response.encoding = get_encoding_from_headers(response.headers)
        response.raw = resp
        response.reason = response.raw.reason

        if isinstance(req.url, bytes):
            response.url = req.url.decode("utf-8")
        else:
            response.url = req.url

        # Add new cookies from the server.
        response.cookies = extract_cookies(req)

        # Give the Response some context.
        response.request = req
        response.connection = self

        return response

    def build_json_response(self, req, resp):
        """Builds a :class:`Response <Response>` object from JSON data

        :param req: The :class:`Request <Request>` used to generate the response.
        :param resp: The  response object.
        :rtype: Response
        """
        response = Response(req)

        # Set encoding.
        response.raw = resp

        if isinstance(req.url, bytes):
            response.url = req.url.decode("utf-8")
        else:
            response.url = req.url

        # Give the Response some context.
        response.request = req
        response.connection = self

        return response


    # def get_connection(self, url, proxies=None):
        # """Returns a url connection for the given URL. 

        # :param url: The URL to connect to.
        # :param proxies: (optional) A Requests-style dictionary of proxies used on this request.
        # :rtype: int
        # """

        # proxy = select_proxy(url, proxies)

        # if proxy:
            # proxy = prepend_scheme_if_needed(proxy, "http")
            # proxy_url = parse_url(proxy)
            # if not proxy_url.host:
                # raise InvalidProxyURL(
                    # "Please check proxy URL. It is malformed "
                    # "and could be missing the host."
                # )
            # proxy_manager = self.proxy_manager_for(proxy)
            # conn = proxy_manager.connection_from_url(url)
        # else:
            # # Only scheme should be lower case
            # parsed = urlparse(url)
            # url = parsed.geturl()
            # conn = self.poolmanager.connection_from_url(url)

        # return conn


    def add_headers(self, request):
        """
        Add headers to the request.

        This method is intended to be overridden by subclasses to inject
        custom headers. It does nothing by default.

        
        :param request: :class:`Request <Request>` to add headers to.
        """
        pass

    def build_proxy_headers(self, proxy):
        """Returns a dictionary of the headers to add to any request sent
        through a proxy. 

        :class:`HttpAdapter <HttpAdapter>`.

        :param proxy: The url of the proxy being used for this request.
        :rtype: dict
        """
        headers = {}
        #
        # TODO: build your authentication here
        #       username, password =...
        # we provide dummy auth here
        #
        username, password = ("user1", "password")

        if username:
            headers["Proxy-Authorization"] = (username, password)

        return headers