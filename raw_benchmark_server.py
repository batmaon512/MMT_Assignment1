"""
raw_benchmark_server.py
=======================
Khởi chạy một máy chủ siêu nhẹ (Không HTTP Parsing, Không Routing, Không Object).
Mục đích: Đo lường giới hạn thông lượng mạng thuần túy (Raw Network Throughput)
của 3 kiến trúc: Threading, Select (Callback) và Asyncio.
"""
import socket
import select
import threading
import asyncio
import argparse

RESPONSE = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK"

def handle_client_sync(conn):
    try:
        conn.recv(1024)
        conn.sendall(RESPONSE)
    except:
        pass
    finally:
        conn.close()

def run_threading(port):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", port))
    server.listen(1000)
    print(f"[RAW THREADING] Sẵn sàng tại cổng {port}...")
    while True:
        try:
            conn, _ = server.accept()
            threading.Thread(target=handle_client_sync, args=(conn,), daemon=True).start()
        except KeyboardInterrupt:
            break

def run_callback(port):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", port))
    server.listen(1000)
    server.setblocking(False)
    
    r_list = [server]
    w_list = []

    print(f"[RAW CALLBACK - select()] Sẵn sàng tại cổng {port}...")
    while True:
        try:
            readable, writable, _ = select.select(r_list, w_list, [])
            for s in readable:
                if s is server:
                    conn, _ = s.accept()
                    conn.setblocking(False)
                    r_list.append(conn)
                else:
                    try:
                        data = s.recv(1024) # Chỉ đọc cho có, không parse
                        if data:
                            r_list.remove(s)
                            w_list.append(s) # Chuyển sang hàng đợi gửi
                        else:
                            r_list.remove(s)
                            s.close()
                    except:
                        if s in r_list: r_list.remove(s)
                        s.close()
            
            for s in writable:
                try:
                    s.sendall(RESPONSE) # Bắn thẳng phản hồi
                except:
                    pass
                finally:
                    if s in w_list: w_list.remove(s)
                    s.close()
        except KeyboardInterrupt:
            break
        except Exception:
            pass

async def handle_async(reader, writer):
    try:
        await reader.read(1024)
        writer.write(RESPONSE)
        await writer.drain()
    except:
        pass
    finally:
        writer.close()

def run_asyncio(port):
    print(f"[RAW ASYNCIO] Sẵn sàng tại cổng {port}...")
    async def main():
        server = await asyncio.start_server(handle_async, "0.0.0.0", port)
        async with server:
            await server.serve_forever()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["threading", "callback", "asyncio"], required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    if args.mode == "threading":
        run_threading(args.port)
    elif args.mode == "callback":
        run_callback(args.port)
    elif args.mode == "asyncio":
        run_asyncio(args.port)
