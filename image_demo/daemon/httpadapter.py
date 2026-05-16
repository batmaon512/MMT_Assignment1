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
daemon.httpadapter
~~~~~~~~~~~~~~~~~

This module provides a http adapter object to manage and persist 
http settings (headers, bodies). The adapter supports both
raw URL paths and RESTful route definitions, and integrates with
Request and Response objects to handle client-server communication.
"""

from .request import Request
from .response import Response
from .dictionary import CaseInsensitiveDict

import asyncio
import inspect
import os
import time

class HttpAdapter:
    """
    A mutable :class:`HTTP adapter <HTTP adapter>` for managing client connections
    and routing requests.
    """

    __attrs__ = [
        "ip",
        "port",
        "conn",
        "connaddr",
        "routes",
        "request",
        "response",
    ]

    def __init__(self, ip, port, conn, connaddr, routes):
        self.ip = ip
        self.port = port
        self.conn = conn
        self.connaddr = connaddr
        self.routes = routes
        self.request = Request()
        self.response = Response()

    def process_request(self, raw_msg, addr):
        """
        Process an HTTP request from a raw message string.
        """
        req = self.request
        resp = self.response

        req.prepare(raw_msg, self.routes)
        req.remote_addr = addr
        print("[HttpAdapter] process_request {} {}".format(
            getattr(req, 'method', '?'), getattr(req, 'path', '?')
        ))

        # Guard: empty or malformed request
        if not req.path:
            return b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n"

        req.user = None

        from daemon.api import master_api_handler
        response = master_api_handler(req, resp)

        # If handler is coroutine → run synchronously
        if asyncio.iscoroutine(response):
            response = asyncio.run(response)

        if isinstance(response, str):
            response = response.encode('utf-8')

        return response

    def handle_client(self, conn, addr, routes):
        self.conn = conn
        self.connaddr = addr

        # Read data from socket (I/O layer)
        msg = ""
        while True:
            chunk = conn.recv(1024).decode('utf-8', errors='ignore')
            if not chunk:
                break
            msg += chunk
            if '\r\n\r\n' in msg:
                break

        print("\n" + "="*40)
        print("[HttpAdapter] handle_client from {}:".format(addr))
        print(msg[:200])
        print("="*40 + "\n")

        response = self.process_request(msg, addr)

        conn.sendall(response)
        conn.close()

    async def handle_client_coroutine(self, reader, writer):
        addr = writer.get_extra_info("peername")

        try:
            msg_bytes = b""
            # Đọc cho đến khi hết header
            while b"\r\n\r\n" not in msg_bytes:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                msg_bytes += chunk
                
            if not msg_bytes:
                return

            # Tìm Content-Length để biết xem body còn bao nhiêu byte
            header_part = msg_bytes.split(b"\r\n\r\n")[0]
            content_length = 0
            for line in header_part.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    try:
                        content_length = int(line.split(b":")[1].strip())
                    except:
                        pass
                    break
            
            # Tính toán và đọc nốt phần body còn thiếu (rất quan trọng cho ảnh Base64 lớn)
            body_already_read = len(msg_bytes) - (len(header_part) + 4)
            bytes_remaining = content_length - body_already_read
            
            while bytes_remaining > 0:
                chunk = await reader.read(min(16384, bytes_remaining))
                if not chunk:
                    break
                msg_bytes += chunk
                bytes_remaining -= len(chunk)

            raw_msg = msg_bytes.decode('utf-8', errors='replace')
            response = self.process_request(raw_msg, addr)

            if isinstance(response, str):
                response = response.encode('utf-8')

            writer.write(response)
            await writer.drain()

        except Exception as e:
            print("[HttpAdapter] handle_client_coroutine error:", e)
        finally:
            writer.close()
            await writer.wait_closed()

    @property
    def extract_cookies(self, req, resp):
        cookies = {}
        for header in headers:
            if header.startswith("Cookie:"):
                cookie_str = header.split(":", 1)[1].strip()
                for pair in cookie_str.split(";"):
                    key, value = pair.strip().split("=")
                    cookies[key] = value
        return cookies

    def build_response(self, req, resp):
        response = Response()
        response.encoding = get_encoding_from_headers(response.headers)
        response.raw = resp
        response.reason = response.raw.reason

        if isinstance(req.url, bytes):
            response.url = req.url.decode("utf-8")
        else:
            response.url = req.url

        response.cookies = self.extract_cookies(req, resp)
        response.request = req
        response.connection = self
        return response

    def build_json_response(self, req, resp):
        response = Response(req)
        response.raw = resp

        if isinstance(req.url, bytes):
            response.url = req.url.decode("utf-8")
        else:
            response.url = req.url

        response.request = req
        response.connection = self
        return response

    def add_headers(self, request):
        pass

    def build_proxy_headers(self, proxy):
        headers = {}
        username, password = ("user1", "password")
        if username:
            headers["Proxy-Authorization"] = (username, password)
        return headers
