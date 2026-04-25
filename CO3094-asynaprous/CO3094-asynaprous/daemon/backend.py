#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# AsynapRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#

"""
daemon.backend
~~~~~~~~~~~~~~~~~

This module provides a backend object to manage and persist backend daemon. 
It implements a basic backend server using Python's socket and threading libraries.
It supports handling multiple client connections concurrently and routing requests using a
custom HTTP adapter.

Requirements:
--------------
- socket: provide socket networking interface.
- threading: Enables concurrent client handling via threads.
- response: response utilities.
- httpadapter: the class for handling HTTP requests.
- CaseInsensitiveDict: provides dictionary for managing headers or routes.


Notes:
------
- The server create daemon threads for client handling.
- The current implementation error handling is minimal, socket errors are printed to the console.
- The actual request processing is delegated to the HttpAdapter class.

Usage Example:
--------------
>>> create_backend("127.0.0.1", 9000, routes={})

"""

import socket
import threading
import argparse
import ssl

import asyncio
import inspect

from .response import *
from .httpadapter import HttpAdapter
from .dictionary import CaseInsensitiveDict

import selectors
sel = selectors.DefaultSelector()

mode_async = "callback"
#mode_async = "coroutine"
mode_async = "threading"

def handle_client(ip, port, conn, addr, routes):
    """
    Initializes an HttpAdapter instance and delegates the client handling logic to it.

    :param ip (str): IP address of the server.
    :param port (int): Port number the server is listening on.
    :param conn (socket.socket): Client connection socket.
    :param addr (tuple): client address (IP, port).
    :param routes (dict): Dictionary of route handlers.
    """
    print("[Backend] Invoke handle_client accepted connection from {}".format(addr))
    daemon = HttpAdapter(ip, port, conn, addr, routes)

    # Handle client
    daemon.handle_client(conn, addr, routes)


# Callback for handling new client (itself run in sync mode)
def handle_client_callback(server, ip, port,conn, addr, routes):
    """
    Initialize connection instance and delegates the client handling logic to it.

    :param ip (str): IP address of the server.
    :param port (int): Port number the server is listening on.
    :param routes (dict): Dictionary of route handlers.
    """
    print("[Backend] Invoke handle_client_callback accepted connection from {}".format(addr))

    daemon = HttpAdapter(ip, port, conn, addr, routes)

    # Handle client
    daemon.handle_client(conn, addr, routes)


# Coroutine async/await for handling new client
async def handle_client_coroutine(reader, writer):
    """
    Coroutine in async communication to initialize connection instance
    then delegates the client handling logic to it.

    :param reader (StreamReader): Stream reader wrapper.
    :param write (Stream write): Stream write wrapper.
    """
    addr = writer.get_extra_info("peername")
    print("[Backend] Invoke handle_client_coroutine accepted connection from {}".format(addr))

    # Handle client in asynchronous mode
    while True:
          daemon = HttpAdapter(None, None, None, None, None)
          await daemon.handle_client_coroutine(reader, writer)

async def async_server(ip="0.0.0.0", port=7000, routes={}):
    print("[Backend] async_server **ASYNC** listening on port {}".format(port))
    if routes != {}:
        print("[Backend] route settings")
        for key, value in routes.items():
            isCoFunc = ""
            if inspect.iscoroutinefunction(value):
               isCoFunc += "**ASYNC** "
            print("   + ('{}', '{}'): {}{}".format(key[0], key[1], isCoFunc, str(value)))

    async_server = await asyncio.start_server(handle_client_coroutine, ip, port)
    async with async_server:
        await async_server.serve_forever()
    return


def run_backend(ip, port, routes):
    """
    Starts the backend server, binds to the specified IP and port, and listens for incoming
    connections. Each connection is handled in a separate thread. The backend accepts incoming
    connections and spawns a thread for each client.


    :param ip (str): IP address to bind the server.
    :param port (int): Port number to listen on.
    :param routes (dict): Dictionary of route handlers.
    """
    # This global variable to configure the asynchrnous mode or not
    global mode_async

    print("[Backend] run_backend with routes={}".format(routes))
    # Process async stream for registering the service and terminate
    if mode_async == "coroutine":

       asyncio.run(async_server(ip, port, routes))
       return

    import select
    
    # --- 1. Tạo Socket cho HTTP (Ví dụ: port 9000) ---
    server_http = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_http.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    # --- 2. Tạo Socket cho HTTPS (Ví dụ: port 9001) ---
    server_https = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_https.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        # Khởi động server HTTP
        server_http.bind((ip, port))
        server_http.listen(50)
        print("[Backend] Listening on port {} (HTTP)".format(port))
        
        # Khởi động server HTTPS
        https_port = port + 1
        server_https.bind((ip, https_port))
        server_https.listen(50)
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")
        server_https = context.wrap_socket(server_https, server_side=True)
        print("[Backend] Listening on port {} (HTTPS enabled)".format(https_port))

        if routes != {}:
            print("[Backend] route settings")
            for key, value in routes.items():
               isCoFunc = ""
               if inspect.iscoroutinefunction(value):
                  isCoFunc += "**ASYNC** "
               print("   + ('{}', '{}'): {}{}".format(key[0], key[1], isCoFunc, str(value)))

        # Lắng nghe chung cả 2 socket
        sockets_to_listen = [server_http, server_https]

        while True:
            # Dùng select để chờ socket nào có khách gõ cửa
            readable, _, _ = select.select(sockets_to_listen, [], [])
            
            for s in readable:
                try:
                    # Accept connection
                    conn, addr = s.accept()
                except Exception as e:
                    print("[Backend] SSL/Accept error: {}".format(e))
                    continue

                if mode_async == "callback":
                   # Callback implementation - Event driven architecture
                   s.setblocking(False)
                   events = sel.select(timeout=None)
                   for key, mask in events:
                       callback, cb_ip, cb_port, cb_routes = key.data
                       callback(key.fileobj, cb_ip, cb_port, conn, addr, cb_routes)

                elif mode_async == "threading":
                   # Baseline multi-thread implementation
                   # Gửi port thực tế mà khách kết nối vào (port hoặc https_port)
                   actual_port = port if s is server_http else https_port
                   client_thread = threading.Thread(target=handle_client, args=(ip, actual_port, conn, addr, routes))
                   client_thread.daemon = True
                   client_thread.start()
    except socket.error as e:
      print("Socket error: {}".format(e))

def create_backend(ip, port, routes={}):
    """
    Entry point for creating and running the backend server.

    :param ip (str): IP address to bind the server.
    :param port (int): Port number to listen on.
    :param routes (dict, optional): Dictionary of route handlers. Defaults to empty dict.
    """

    run_backend(ip, port, routes)