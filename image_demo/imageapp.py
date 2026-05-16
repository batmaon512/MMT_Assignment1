import json
import uuid
import minizmq as zmq
import threading
import sys
import os

from daemon import AsynapRous

app = AsynapRous()

# --- ZMQ SETUP ---
zmq_ctx = zmq.Context()
# Sử dụng TCP thay vì IPC trên Windows để đảm bảo hoạt động 100% không bị lỗi path
zmq_pusher = zmq_ctx.socket(zmq.PUSH)
zmq_pusher.bind("tcp://127.0.0.1:5557")

SHARED_RESULTS = {}
results_lock = threading.Lock()

def zmq_collector():
    """Chạy ngầm để nhận kết quả từ Worker"""
    receiver = zmq_ctx.socket(zmq.PULL)
    receiver.bind("tcp://127.0.0.1:5558")
    print("[Server] Collector listening on 5558...")
    while True:
        try:
            msg = receiver.recv_json()
            req_id = msg.get("request_id")
            with results_lock:
                if req_id in SHARED_RESULTS:
                    SHARED_RESULTS[req_id]["data"] = msg
                    SHARED_RESULTS[req_id]["event"].set()
        except Exception as e:
            print("ZMQ Collector Error:", e)

# Khởi chạy Collector Thread
threading.Thread(target=zmq_collector, daemon=True).start()

def json_response(payload, status=200):
    body = json.dumps(payload)
    status_text = "OK" if status == 200 else "Bad Request"
    res = (
        f"HTTP/1.1 {status} {status_text}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n\r\n{body}"
    )
    return res.encode('utf-8')

@app.route('/images/app', methods=['GET', 'POST'])
def serve_html(req):
    """Phục vụ file HTML giao diện"""
    html_content = """<!DOCTYPE html>
<html>
<head>
    <title>Image Processor (ZeroMQ)</title>
    <style>
        body { font-family: Arial; text-align: center; padding: 50px; background: #f4f4f9; }
        .box { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.1); display: inline-block; }
        img { max-width: 400px; margin-top: 20px; border-radius: 5px; }
        button { padding: 10px 20px; cursor: pointer; background: #007bff; color: white; border: none; border-radius: 5px; }
    </style>
</head>
<body>
    <div class="box">
        <h2>AsynapRous Image Processor</h2>
        <input type="file" id="fileInput" accept="image/*"><br><br>
        <button onclick="uploadImage()">Đóng dấu ảnh</button>
        <p id="status"></p>
        <div style="display: flex; gap: 20px; justify-content: center;">
            <div>
                <h4>Gốc</h4>
                <img id="preview" style="display:none;">
            </div>
            <div>
                <h4>Kết quả (Từ Worker)</h4>
                <img id="result" style="display:none;">
            </div>
        </div>
    </div>

    <script>
        let base64Image = "";

        document.getElementById('fileInput').addEventListener('change', function(e) {
            const file = e.target.files[0];
            const reader = new FileReader();
            reader.onload = function(event) {
                base64Image = event.target.result;
                document.getElementById('preview').src = base64Image;
                document.getElementById('preview').style.display = 'block';
            };
            reader.readAsDataURL(file);
        });

        async function uploadImage() {
            if (!base64Image) { alert("Vui lòng chọn ảnh!"); return; }
            document.getElementById('status').innerText = "Đang gửi cho Worker xử lý...";
            
            try {
                const response = await fetch('/images/process', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ image: base64Image })
                });
                
                const data = await response.json();
                if (data.image) {
                    document.getElementById('result').src = data.image;
                    document.getElementById('result').style.display = 'block';
                    document.getElementById('status').innerText = "Xong!";
                } else {
                    document.getElementById('status').innerText = "Lỗi: " + data.error;
                }
            } catch (err) {
                document.getElementById('status').innerText = "Lỗi kết nối!";
            }
        }
    </script>
</body>
</html>"""
    res = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(html_content.encode('utf-8'))}\r\n\r\n{html_content}"
    )
    return res.encode('utf-8')

@app.route('/images/process', methods=['POST'])
def process_image(req):
    """Nhận base64 ảnh, đẩy qua ZMQ, chờ kết quả"""
    try:
        data = json.loads(req.body)
        base64_img = data.get("image")
        if not base64_img:
            return json_response({"error": "No image data"}, 400)

        req_id = str(uuid.uuid4())[:8]
        
        # Đăng ký chờ kết quả
        event = threading.Event()
        with results_lock:
            SHARED_RESULTS[req_id] = {"event": event, "data": None}
            
        # PUSH task (chỉ lấy phần data của base64, bỏ prefix)
        img_data = base64_img.split(",")[1] if "," in base64_img else base64_img
        
        zmq_pusher.send_json({
            "request_id": req_id,
            "image": img_data,
            "text": "CO3093 - ASYNAPROUS"
        })
        print(f"[API] Đã đẩy task {req_id} cho ZMQ Worker")

        # Đợi kết quả
        finished = event.wait(timeout=10.0)
        
        if finished:
            with results_lock:
                res_data = SHARED_RESULTS.pop(req_id, {}).get("data")
            if res_data and res_data.get("status") == "success":
                # Thêm prefix để hiển thị trên web
                final_b64 = "data:image/jpeg;base64," + res_data.get("result")
                return json_response({"image": final_b64})
            else:
                return json_response({"error": res_data.get("error")}, 500)
        else:
            with results_lock:
                SHARED_RESULTS.pop(req_id, None)
            return json_response({"error": "Worker timeout"}, 504)
            
    except Exception as e:
        return json_response({"error": str(e)}, 500)

def create_imageapp(ip, port):
    # Đăng ký công khai route mới để bỏ qua Authentication
    from daemon.httpadapter import HttpAdapter
    
    app.prepare_address(ip, port)
    app.run()
