import json
import time

from daemon import AsynapRous

app = AsynapRous()

ONLINE_TTL = 30.0
PEER_REGISTRY = {}
ONLINE = {}

def cleanup_online(now):
    expired = [name for name, ts in ONLINE.items() if now - ts > ONLINE_TTL]
    for name in expired:
        ONLINE.pop(name, None)

def json_response(payload, status=200):
    body = json.dumps(payload)
    status_text = "OK" if status == 200 else "Bad Request"
    res = f"HTTP/1.1 {status} {status_text}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n{body}"
    return res.encode('utf-8')

@app.route('/submit-info', methods=['POST'])
def submit_info(req):
    global PEER_REGISTRY, ONLINE
    try:
        body = req.body
        if not body:
            return json_response({"code": 0, "message": "Missing body"})
            
        data = json.loads(body)
        name = data.get("name") or getattr(req, "user", "")
        ip = data.get("ip", "")
        port = data.get("port")
        
        if not name:
            return json_response({"code": 0, "message": "Missing name"})
            
        now = time.time()
        if name in PEER_REGISTRY:
            if ip: PEER_REGISTRY[name]["ip"] = ip
            if port: PEER_REGISTRY[name]["port"] = port
            PEER_REGISTRY[name]["last_seen"] = now
        else:
            PEER_REGISTRY[name] = {"ip": ip, "port": port, "last_seen": now}
            
        ONLINE[name] = now
        cleanup_online(now)
        
        return json_response({"code": 1, "message": "Registered successfully"})
    except Exception as e:
        return json_response({"code": 0, "error": str(e)})

@app.route('/get-list', methods=['POST'])
def get_list(req):
    global PEER_REGISTRY, ONLINE
    try:
        now = time.time()
        cleanup_online(now)
        peers = [
            {"name": name, **info}
            for name, info in PEER_REGISTRY.items()
            if ONLINE.get(name)
        ]
        return json_response({"code": 1, "peers": peers})
    except Exception as e:
        return json_response({"code": 0, "error": str(e)})

@app.route('/online', methods=['POST'])
def get_online(req):
    global ONLINE
    try:
        body = req.body
        data = json.loads(body) if body else {}
        name = data.get("name") or getattr(req, "user", "")
        
        now = time.time()
        if name:
            ONLINE[name] = now
            
        cleanup_online(now)
        return json_response({"code": 1, "online": list(ONLINE.keys())})
    except Exception as e:
        return json_response({"code": 0, "error": str(e)})

def create_trackerapp(ip, port):
    app.prepare_address(ip, port)
    app.run()
