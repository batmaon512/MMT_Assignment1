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
deamon.asynaprous
~~~~~~~~~~~~~~~~~

Lightweight web application router cho RESTful URL endpoints.
Không dùng asyncio — chỉ dùng Python standard library.

Cơ chế:
    - Decorator @app.route() đăng ký handler vào bảng routes.
    - app.run() → create_backend() → run_backend() với mode được chọn.

Supported modes (set qua daemon.backend.mode_async):
    - "coroutine" : asyncio event loop
    - "threading" : one thread per connection
    - "callback"  : custom select() event loop (không asyncio)
"""

import inspect
from .backend import create_backend


class AsynapRous:
    """
    The fully mutable :class:`AsynapRous <AsynapRous>` object, which is a lightweight,
    mutable web application router for deploying RESTful URL endpoints.

    The `AsynapRous` class provides a decorator-based routing system for building simple
    RESTful web applications.  The class allows developers to register route handlers
    using decorators and launch a TCP-based backend server to serve RESTful requests.
    Each route is mapped to a handler function based on HTTP method and path. It mappings
    supports tracking the combined HTTP methods and path route mappings internally.

    Usage::
      >>> import daemon.asynaprous
      >>> app = AsynapRous()
      >>> @app.route('/login', methods=['POST'])
      >>> def login(headers="guest", body="anonymous"):
      >>>     return {'message': 'Logged in'}

      >>> @app.route('/hello', methods=['GET'])
      >>> def hello(headers, body):
      >>>     return {'message': 'Hello, world!'}

      >>> app.run()
    """

    def __init__(self):
        """
        Initialize a new AsynapRous instance.

        Sets up an empty route registry and prepares placeholders for IP and port.
        """
        self.routes = {}
        self.ip     = None
        self.port   = None

    def prepare_address(self, ip, port):
        """
        Configure the IP address and port for the backend server.

        :param ip (str): The IP address to bind the server.
        :param port (str): The port number to listen on.
        """
        self.ip   = ip
        self.port = port

    def route(self, path, methods=['GET']):
        """
        Decorator to register a route handler for a specific path and HTTP methods.

        Tự động phát hiện sync/async handler qua inspect.
        Không cần asyncio — async handler sẽ được chạy qua asyncio.run()
        tạm thời trong make_http_handler() nếu cần.

        :param path (str): The URL path to route.
        :param methods (list): A list of HTTP methods (e.g., ['GET', 'POST']) to bind.

        :rtype: function - A decorator that registers the handler function.
        """
        def decorator(func):
            for method in methods:
                self.routes[(method.upper(), path)] = func

            # Gắn metadata lên function để dễ debug
            func._route_path    = path
            func._route_methods = methods

            def sync_wrapper(*args, **kwargs):
                print("[AsynapRous] running [{}] {}".format(methods, path))
                return func(*args, **kwargs)

            return sync_wrapper

        return decorator

    def run(self):
        """
        Start the backend server and begin handling requests.

        This method launches the TCP server using the configured IP and port,
        and dispatches incoming requests to the registered route handlers.

        :raise: Error if IP or port has not been configured.
        """
        if not self.ip or not self.port:
            raise RuntimeError(
                "[AsynapRous] Must call prepare_address(ip, port) before run()"
            )

        create_backend(self.ip, self.port, self.routes)
