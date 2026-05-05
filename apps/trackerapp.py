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

import socket

def get_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't need to be reachable, just to force OS to pick the right interface
        s.connect(('8.8.8.8', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

MY_LAN_IP = get_lan_ip()
print(f"[Tracker] Detected LAN IP: {MY_LAN_IP}")

def resolve_peer_ip(candidate_ip, remote_addr):
    """Resolve peer address to a reachable IPv4 when possible."""
    ip = (candidate_ip or "").strip()

    # Prefer caller-provided address when valid and not wildcard/loopback.
    if ip and ip not in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
        try:
            resolved = socket.gethostbyname(ip)
            if resolved not in ["127.0.0.1", "0.0.0.0"]:
                return resolved
        except Exception:
            parts = ip.split('.')
            if len(parts) == 4:
                try:
                    if all(0 <= int(p) <= 255 for p in parts) and ip not in ["127.0.0.1", "0.0.0.0"]:
                        return ip
                except Exception:
                    pass

    # Fallback to source socket address.
    if remote_addr and remote_addr[0] not in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
        return remote_addr[0]

    # Last resort for same-machine client.
    return MY_LAN_IP

def get_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't need to be reachable, just to force OS to pick the right interface
        s.connect(('8.8.8.8', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

MY_LAN_IP = get_lan_ip()
print(f"[Tracker] Detected LAN IP: {MY_LAN_IP}")

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

        remote = getattr(req, "remote_addr", None)
        resolved_ip = resolve_peer_ip(ip, remote)
        try:
            print(f"[Tracker] submit-info from remote={remote} candidate_ip={ip!r} resolved={resolved_ip}")
        except Exception:
            pass
        ip = resolved_ip

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
        
        print(f"[Tracker] Registered: {name} at {ip}:{port}")
        try:
            print(f"[Tracker] Current registry: {PEER_REGISTRY}")
        except Exception:
            pass

        return json_response({"code": 1, "message": "Registered successfully"})
    except Exception as e:
        print(f"[Tracker] Error in submit_info: {e}")
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
        try:
            print(f"[Tracker] get-list -> returning peers={peers}")
        except Exception:
            pass
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
