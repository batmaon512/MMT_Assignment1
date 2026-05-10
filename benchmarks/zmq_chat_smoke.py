"""Smoke test for the ZeroMQ chat backend.

What it verifies:
- the chat server starts with a ZeroMQ PULL endpoint
- clients can register without HTTP
- direct messages are delivered to the right recipient
- broadcast reaches all registered clients

Run:
  python benchmarks/zmq_chat_smoke.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import zmq


ROOT = Path(__file__).resolve().parents[1]
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8011
ALICE_RECV_PORT = 8012
BOB_RECV_PORT = 8013


def wait_for_port_ready(ctx: zmq.Context, endpoint: str, timeout_s: float = 5.0) -> zmq.Socket:
    sock = ctx.socket(zmq.PUSH)
    sock.connect(endpoint)
    deadline = time.time() + timeout_s
    return sock, deadline


def recv_json_or_fail(sock: zmq.Socket, label: str, timeout_s: float = 5.0) -> dict:
    poller = zmq.Poller()
    poller.register(sock, zmq.POLLIN)
    events = dict(poller.poll(timeout_s * 1000))
    if sock not in events:
        raise AssertionError(f"Timed out waiting for {label}")
    return sock.recv_json()


def main() -> int:
    server_cmd = [
        sys.executable,
        str(ROOT / "start_chatapp.py"),
        "--bind-ip",
        SERVER_HOST,
        "--bind-port",
        str(SERVER_PORT),
    ]
    server = subprocess.Popen(server_cmd, cwd=ROOT)
    try:
        time.sleep(1.0)

        ctx = zmq.Context.instance()

        # Alice receive socket
        alice_recv = ctx.socket(zmq.PULL)
        alice_recv.bind(f"tcp://127.0.0.1:{ALICE_RECV_PORT}")

        # Bob receive socket
        bob_recv = ctx.socket(zmq.PULL)
        bob_recv.bind(f"tcp://127.0.0.1:{BOB_RECV_PORT}")

        push = ctx.socket(zmq.PUSH)
        push.connect(f"tcp://{SERVER_HOST}:{SERVER_PORT}")

        # Register both users
        push.send_json({"type": "register", "name": "alice", "recv_port": ALICE_RECV_PORT, "ip": "127.0.0.1"})
        push.send_json({"type": "register", "name": "bob", "recv_port": BOB_RECV_PORT, "ip": "127.0.0.1"})

        # Direct message alice -> bob
        push.send_json({"type": "send", "from": "alice", "to": "bob", "message": "hello bob"})
        bob_msg = recv_json_or_fail(bob_recv, "direct message to bob")
        assert bob_msg["from"] == "alice"
        assert bob_msg["to"] == "bob"
        assert bob_msg["message"] == "hello bob"

        # Broadcast from alice -> alice and bob
        push.send_json({"type": "broadcast", "from": "alice", "message": "all hands"})
        alice_msg = recv_json_or_fail(alice_recv, "broadcast to alice")
        bob_broadcast = recv_json_or_fail(bob_recv, "broadcast to bob")
        assert alice_msg["to"] == "broadcast"
        assert alice_msg["message"] == "all hands"
        assert bob_broadcast["to"] == "broadcast"
        assert bob_broadcast["message"] == "all hands"

        print("SMOKE TEST PASSED")
        return 0
    finally:
        try:
            server.terminate()
            server.wait(timeout=5)
        except Exception:
            server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
