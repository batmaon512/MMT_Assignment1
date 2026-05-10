"""Inproc demo: producer and worker in the same process using inproc transport.

Useful to demonstrate intra-process near-zero latency communication.
"""
import threading
import time
import zmq

INPROC_ADDR = "inproc://workers"

def worker_thread(ctx: zmq.Context, id: int):
    sock = ctx.socket(zmq.PULL)
    sock.connect(INPROC_ADDR)
    print(f"inproc worker-{id} connected")
    try:
        while True:
            msg = sock.recv_string()
            print(f"worker-{id} received: {msg}")
    except Exception:
        pass
    finally:
        sock.close()

def main(count: int = 10):
    ctx = zmq.Context()
    # Create PULL and bind in the same context
    pull = ctx.socket(zmq.PULL)
    pull.bind(INPROC_ADDR)

    # Start worker threads that connect to inproc
    threads = []
    for i in range(2):
        t = threading.Thread(target=worker_thread, args=(ctx, i), daemon=True)
        t.start()
        threads.append(t)

    # Create PUSH and connect to the inproc endpoint
    push = ctx.socket(zmq.PUSH)
    push.connect(INPROC_ADDR)

    try:
        for i in range(count):
            msg = f"inproc-msg-{i}"
            push.send_string(msg)
            print("sent", msg)
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        push.close()
        pull.close()
        ctx.term()

if __name__ == "__main__":
    main()
