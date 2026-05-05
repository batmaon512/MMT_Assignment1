# -*- coding: utf-8 -*-
"""
benchmark.py
~~~~~~~~~~~~~~~~~

So sanh hieu nang coroutine vs threading voi nhieu muc concurrency.

Cach chay:
    python benchmark.py [options]

Vi du:
    # Chay voi steps mac dinh 10,50,100,200
    python benchmark.py

    # Chi dinh steps thu cong
    python benchmark.py --steps 10,50,100,200,500

    # Dung endpoint anh thay vi sleep
    python benchmark.py --endpoint image

    # Day du tuy chinh
    python benchmark.py --co-port 9011 --th-port 9010 -n 200 --steps 50,100,200 --endpoint sleep
"""

import socket
import threading
import asyncio
import time
import statistics
import argparse
import sys


# ──────────────────────────────────────────────
#  Mac dinh
# ──────────────────────────────────────────────
DEFAULT_CO_IP    = "127.0.0.1"
DEFAULT_CO_PORT  = 9011
DEFAULT_TH_IP    = "127.0.0.1"
DEFAULT_TH_PORT  = 9010
DEFAULT_N        = 300   # Max concurrency
DEFAULT_STEP     = 50    # Buoc nhay
DEFAULT_R        = 200   # So request moi buoc
DEFAULT_ENDPOINT = "sleep"
DEFAULT_TIMEOUT  = 30   # 30s de xu ly anh 11MB

ENDPOINTS = {
    "sleep": {
        "coroutine": "/benchmark/async",
        "threading": "/benchmark/sync",
        "desc": "asyncio.sleep / time.sleep (50ms I/O wait)",
    },
    "image": {
        "coroutine": "/benchmark_1.jpg",
        "threading": "/benchmark_1.jpg",
        "desc": "Load file anh 11MB tu disk",
    },
}


# ──────────────────────────────────────────────
#  Parse arguments
# ──────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(
        prog="benchmark.py",
        description="Benchmark: coroutine vs threading — quet nhieu muc concurrency",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Vi du:
  # Buoc nhay tu dong: 50,100,150,200,250,300
  python benchmark.py -n 300 --step 50 -r 200

  # Buoc nhay tu dong voi endpoint anh
  python benchmark.py -n 100 --step 20 --endpoint image

  # Danh sach thu cong (ghi de -n va --step)
  python benchmark.py --steps 10,50,100,200

  # Day du
  python benchmark.py --co-port 9011 --th-port 9010 -n 300 --step 50 -r 200 --endpoint sleep
        """
    )
    parser.add_argument("--co-ip",   default=DEFAULT_CO_IP,   metavar="IP",
                        help="IP coroutine server (default: %(default)s)")
    parser.add_argument("--co-port", default=DEFAULT_CO_PORT, type=int, metavar="PORT",
                        help="Port coroutine server (default: %(default)s)")
    parser.add_argument("--th-ip",   default=DEFAULT_TH_IP,   metavar="IP",
                        help="IP threading server (default: %(default)s)")
    parser.add_argument("--th-port", default=DEFAULT_TH_PORT, type=int, metavar="PORT",
                        help="Port threading server (default: %(default)s)")
    parser.add_argument("-n", "--max-c", default=DEFAULT_N, type=int, metavar="N",
                        help="Max concurrency (buoc nhay chay den N). Default: %(default)s")
    parser.add_argument("--step", default=DEFAULT_STEP, type=int, metavar="STEP",
                        help="Buoc nhay concurrency. Vi du: --step 50 -> 50,100,...,N. Default: %(default)s")
    parser.add_argument("-r", "--requests", default=DEFAULT_R, type=int, metavar="R",
                        help="So request gui moi buoc. Default: %(default)s")
    parser.add_argument("--steps", default=None, metavar="LIST",
                        help="(Tuy chon) Danh sach concurrency thu cong, vi du: 10,50,200. Ghi de -n va --step.")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT,
                        choices=list(ENDPOINTS.keys()),
                        help="Loai endpoint: sleep hoac image (default: %(default)s)")
    return parser.parse_args()


def build_steps(args) -> list:
    """Tao danh sach concurrency tu tham so."""
    if args.steps is not None:
        # Thu cong: --steps 10,50,100,200
        try:
            steps = [int(s.strip()) for s in args.steps.split(",") if s.strip()]
            if not steps:
                raise ValueError
            return sorted(set(steps))
        except ValueError:
            print(f"  [ERR] --steps phai la danh sach so nguyen, vi du: 10,50,100,200")
            sys.exit(1)
    else:
        # Tu dong: buoc nhay tu step den max-c
        if args.step <= 0:
            print(f"  [ERR] --step phai lon hon 0")
            sys.exit(1)
        if args.max_c <= 0:
            print(f"  [ERR] -n phai lon hon 0")
            sys.exit(1)
        steps = list(range(args.step, args.max_c + 1, args.step))
        if not steps:
            steps = [args.max_c]
        return steps


# ──────────────────────────────────────────────
#  Kiem tra server
# ──────────────────────────────────────────────
def check_server(host: str, port: int, label: str) -> bool:
    try:
        s = socket.create_connection((host, port), timeout=3)
        s.close()
        print(f"  [OK] {label} tai {host}:{port}")
        return True
    except Exception:
        print(f"  [ERR] Khong ket noi duoc {label} tai {host}:{port}")
        return False


# ──────────────────────────────────────────────
#  HTTP request builder
# ──────────────────────────────────────────────
def make_request(host: str, port: int, path: str) -> bytes:
    return (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode()


# ──────────────────────────────────────────────
#  Workers
# ──────────────────────────────────────────────
def sync_worker(host, port, path, results, errors):
    req = make_request(host, port, path)
    start = time.perf_counter()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(DEFAULT_TIMEOUT)
        s.connect((host, port))
        s.sendall(req)
        resp = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
        s.close()
        results.append(time.perf_counter() - start)
    except Exception as e:
        errors.append(str(e))


async def async_worker(host, port, path, results, errors, sem):
    req = make_request(host, port, path)
    async with sem:
        start = time.perf_counter()
        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.write(req)
            await writer.drain()
            resp = b""
            while True:
                chunk = await reader.read(65536)  # 64KB: giam so lan await voi payload lon
                if not chunk:
                    break
                resp += chunk
            writer.close()
            await writer.wait_closed()
            results.append(time.perf_counter() - start)
        except Exception as e:
            errors.append(str(e))


# ──────────────────────────────────────────────
#  Fire functions
# ──────────────────────────────────────────────
def fire_threaded(host, port, path, n, c):
    results, errors = [], []
    total_start = time.perf_counter()
    sent = 0
    while sent < n:
        batch = min(c, n - sent)
        threads = [
            threading.Thread(target=sync_worker, args=(host, port, path, results, errors))
            for _ in range(batch)
        ]
        for t in threads: t.start()
        for t in threads: t.join()
        sent += batch
    return results, errors, time.perf_counter() - total_start


async def _gather_async(host, port, path, n, c, results, errors):
    sem = asyncio.Semaphore(c)
    tasks = [
        asyncio.create_task(async_worker(host, port, path, results, errors, sem))
        for _ in range(n)
    ]
    await asyncio.gather(*tasks)


def fire_async(host, port, path, n, c):
    results, errors = [], []
    total_start = time.perf_counter()
    asyncio.run(_gather_async(host, port, path, n, c, results, errors))
    return results, errors, time.perf_counter() - total_start


# ──────────────────────────────────────────────
#  Thong ke
# ──────────────────────────────────────────────
def _pct(data, p):
    s = sorted(data)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(results, errors, total):
    if not results:
        return dict(ok=0, err=len(errors), rps=0,
                    avg=0, p50=0, p95=0, mn=0, mx=0, sd=0, total=round(total,4))
    ms = [r * 1000 for r in results]
    return dict(
        ok=len(results),
        err=len(errors),
        total=round(total, 4),
        rps=round(len(results) / total, 2),
        avg=round(statistics.mean(ms), 2),
        p50=round(_pct(ms, 50), 2),
        p95=round(_pct(ms, 95), 2),
        mn=round(min(ms), 2),
        mx=round(max(ms), 2),
        sd=round(statistics.stdev(ms) if len(ms) > 1 else 0, 2),
    )


# ──────────────────────────────────────────────
#  In ket qua 1 buoc
# ──────────────────────────────────────────────
def print_step_result(step: int, co: dict, th: dict):
    print(f"\n  --- Concurrency = {step} ---")
    print(f"  {'Metric':<22} {'coroutine':>12} {'threading':>12}  Winner")
    print(f"  {'-'*56}")

    def row(label, key, low_better=True):
        va, vb = co[key], th[key]
        if va == 0 and vb == 0:
            w = "N/A"
        elif va == vb:
            w = "draw"
        elif (va < vb) == low_better:
            w = "coroutine [WIN]"
        else:
            w = "threading [WIN]"
        print(f"  {label:<22} {va:>12.2f} {vb:>12.2f}  {w}")

    row("Throughput (req/s)", "rps", low_better=False)
    row("Avg latency (ms)",   "avg")
    row("p50 latency (ms)",   "p50")
    row("p95 latency (ms)",   "p95")
    row("Std dev (ms)",       "sd")
    err_info = f"  Errors: coroutine={co['err']}  threading={th['err']}"
    if co['err'] or th['err']:
        print(err_info)


# ──────────────────────────────────────────────
#  In bang tong hop cuoi cung
# ──────────────────────────────────────────────
def print_summary_table(steps, all_co, all_th):
    print(f"\n{'='*80}")
    print(f"  BANG TONG HOP — tat ca {len(steps)} buoc concurrency")
    print(f"{'='*80}")

    # Header
    print(f"  {'Concurrency':>11} | {'-- COROUTINE --':^28} | {'-- THREADING --':^28}")
    print(f"  {'':>11} | {'RPS':>8} {'Avg':>8} {'p95':>8} | {'RPS':>8} {'Avg':>8} {'p95':>8}  Winner(RPS)")
    print(f"  {'-'*79}")

    for step, co, th in zip(steps, all_co, all_th):
        if co['rps'] > th['rps']:
            w = "co"
        elif th['rps'] > co['rps']:
            w = "th"
        else:
            w = "="
        print(
            f"  {step:>11} |"
            f" {co['rps']:>8.1f} {co['avg']:>8.1f} {co['p95']:>8.1f} |"
            f" {th['rps']:>8.1f} {th['avg']:>8.1f} {th['p95']:>8.1f}"
            f"  [{w}]"
        )
    print()


# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────
if __name__ == "__main__":
    args = parse_args()
    steps = build_steps(args)
    ep = ENDPOINTS[args.endpoint]

    co_path = ep["coroutine"]
    th_path = ep["threading"]

    print(f"\n{'='*64}")
    print(f"  BENCHMARK: coroutine vs threading")
    print(f"{'='*64}")
    print(f"  coroutine : {args.co_ip}:{args.co_port}  -> {co_path}")
    print(f"  threading : {args.th_ip}:{args.th_port}  -> {th_path}")
    print(f"  Endpoint  : {args.endpoint} ({ep['desc']})")
    print(f"  Requests  : {args.requests} moi buoc")
    print(f"  Steps (c) : {steps}")
    if args.steps is None:
        print(f"  (tu dong: buoc nhay {args.step}, max {args.max_c})")
    print()

    ok_co = check_server(args.co_ip, args.co_port, "coroutine server")
    ok_th = check_server(args.th_ip, args.th_port, "threading server")
    if not ok_co or not ok_th:
        print("\n  [ERR] Hay chay du 2 server roi thu lai.")
        sys.exit(1)

    all_co_results = []
    all_th_results = []

    for i, step in enumerate(steps):
        n = args.requests
        c = step
        print(f"\n  [{i+1}/{len(steps)}] Concurrency = {step}, N = {n}")

        # Coroutine
        print(f"  -> coroutine ...", end="", flush=True)
        r_co, e_co, t_co = fire_async(args.co_ip, args.co_port, co_path, n, c)
        co_stat = summarize(r_co, e_co, t_co)
        print(f"  RPS={co_stat['rps']:.1f}  avg={co_stat['avg']:.1f}ms  p95={co_stat['p95']:.1f}ms  err={co_stat['err']}")

        # Threading
        print(f"  -> threading ...", end="", flush=True)
        r_th, e_th, t_th = fire_threaded(args.th_ip, args.th_port, th_path, n, c)
        th_stat = summarize(r_th, e_th, t_th)
        print(f"  RPS={th_stat['rps']:.1f}  avg={th_stat['avg']:.1f}ms  p95={th_stat['p95']:.1f}ms  err={th_stat['err']}")

        all_co_results.append(co_stat)
        all_th_results.append(th_stat)

        print_step_result(step, co_stat, th_stat)

    # Bang tong hop
    print_summary_table(steps, all_co_results, all_th_results)
