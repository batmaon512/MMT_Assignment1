import argparse
from apps.chatapp import create_chatapp

PORT = 8001

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog='ChatApp',
        description='Start the ZeroMQ chat backend',
        epilog='ZeroMQ chat server daemon',
    )
    parser.add_argument('--bind-ip', default='0.0.0.0', help='IP address for the server PULL socket to bind')
    parser.add_argument('--bind-port', type=int, default=PORT, help='Port for the server PULL socket to bind')
    parser.add_argument('--server-endpoint', help='Optional tcp://host:port override for the server bind endpoint')
    
    args = parser.parse_args()

    if args.server_endpoint:
        if not args.server_endpoint.startswith('tcp://'):
            raise SystemExit('--server-endpoint must start with tcp://')
        bind_ip, bind_port = args.server_endpoint.removeprefix('tcp://').rsplit(':', 1)
        create_chatapp(bind_ip, int(bind_port))
    else:
        create_chatapp(args.bind_ip, args.bind_port)
