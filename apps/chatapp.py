"""ZeroMQ-based chat backend (brokerless PUSH/PULL registration + delivery).

Clients send JSON messages to the server's PULL socket. Message types:
 - register: {"type":"register","name":"alice","recv_port":8002}
 - send: {"type":"send","from":"alice","to":"bob","message":"hi"}
 - broadcast: {"type":"broadcast","from":"alice","message":"hello everyone"}

The server stores a mapping of user -> push-socket (connected to client's recv endpoint)
and forwards messages accordingly. This replaces the previous HTTP-based chat backend.
"""
import json
import time
import zmq
import threading

REGISTRY = {}  # name -> {'addr': 'tcp://ip:port', 'socket': zmq.Socket}
SOCKET_LOCK = threading.Lock()

def _connect_push(ctx, name, addr):
    """Create and cache a PUSH socket connected to addr for user name."""
    with SOCKET_LOCK:
        entry = REGISTRY.get(name)
        if entry and entry.get('addr') == addr and entry.get('socket') is not None:
            return entry['socket']
        if entry and entry.get('socket') is not None:
            try:
                entry['socket'].close()
            except Exception:
                pass
        push = ctx.socket(zmq.PUSH)
        push.connect(addr)
        REGISTRY[name] = {'addr': addr, 'socket': push}
        return push

def _send_to_user(ctx, name, payload):
    entry = REGISTRY.get(name)
    if not entry:
        print(f"[chatserver] Unknown recipient: {name}")
        return False
    push = entry.get('socket')
    if not push:
        push = _connect_push(ctx, name, entry['addr'])
    try:
        push.send_json(payload)
        return True
    except Exception as e:
        print(f"[chatserver] Error sending to {name}: {e}")
        return False

def _handle_message(ctx, msg_bytes):
    try:
        obj = json.loads(msg_bytes.decode('utf-8'))
    except Exception:
        print("[chatserver] Received invalid JSON")
        return

    typ = obj.get('type')
    if typ == 'register':
        name = obj.get('name')
        recv_port = obj.get('recv_port')
        ip = obj.get('ip') or obj.get('host') or obj.get('address') or '127.0.0.1'
        if not name:
            print("[chatserver] Invalid register message: missing name")
            return
        try:
            recv_port = int(recv_port)
        except Exception:
            print(f"[chatserver] Invalid register message for {name}: bad port {recv_port}")
            return
        addr = f"tcp://{ip}:{recv_port}"
        _connect_push(ctx, name, addr)
        print(f"[chatserver] Registered {name} -> {addr}")
    elif typ == 'send':
        to = obj.get('to')
        frm = obj.get('from')
        message = obj.get('message')
        if not to or not frm or not message:
            print(f"[chatserver] Invalid send payload: {obj}")
            return
        payload = {'from': frm, 'to': to, 'message': message, 'time': int(time.time()*1000)}
        if to == 'broadcast':
            # Broadcast to all registered users
            for user in list(REGISTRY.keys()):
                _send_to_user(ctx, user, payload)
        else:
            _send_to_user(ctx, to, payload)
    elif typ == 'broadcast':
        frm = obj.get('from')
        message = obj.get('message')
        payload = {'from': frm, 'to': 'broadcast', 'message': message, 'time': int(time.time()*1000)}
        for user in list(REGISTRY.keys()):
            _send_to_user(ctx, user, payload)
    else:
        print(f"[chatserver] Unknown message type: {typ}")

def create_chatapp(bind_ip: str, bind_port: int, tracker_host=None, tracker_p=None):
    """Start the ZeroMQ chat server.

    The legacy tracker_host/tracker_p parameters are accepted for backward compatibility
    but ignored by the ZeroMQ implementation.
    """
    ctx = zmq.Context()
    pull = ctx.socket(zmq.PULL)
    bind_addr = f"tcp://{bind_ip}:{bind_port}"
    pull.bind(bind_addr)
    print(f"[chatserver] Listening PULL <- {bind_addr}")

    try:
        while True:
            msg = pull.recv()
            _handle_message(ctx, msg)
    except KeyboardInterrupt:
        print("[chatserver] Shutting down")
    finally:
        with SOCKET_LOCK:
            for entry in REGISTRY.values():
                s = entry.get('socket')
                try:
                    if s is not None:
                        s.close()
                except Exception:
                    pass
        pull.close()
        ctx.term()

