ZeroMQ Chat backend (brokerless PUSH/PULL)

Overview
- Server: `apps.chatapp.create_chatapp(bind_ip, bind_port)` binds a PULL socket.
- Client: `apps/zmq_chat_client.py` binds a PULL socket to receive messages and connects PUSH to server to send/register.

Quick start
1. Install deps:
```
python -m pip install -r requirements.txt
```
2. Start server (uses same `start_chatapp.py` entrypoint):
```
python -m start_chatapp --server-ip 0.0.0.0 --server-port 8001
```
3. Start two clients in separate terminals:
```
python -m apps.zmq_chat_client --name alice --server 127.0.0.1:8001 --recv-port 8002
python -m apps.zmq_chat_client --name bob --server 127.0.0.1:8001 --recv-port 8003
```
4. From alice terminal:
```
/msg bob Hello Bob
/broadcast Hello everyone
```
