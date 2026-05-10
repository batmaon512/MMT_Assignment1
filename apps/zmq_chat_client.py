"""Simple ZeroMQ chat client for the server implemented in `apps.chatapp`.

Usage:
  python -m apps.zmq_chat_client --name alice --server 127.0.0.1:8001 --recv-port 8002

Client will:
 - bind a PULL socket at tcp://0.0.0.0:RECV_PORT to receive messages
 - connect a PUSH socket to server's PULL endpoint and send register/send messages
 - interactive prompt to send messages: /msg <to> <text> or /broadcast <text>
"""
import argparse
import threading
import zmq
import socket

def recv_loop(ctx, recv_port):
    sock = ctx.socket(zmq.PULL)
    bind_addr = f"tcp://0.0.0.0:{recv_port}"
    sock.bind(bind_addr)
    print(f"[client] Listening for incoming messages on {bind_addr}")
    try:
        while True:
            msg = sock.recv_json()
            print(f"INCOMING: {msg}")
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()

def main(name, server_addr, recv_port):
    ctx = zmq.Context()
    # PUSH socket to server
    push = ctx.socket(zmq.PUSH)
    server_tcp = f"tcp://{server_addr}"
    push.connect(server_tcp)

    # Start receiver thread
    t = threading.Thread(target=recv_loop, args=(ctx, recv_port), daemon=True)
    t.start()

    # Register with server
    my_ip = socket.gethostbyname(socket.gethostname())
    reg = {'type': 'register', 'name': name, 'recv_port': recv_port, 'ip': my_ip}
    push.send_json(reg)
    print(f"[client] Registered as {name} -> {my_ip}:{recv_port}")

    try:
        while True:
            line = input('> ')
            if not line:
                continue
            if line.startswith('/msg '):
                parts = line.split(' ', 2)
                if len(parts) < 3:
                    print('usage: /msg <to> <message>')
                    continue
                _, to, message = parts
                obj = {'type': 'send', 'from': name, 'to': to, 'message': message}
                push.send_json(obj)
            elif line.startswith('/broadcast '):
                message = line[len('/broadcast '):]
                obj = {'type': 'broadcast', 'from': name, 'message': message}
                push.send_json(obj)
            elif line in ('/quit', '/exit'):
                break
            else:
                print('commands: /msg /broadcast /quit')
    except KeyboardInterrupt:
        pass
    finally:
        push.close()
        ctx.term()

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='ZeroMQ chat client')
    p.add_argument('--name', required=True, help='User name to register with the server')
    p.add_argument('--server', default='127.0.0.1:8001', help='Chat server endpoint in host:port form')
    p.add_argument('--recv-port', type=int, required=True, help='Local port for the client PULL socket')
    args = p.parse_args()
    main(args.name, args.server, args.recv_port)
