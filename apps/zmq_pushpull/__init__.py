"""Brokerless ZeroMQ push-pull examples.

Producer binds a PUSH socket; many workers connect with PULL sockets.
Also includes an inproc demo for intra-process low-latency messaging.
"""

__all__ = ["producer", "worker", "inproc_demo"]
"""ZeroMQ push-pull examples package."""
