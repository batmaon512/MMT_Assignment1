import argparse
from apps.trackerapp import create_trackerapp

PORT = 9000

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='Tracker', description='', epilog='Tracker daemon')
    parser.add_argument('--server-ip', default='0.0.0.0')
    parser.add_argument('--server-port', type=int, default=PORT)
    
    args = parser.parse_args()
    ip = args.server_ip
    port = args.server_port

    create_trackerapp(ip, port)
