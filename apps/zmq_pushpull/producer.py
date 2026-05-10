"""Brokerless PUSH producer (binds) for low-latency push-pull demo.

Usage:
  python -m apps.zmq_pushpull.producer

This producer binds a PUSH socket at tcp://*:5560. Multiple workers
can connect with PULL to the same endpoint and will receive a subset
of messages in a round-robin fashion.
"""
import time
import zmq
import argparse

DEFAULT_BIND = "tcp://*:5560"

def main(bind_addr: str = DEFAULT_BIND, count: int = 100, interval: float = 0.01):
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PUSH)
    sock.bind(bind_addr)

    print(f"Producer bound PUSH -> {bind_addr}")
    try:
        for i in range(count):
            msg = f"task-{i}"
            sock.send_string(msg)
            print("sent", msg)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Producer interrupted")
    finally:
        sock.close()
        ctx.term()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--bind", default=DEFAULT_BIND)
    p.add_argument("--count", type=int, default=100)
    p.add_argument("--interval", type=float, default=0.01)
    args = p.parse_args()
    main(args.bind, args.count, args.interval)
