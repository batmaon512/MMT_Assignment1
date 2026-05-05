import json
import time
import asyncio
from urllib import request as urllib_request

from daemon import AsynapRous

app = AsynapRous()

tracker_ip = "127.0.0.1"
tracker_port = 9000
MESSAGE_QUEUE = []

# Local cache: { name -> {"ip": ..., "port": ...} }
# Populated when peers register or connect-peer is called.
# Allows P2P communication even when tracker is offline.
PEER_CACHE = {}

def json_response(payload, status=200):
    body = json.dumps(payload)
    status_text = "OK" if status == 200 else "Bad Request"
    res = f"HTTP/1.1 {status} {status_text}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n{body}"
    return res.encode('utf-8')

@app.route('/api/login', methods=['POST'])
def app_login(req):
    if getattr(req, 'user', None):
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

def make_tracker_request(path, data, req=None):
    url = f"http://{tracker_ip}:{tracker_port}{path}"
    try:
        headers = {'Content-Type': 'application/json'}
        if req and 'cookie' in req.headers:
            headers['Cookie'] = req.headers['cookie']
            
        urllib_req = urllib_request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
        with urllib_request.urlopen(urllib_req, timeout=5) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        return {"code": 0, "error": str(e)}

@app.route('/submit-info', methods=['POST'])
async def submit_info(req):
    body = req.body
    data = json.loads(body) if body else {}
    data["name"] = data.get("name") or getattr(req, "user", "")
    res = await make_tracker_request_async("/submit-info", data, req)
    return json_response(res)

@app.route('/get-list', methods=['POST'])
async def get_list(req):
    global PEER_CACHE
    res = await make_tracker_request_async("/get-list", {}, req)
    # Cache peer info locally for offline use
    if res.get("code") == 1:
        for peer in res.get("peers", []):
            name = peer.get("name")
            if name:
                PEER_CACHE[name] = {"ip": peer.get("ip"), "port": peer.get("port")}
    return json_response(res)


@app.route('/peers', methods=['POST'])
def peers(req):
    """Return the locally cached peers (name, ip, port)."""
    global PEER_CACHE
    peers = [{"name": n, "ip": info.get("ip"), "port": info.get("port")} for n, info in PEER_CACHE.items()]
    return json_response({"code": 1, "peers": peers})

@app.route('/online', methods=['POST'])
async def online(req):
    body = req.body
    data = json.loads(body) if body else {}
    data["name"] = data.get("name") or getattr(req, "user", "")
    res = await make_tracker_request_async("/online", data, req)
    return json_response(res)

@app.route('/connect-peer', methods=['POST'])
async def connect_peer(req):
    global PEER_CACHE
    body = req.body
    data = json.loads(body) if body else {}
    target = data.get("target")
    if not target:
        return json_response({"code": 0, "message": "Missing target"})

    # Check local cache first (works even without tracker)
    if target in PEER_CACHE:
        peer = PEER_CACHE[target]
        return json_response({"code": 1, "message": "Connected (cached)", "peer": {"name": target, **peer}})

    # Fall back to tracker
    peers_res = await make_tracker_request_async("/get-list", {}, req)
    peers = peers_res.get("peers", [])
    target_peer = next((p for p in peers if p["name"] == target), None)

    if target_peer:
        # Store in local cache for future offline use
        PEER_CACHE[target] = {"ip": target_peer["ip"], "port": target_peer["port"]}
        return json_response({"code": 1, "message": "Connected", "peer": target_peer})
    else:
        return json_response({"code": 0, "message": "Peer not found"})

async def make_tracker_request_async(path, data, req=None):
    """Non-blocking call to tracker using asyncio.open_connection."""
    try:
        headers = {'Content-Type': 'application/json'}
        cookie = ""
        auth_header = ""
        if req and req.headers:
            if 'cookie' in req.headers:
                cookie = req.headers['cookie']
            # Forward Authorization header if present so tracker can authenticate
            if 'authorization' in req.headers:
                auth_header = req.headers['authorization']

        body = json.dumps(data).encode('utf-8')
        http_request = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {tracker_ip}:{tracker_port}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            + (f"Cookie: {cookie}\r\n" if cookie else "")
            + (f"Authorization: {auth_header}\r\n" if auth_header else "")
            + f"Connection: close\r\n\r\n"
        ).encode('utf-8') + body

        reader, writer = await asyncio.open_connection(tracker_ip, tracker_port)
        # Debug: show outgoing request to tracker
        try:
            print("[ChatApp] Outgoing tracker request:\n", http_request.decode('utf-8', errors='replace'))
        except Exception:
            pass
        writer.write(http_request)
        await writer.drain()

        resp_bytes = b""
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                break
            resp_bytes += chunk

        writer.close()
        await writer.wait_closed()

        # Debug: show raw response from tracker
        try:
            print("[ChatApp] Raw tracker response:\n", resp_bytes.decode('utf-8', errors='replace'))
        except Exception:
            pass
        # Parse HTTP response body
        if b"\r\n\r\n" in resp_bytes:
            resp_body = resp_bytes.split(b"\r\n\r\n", 1)[1]
        else:
            resp_body = resp_bytes
        return json.loads(resp_body.decode('utf-8'))
    except Exception as e:
        return {"code": 0, "error": str(e)}

def make_tracker_request(path, data, req=None):
    """Synchronous wrapper - kept for non-async route handlers."""
    url = f"http://{tracker_ip}:{tracker_port}{path}"
    try:
        headers = {'Content-Type': 'application/json'}
        if req and req.headers:
            if 'cookie' in req.headers:
                headers['Cookie'] = req.headers['cookie']
            # Forward Authorization header if present
            if 'authorization' in req.headers:
                headers['Authorization'] = req.headers['authorization']
        urllib_req = urllib_request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
        with urllib_request.urlopen(urllib_req, timeout=5) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        return {"code": 0, "error": str(e)}

async def send_to_peer(target_ip, target_port, payload):
    """Send a message directly to a peer using asyncio non-blocking TCP."""
    try:
        body = json.dumps(payload).encode('utf-8')
        http_request = (
            f"POST /internal/receive-msg HTTP/1.1\r\n"
            f"Host: {target_ip}:{target_port}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode('utf-8') + body

        reader, writer = await asyncio.open_connection(target_ip, int(target_port))
        writer.write(http_request)
        await writer.drain()
        await reader.read(4096)  # Read and discard response
        writer.close()
        await writer.wait_closed()
        return True
    except Exception as e:
        print(f"[ChatApp] Error sending to peer {target_ip}:{target_port}: {e}")
        return False

@app.route('/send-peer', methods=['POST'])
async def send_peer(req):
    global PEER_CACHE
    body = req.body
    data = json.loads(body) if body else {}
    target_name = data.get("to")
    message = data.get("message")
    sender_name = getattr(req, "user", None) or data.get("from")
    
    if not target_name or not message:
        return json_response({"code": 0, "message": "Missing fields"})

    # Try local cache first (P2P - no tracker needed)
    target_peer = PEER_CACHE.get(target_name)

    if not target_peer:
        # Fall back to tracker
        peers_res = await make_tracker_request_async("/get-list", {}, req)
        peers = peers_res.get("peers", [])
        found = next((p for p in peers if p["name"] == target_name), None)
        if found:
            PEER_CACHE[target_name] = {"ip": found["ip"], "port": found["port"]}
            target_peer = PEER_CACHE[target_name]

    if not target_peer:
        return json_response({"code": 0, "message": f"Peer '{target_name}' not found (tracker offline?)"})
        
    payload = {
        "from": sender_name,
        "to": target_name,
        "message": message,
        "time": time.time() * 1000
    }
    
    success = await send_to_peer(target_peer["ip"], target_peer["port"], payload)
    if success:
        return json_response({"code": 1, "message": "Message sent"})
    else:
        return json_response({"code": 0, "message": "Failed to send message"})

@app.route('/broadcast-peer', methods=['POST'])
async def broadcast_peer(req):
    global PEER_CACHE
    body = req.body
    data = json.loads(body) if body else {}
    message = data.get("message")
    sender_name = getattr(req, "user", None) or data.get("from")
    
    if not message:
        return json_response({"code": 0, "message": "Missing message"})

    # Merge tracker list into local cache (if tracker available)
    try:
        peers_res = await make_tracker_request_async("/get-list", {}, req)
        for p in peers_res.get("peers", []):
            name = p.get("name")
            if name:
                PEER_CACHE[name] = {"ip": p["ip"], "port": p["port"]}
    except Exception:
        pass  # Use cached peers if tracker offline
    
    payload = {
        "from": sender_name,
        "to": "broadcast",
        "message": message,
        "time": time.time() * 1000
    }
    
    # Send to all known peers concurrently (pure P2P)
    tasks = [
        send_to_peer(info["ip"], info["port"], payload)
        for name, info in PEER_CACHE.items()
        if name != sender_name
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
            
    return json_response({"code": 1, "message": "Broadcast complete"})

@app.route('/internal/receive-msg', methods=['POST'])
def internal_receive_msg(req):
    global MESSAGE_QUEUE
    body = req.body
    if body:
        try:
            data = json.loads(body)
            MESSAGE_QUEUE.append(data)
            return json_response({"code": 1, "message": "Received"})
        except Exception:
            return json_response({"code": 0, "message": "Invalid JSON"})
    return json_response({"code": 0, "message": "Empty body"})

@app.route('/poll-messages', methods=['POST'])
def poll_messages(req):
    global MESSAGE_QUEUE
    msgs = list(MESSAGE_QUEUE)
    MESSAGE_QUEUE.clear()
    return json_response({"code": 1, "messages": msgs})

def create_chatapp(ip, port, tracker_host, tracker_p):
    global tracker_ip, tracker_port, own_port
    tracker_ip = tracker_host
    tracker_port = tracker_p
    own_port = port
    app.prepare_address(ip, port)
    app.run()
