import json
import threading
import minizmq as zmq
import threading
import sys
import os

from daemon import AsynapRous

# --- CONFIGURATION ---
ZMQ_HOST = "127.0.0.1"
ZMQ_TASK_PORT = 5557    # Cổng Server phát task
ZMQ_RESULT_PORT = 5558  # Cổng Server nhận kết quả về

app = AsynapRous()

# --- ZMQ SETUP ---
zmq_ctx = zmq.Context()
# Sử dụng TCP thay vì IPC trên Windows để đảm bảo hoạt động 100% không bị lỗi path
zmq_pusher = zmq_ctx.socket(zmq.PUSH)
zmq_pusher.bind(f"tcp://{ZMQ_HOST}:{ZMQ_TASK_PORT}")

SHARED_RESULTS = {}
results_lock = threading.Lock()

task_counter = 0

def zmq_collector():
    """Chạy ngầm để nhận kết quả từ Worker"""
    receiver = zmq_ctx.socket(zmq.PULL)
    receiver.bind(f"tcp://{ZMQ_HOST}:{ZMQ_RESULT_PORT}")
    print(f"[Server] Collector listening on {ZMQ_RESULT_PORT}...")
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
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
    except Exception as e:
        html_content = f"<h1>Lỗi: Không tìm thấy file index.html</h1><p>{str(e)}</p>"
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

        global task_counter
        with results_lock:
            task_counter += 1
            req_id = str(task_counter)
            
            # Đăng ký chờ kết quả
            event = threading.Event()
            SHARED_RESULTS[req_id] = {"event": event, "data": None}
            

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
    from daemon.httpadapter import HttpAdapter
    
    app.prepare_address(ip, port)
    app.run()
