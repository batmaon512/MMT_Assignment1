import json
from .response import Response

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
    """API Đăng nhập: Trả về JSON để Form Javascript xử lý"""
    # HttpAdapter đã kiểm tra Basic Auth trước đó. Nếu đúng, req.user sẽ có tên.
    if req.user:
        body = '{"success": true, "message": "Dang nhap thanh cong!"}'
        # Thêm Header Set-Cookie nếu HttpAdapter đã tạo ra Cookie mới
        cookie_header = f"Set-Cookie: {req.new_cookie}\r\n" if hasattr(req, 'new_cookie') and req.new_cookie else ""
        res = f"HTTP/1.1 200 OK\r\n{cookie_header}Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n{body}"
        return res.encode('utf-8')
    else:
        body = '{"success": false, "error": "Sai tai khoan hoac mat khau!"}'
        res = f"HTTP/1.1 401 Unauthorized\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n{body}"
        return res.encode('utf-8')

def app_me(req):
    """API lấy thông tin người dùng đang đăng nhập"""
    if req.user:
        body = '{"username": "' + req.user + '"}'
        res = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n{body}"
        return res.encode('utf-8')
    else:
        body = '{"error": "Chua dang nhap"}'
        res = f"HTTP/1.1 401 Unauthorized\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n{body}"
        return res.encode('utf-8')

def app_logout(req):
    """API Đăng xuất: Xóa Cookie trên trình duyệt"""
    body = '{"success": true}'
    # Đặt thời hạn Max-Age=0 để Trình duyệt tự xóa Cookie
    res = f"HTTP/1.1 200 OK\r\nSet-Cookie: session_id=; Max-Age=0; Path=/\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n{body}"
    return res.encode('utf-8')

def app_status(req):
    """API kiểm tra trạng thái Server (Sử dụng phương thức GET)"""
    # Trả về chuỗi JSON để trình duyệt dễ dàng đọc được
    response_body = '{"status": "online", "server": "AsynapRous", "version": "1.0", "message": "Server dang hoat dong tot!"}'
    
    resp = Response()
    resp._content = response_body.encode('utf-8')
    resp.headers['Content-Type'] = 'application/json'
    
    header_str = resp.build_response_header(req)
    return header_str + resp._content

# Cuốn danh bạ ánh xạ Đường dẫn tới Hàm xử lý API
API_ROUTES = {
    # Các hàm xử lý POST / PUT từ Form
    ('POST', '/echo'): app_echo,
    ('PUT', '/hello'): app_hello,
    ('POST', '/api/login'): app_login,
    ('POST', '/api/logout'): app_logout,
    
    # Các hàm xử lý GET (Khi gõ trực tiếp lên thanh địa chỉ trình duyệt)
    ('GET', '/hello'): app_hello,
    ('GET', '/status'): app_status,
    ('GET', '/api/me'): app_me
}

def master_api_handler(req, resp):
    """
    MASTER ROUTER: Lớp API Trung tâm.
    Mọi gói tin sau khi qua bảo vệ sẽ được đưa vào đây.
    Lớp này sẽ quyết định:
    1. Nếu là lệnh API (có trong danh bạ) -> Chạy hàm API.
    2. Nếu là yêu cầu web bình thường -> Sai ông Thủ kho (resp) đi lấy file tĩnh.
    """
    if req.hook:
        return req.hook(req)
    elif req.method == 'GET':
        # Xử lý các yêu cầu lấy file tĩnh (chỉ áp dụng cho GET)
        return resp.build_response(req)
    else:
        # Nếu là phương thức khác (POST, PUT...) mà không có API thì chặn luôn
        return resp.build_notfound()
