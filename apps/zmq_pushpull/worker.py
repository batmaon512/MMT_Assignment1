"""Brokerless PULL worker for low-latency push-pull demo.

Usage:
  python -m apps.zmq_pushpull.worker

The worker connects to the producer endpoint and processes messages.
Multiple workers may be started and they'll share the load.
"""
import time
import zmq
import argparse
import socket

DEFAULT_CONNECT = "tcp://127.0.0.1:5560"

def main(connect_addr: str = DEFAULT_CONNECT, work_time: float = 0.02):
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PULL)
    sock.connect(connect_addr)

    hostname = socket.gethostname()
    print(f"Worker {hostname} connected PULL <- {connect_addr}")
    try:
        while True:
            msg = sock.recv_string()
            print(f"{hostname} got: {msg}")
            # simulate processing time
            time.sleep(work_time)
    except KeyboardInterrupt:
        print("Worker interrupted")
    finally:
        sock.close()
        ctx.term()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--connect", default=DEFAULT_CONNECT)
    p.add_argument("--work-time", type=float, default=0.02)
    args = p.parse_args()
    main(args.connect, args.work_time)
