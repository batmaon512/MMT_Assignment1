import argparse
import sys
import os

from imageapp import create_imageapp

PORT = 8080

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog='ImageApp', description='', epilog='ImageApp daemon')
    parser.add_argument('--server-ip', default='0.0.0.0')
    parser.add_argument('--server-port', type=int, default=PORT)

    args = parser.parse_args()

    create_imageapp(args.server_ip, args.server_port)
