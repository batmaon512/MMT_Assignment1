"""
benchmark_th_cb.py
==================
So sánh hiệu năng: Threading Mode vs Callback (select) Mode

Cách dùng:
    # Bước 1: Khởi động threading server (port 9010)
    python start_backend.py --server-port 9010 --mode threading

    # Bước 2: Khởi động callback server (port 9020)
    python start_backend.py --server-port 9020 --mode callback

    # Bước 3: Chạy benchmark
    python benchmark_th_cb.py
    python benchmark_th_cb.py --th-port 9010 --cb-port 9020 -n 500 --step 50

Metrics:
    - Throughput (req/s)
    - Avg latency (ms)
    - P50, P95 latency (ms)
    - Error count
"""

import socket
import threading
import time
import argparse
import statistics
from collections import defaultdict


# =============================================================================
#  Cấu hình mặc định
# =============================================================================

DEFAULT_HOST     = "127.0.0.1"
DEFAULT_TH_PORT  = 9010       # Threading server
DEFAULT_CB_PORT  = 9020       # Callback server
DEFAULT_N        = 300        # Tổng số request
DEFAULT_STEP     = 50         # Bước tăng concurrency
DEFAULT_ENDPOINT = "/status"  # Endpoint test (không cần auth)


# =============================================================================
#  HTTP Request builder
# =============================================================================

def build_http_request(host, port, path="/status"):
    """Tạo HTTP GET request đơn giản."""
    return (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode("utf-8")


# =============================================================================
#  Worker: Gửi 1 request, đo latency
# =============================================================================

def send_request(host, port, path, results, errors, index):
    """
    Gửi 1 HTTP request và đo thời gian latency.

    :param host: Server hostname.
    :param port: Server port.
    :param path: URL path.
    :param results: List dùng chung để ghi latency (ms).
    :param errors: List dùng chung để ghi lỗi.
    :param index: Số thứ tự request (để debug).
    """
    t_start = time.perf_counter()
    try:
        req = build_http_request(host, port, path)

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect((host, port))
        s.sendall(req)

        # Đọc response
        resp = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
        s.close()

        # Kiểm tra HTTP status
        first_line = resp.split(b"\r\n")[0].decode("utf-8", errors="replace")
        if "200" not in first_line and "302" not in first_line:
            errors.append(f"[{index}] Bad status: {first_line}")
            return

        t_end = time.perf_counter()
        latency_ms = (t_end - t_start) * 1000
        results.append(latency_ms)

    except Exception as e:
        errors.append(f"[{index}] {type(e).__name__}: {e}")


# =============================================================================
#  Benchmark engine: Gửi N request với concurrency C
# =============================================================================

def run_benchmark(host, port, path, n, concurrency):
    """
    Gửi N request đến server, tối đa C request đồng thời.

    Mỗi batch gồm C thread chạy song song.
    Đo tổng thời gian và thu thập latency của từng request.

    :param host (str): Server host.
    :param port (int): Server port.
    :param path (str): URL path.
    :param n (int): Tổng số request.
    :param concurrency (int): Số request đồng thời (số thread mỗi batch).
    :return: dict với các metrics.
    """
    latencies = []
    errors    = []
    sent      = 0

    t_total_start = time.perf_counter()

    while sent < n:
        batch_size = min(concurrency, n - sent)
        threads = []

        for i in range(batch_size):
            t = threading.Thread(
                target=send_request,
                args=(host, port, path, latencies, errors, sent + i),
                daemon=True
            )
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        sent += batch_size

    t_total_end = time.perf_counter()
    total_time = t_total_end - t_total_start

    # ── Tính toán metrics ───────────────────────────────────────────
    success_count = len(latencies)
    error_count   = len(errors)

    if success_count == 0:
        return {
            "n": n, "concurrency": concurrency,
            "success": 0, "errors": error_count,
            "rps": 0, "avg": 0, "p50": 0, "p95": 0,
            "total_time": total_time,
        }

    latencies_sorted = sorted(latencies)
    p50_idx = int(len(latencies_sorted) * 0.50)
    p95_idx = int(len(latencies_sorted) * 0.95)

    return {
        "n":          n,
        "concurrency": concurrency,
        "success":    success_count,
        "errors":     error_count,
        "rps":        success_count / total_time,
        "avg":        statistics.mean(latencies),
        "p50":        latencies_sorted[p50_idx - 1],
        "p95":        latencies_sorted[p95_idx - 1],
        "total_time": total_time,
    }


# =============================================================================
#  Check server alive
# =============================================================================

def check_server(host, port, path="/status", label="Server"):
    """Kiểm tra server có đang chạy không."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((host, port))
        req = build_http_request(host, port, path)
        s.sendall(req)
        resp = s.recv(256)
        s.close()
        first = resp.split(b"\r\n")[0].decode("utf-8", errors="replace")
        print(f"  ✅ {label} ({host}:{port}) — {first}")
        return True
    except Exception as e:
        print(f"  ❌ {label} ({host}:{port}) — {e}")
        return False


# =============================================================================
#  Display helpers
# =============================================================================

def print_header():
    print()
    print("=" * 80)
    print(f"  {'Concurrency':>11} │ {'Mode':>8} │ {'RPS':>8} │ {'Avg(ms)':>8} │"
          f" {'P50(ms)':>8} │ {'P95(ms)':>8} │ {'Errors':>6}")
    print("-" * 80)


def print_row(concurrency, mode, result):
    print(
        f"  {concurrency:>11} │ {mode:>8} │ {result['rps']:>8.1f} │"
        f" {result['avg']:>8.1f} │ {result['p50']:>8.1f} │"
        f" {result['p95']:>8.1f} │ {result['errors']:>6}"
    )


def print_separator():
    print("-" * 80)


def print_summary(th_results, cb_results, steps):
    """In bảng so sánh tổng hợp."""
    print()
    print("=" * 80)
    print("  SO SÁNH TỔNG HỢP: Threading vs Callback")
    print("=" * 80)
    print(f"  {'Concurrency':>11} │ {'TH RPS':>8} │ {'CB RPS':>8} │"
          f" {'TH Avg':>8} │ {'CB Avg':>8} │ {'Winner':>10}")
    print("-" * 80)

    for c in steps:
        th = th_results.get(c)
        cb = cb_results.get(c)
        if not th or not cb:
            continue
        winner = "Callback ✅" if cb["rps"] > th["rps"] else "Threading ✅"
        print(
            f"  {c:>11} │ {th['rps']:>8.1f} │ {cb['rps']:>8.1f} │"
            f" {th['avg']:>8.1f} │ {cb['avg']:>8.1f} │ {winner:>10}"
        )
    print("=" * 80)
    print()


# =============================================================================
#  Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Benchmark: Threading Mode vs Callback (select) Mode"
    )
    parser.add_argument("--host",     default=DEFAULT_HOST,     help="Server hostname")
    parser.add_argument("--th-port",  type=int, default=DEFAULT_TH_PORT,  help="Threading server port")
    parser.add_argument("--cb-port",  type=int, default=DEFAULT_CB_PORT,  help="Callback server port")
    parser.add_argument("-n",         type=int, default=DEFAULT_N,        help="Total requests per test")
    parser.add_argument("--step",     type=int, default=DEFAULT_STEP,     help="Concurrency step size")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT,           help="URL path to benchmark")
    parser.add_argument("--max-c",    type=int, default=0,
                        help="Max concurrency (default: n)")
    args = parser.parse_args()

    host     = args.host
    th_port  = args.th_port
    cb_port  = args.cb_port
    n        = args.n
    step     = args.step
    endpoint = args.endpoint
    max_c    = args.max_c if args.max_c > 0 else n

    # Các mức concurrency cần test
    steps = list(range(step, max_c + 1, step))
    if not steps:
        steps = [step]

    print()
    print("=" * 80)
    print("  BENCHMARK: Threading vs Callback (select) Mode")
    print("=" * 80)
    print(f"  Total requests per test : {n}")
    print(f"  Concurrency steps       : {steps}")
    print(f"  Endpoint                : {endpoint}")
    print(f"  Threading server        : {host}:{th_port}")
    print(f"  Callback server         : {host}:{cb_port}")
    print()

    # ── Kiểm tra server ──────────────────────────────────────────────
    print("Checking servers...")
    th_ok = check_server(host, th_port, endpoint, "Threading")
    cb_ok = check_server(host, cb_port, endpoint, "Callback ")
    print()

    if not th_ok and not cb_ok:
        print("❌ Cả 2 server đều không phản hồi. Hãy khởi động trước:")
        print(f"  python start_backend.py --server-port {th_port} --mode threading")
        print(f"  python start_backend.py --server-port {cb_port} --mode callback")
        return

    th_results = {}
    cb_results = {}

    # ── Chạy benchmark từng mức concurrency ─────────────────────────
    print_header()

    for c in steps:
        print_separator()

        # Threading
        if th_ok:
            print(f"  Running threading c={c}...", end="", flush=True)
            th_r = run_benchmark(host, th_port, endpoint, n, c)
            th_results[c] = th_r
            print(f"\r", end="")
            print_row(c, "thread", th_r)

        # Callback
        if cb_ok:
            print(f"  Running callback  c={c}...", end="", flush=True)
            cb_r = run_benchmark(host, cb_port, endpoint, n, c)
            cb_results[c] = cb_r
            print(f"\r", end="")
            print_row(c, "callbk", cb_r)

    print("=" * 80)

    # ── Bảng tổng hợp ───────────────────────────────────────────────
    if th_ok and cb_ok:
        print_summary(th_results, cb_results, steps)

    # ── Phân tích ────────────────────────────────────────────────────
    if th_ok and cb_ok and th_results and cb_results:
        cb_wins = sum(
            1 for c in steps
            if c in th_results and c in cb_results
            and cb_results[c]["rps"] > th_results[c]["rps"]
        )
        th_wins = len(steps) - cb_wins

        print("  📊 Phân tích:")
        print(f"     Callback thắng : {cb_wins}/{len(steps)} scenarios")
        print(f"     Threading thắng: {th_wins}/{len(steps)} scenarios")
        print()
        print("  💡 Lý thuyết:")
        print("     - Callback (select): 1 thread, không có overhead tạo thread")
        print("       → Thắng khi concurrency cao, nhiều kết nối ngắn")
        print("     - Threading: mỗi kết nối 1 thread")
        print("       → Thắng khi request cần CPU-heavy, ít kết nối đồng thời")
        print()


if __name__ == "__main__":
    main()
