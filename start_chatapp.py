import argparse
from apps.chatapp import create_chatapp

PORT = 8001

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='ChatApp', description='', epilog='ChatApp daemon')
    parser.add_argument('--server-ip', default='0.0.0.0')
    parser.add_argument('--server-port', type=int, default=PORT)
    parser.add_argument('--tracker-ip', default='127.0.0.1')
    parser.add_argument('--tracker-port', type=int, default=9000)
    
    args = parser.parse_args()

    create_chatapp(args.server_ip, args.server_port, args.tracker_ip, args.tracker_port)
