import socket
import threading
import time
import argparse
import statistics
import csv
import os

# Configuration
DEFAULT_HOST = "127.0.0.1"
DEFAULT_TH_PORT = 9010
DEFAULT_CB_PORT = 9020
DEFAULT_AS_PORT = 9030
DEFAULT_PROXY_PORT = 8080
DEFAULT_N = 2000
DEFAULT_STEP = 200
DEFAULT_ENDPOINT = "/status"


def build_http_request(host, port, path="/status"):
    return (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode("utf-8")


def send_request(host, port, path, results, errors, index):
    t_start = time.perf_counter()
    try:
        req = build_http_request(host, port, path)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect((host, port))
        s.sendall(req)

        resp = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
        s.close()

        first_line = resp.split(b"\r\n")[0].decode("utf-8", errors="replace")
        if "200" not in first_line and "302" not in first_line:
            errors.append(f"[{index}] Bad status: {first_line}")
            return

        t_end = time.perf_counter()
        results.append((t_end - t_start) * 1000)
    except Exception as e:
        errors.append(f"[{index}] {type(e).__name__}: {e}")


def run_benchmark(host, port, path, n, concurrency):
    latencies, errors = [], []
    sent = 0
    t_total_start = time.perf_counter()

    while sent < n:
        batch_size = min(concurrency, n - sent)
        threads = []
        for i in range(batch_size):
            t = threading.Thread(target=send_request, args=(
                host, port, path, latencies, errors, sent + i))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        sent += batch_size

    total_time = time.perf_counter() - t_total_start
    success = len(latencies)

    if success == 0:
        return {"rps": 0, "avg": 0, "p95": 0, "errors": len(errors)}

    latencies.sort()
    p95 = latencies[int(success * 0.95) - 1]
    return {
        "rps": success / total_time,
        "avg": statistics.mean(latencies),
        "p95": p95,
        "errors": len(errors)
    }


def check_server(host, port, label):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect((host, port))
        s.sendall(build_http_request(host, port))
        s.recv(256)
        s.close()
        print(f"  [OK] {label:<10} (Port {port})")
        return True
    except:
        print(f"  [--] {label:<10} (Port {port}) - OFFLINE")
        return False


def save_csv(filename, headers, rows):
    with open(filename, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f"✅ Data exported to file: {filename}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark Load Balancer")
    parser.add_argument("-n", type=int, default=DEFAULT_N,
                        help="Total requests")
    parser.add_argument("--step", type=int,
                        default=DEFAULT_STEP, help="Concurrency step")
    parser.add_argument(
        "--endpoint", default=DEFAULT_ENDPOINT, help="API Endpoint")
    args = parser.parse_args()

    steps = list(range(args.step, args.n + 1, args.step)) or [args.step]

    print("\n" + "="*85)
    print("  ASYNAPROUS BENCHMARK: SERVERS vs PROXY LOAD BALANCER")
    print("="*85)

    th_ok = check_server(DEFAULT_HOST, DEFAULT_TH_PORT, "Threading")
    cb_ok = check_server(DEFAULT_HOST, DEFAULT_CB_PORT, "Callback")
    as_ok = check_server(DEFAULT_HOST, DEFAULT_AS_PORT, "Asyncio")

    csv_servers = []

    print("\n--- BENCHMARK EACH SERVER ---")
    print(f" {'Concurrency':>11} | {'Mode':>10} | {'RPS (req/s)':>12} | {'Avg (ms)':>10} | {'P95 (ms)':>10} | {'Errors':>6}")
    print("-" * 85)

    for c in steps:
        if th_ok:
            r = run_benchmark(DEFAULT_HOST, DEFAULT_TH_PORT,
                              args.endpoint, args.n, c)
            csv_servers.append([c, "Threading", round(r['rps'], 1), round(
                r['avg'], 1), round(r['p95'], 1), r['errors']])
            print(
                f" {c:>11} | {'Threading':>10} | {r['rps']:>12.1f} | {r['avg']:>10.1f} | {r['p95']:>10.1f} | {r['errors']:>6}")
        if cb_ok:
            r = run_benchmark(DEFAULT_HOST, DEFAULT_CB_PORT,
                              args.endpoint, args.n, c)
            csv_servers.append([c, "Callback", round(r['rps'], 1), round(
                r['avg'], 1), round(r['p95'], 1), r['errors']])
            print(
                f" {c:>11} | {'Callback':>10} | {r['rps']:>12.1f} | {r['avg']:>10.1f} | {r['p95']:>10.1f} | {r['errors']:>6}")
        if as_ok:
            r = run_benchmark(DEFAULT_HOST, DEFAULT_AS_PORT,
                              args.endpoint, args.n, c)
            csv_servers.append([c, "Asyncio", round(r['rps'], 1), round(
                r['avg'], 1), round(r['p95'], 1), r['errors']])
            print(
                f" {c:>11} | {'Asyncio':>10} | {r['rps']:>12.1f} | {r['avg']:>10.1f} | {r['p95']:>10.1f} | {r['errors']:>6}")
        print("-" * 85)

    print("\n" + "="*85)

    # Calculate champion
    print("  SUMMARY OF THROUGHPUT CHAMPION (Highest RPS):")
    for c in steps:
        scores = []
        for row in csv_servers:
            if row[0] == c:
                scores.append((row[1], row[2]))
        if scores:
            scores.sort(key=lambda x: x[1], reverse=True)
            winner = scores[0][0] if scores[0][1] > 0 else "N/A"
            print(f"   - Concurrency {c:<4}: 🏆 {winner}")

    headers = ["Concurrency", "Mode", "RPS", "Avg_ms", "P95_ms", "Errors"]
    save_csv("benchmark_servers.csv", headers, csv_servers)


if __name__ == "__main__":
    main()
